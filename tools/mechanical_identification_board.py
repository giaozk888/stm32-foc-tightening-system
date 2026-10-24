"""Six explicit signed mechanical points, fixed numeric Ka. Files-only default."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import zlib
import bemf_flux_gain_batch as previous
import mechanical_identification_report as analysis

base=previous.base;prior=previous.prior;fitted=previous.fitted;TMP=previous.TMP
ROOT_RESTORE=TMP/'bemf-flux-gain-restore-1792667152375350500.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/MechanicalIdentificationMotionCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='55551e57859c6b46a718fe1b61a5cf0f42dcb60ec02b939e1c34ec70fb38d5a5'
ELF_SHA='913902c8e0c5f0c61e5b60c4dc86a721142262cb472b7f233e3aa869c89d573b'
SIZE=208288
KA=.000046875
PSI=.00034866
POINTS=(100,-100,200,-200,240,-240)
TRIP_RPM=300
TRAVEL_DEG=20000
CLOSURE_SECONDS=7.5
LIMITS_QUERY=False
LIMITS_EXTRA={}


def image():
    data=IMAGE.read_bytes()
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if x['file'].endswith('/Core/Src/main.c'))
    flags=('FOC_MECHANICAL_IDENT_DIAG=1','FOC_MECHANICAL_MOTION_DIAG=1',
        'FOC_FRICTION_CALIBRATION_DIAG=1','FOC_BEMF_CANDIDATE=1',
        'FOC_BEMF_PSI_WB=0.00034866f','FOC_BEMF_ENABLED_DEFAULT=1',
        'SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f','FOC_FRICTION_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','FOC_PROTECTED_CLOSED_LOOP=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'AS5047P_DMA_FOC_FIRST=1','FOC_SPEED_PI_ANTI_WINDUP=1','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+x+' ' not in cmd for x in flags) or
        any('-D'+x in cmd for x in ('FOC_KA_FULL_DIAG','FOC_KA_SYNC_DIAG',
            'FOC_KA_IDENT_DIAG','FOC_ACCEL_FF_AUDIT','FOC_BEMF_GAIN_DIAG',
            'FOC_DQ_DECOUPLING_CANDIDATE','FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        base.symbols(ELF).get('mechanical_capture',(0,0))[1]!=analysis.SIZE):
        raise ValueError('Exact reviewed mechanical motion image required')
    for marker in (b'MECH_IDENT_DIAGNOSTIC: manual signed point; fixed compensation; no START',
                   b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'TRAVEL=20000deg RAM only',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Required manual/protection marker missing')
    base.support.support.require_baud(cmd)
    return data


def bemf_status(line):
    v=base.hw.fields(line)
    if any(v.get(k)!=x for k,x in dict(ON='1',CONFIGURED='1',PSI_NWB='348660',DQ_CROSS='0').items()):
        raise RuntimeError('Fixed 0.00034866Wb BEMF ON required; no motion')
    return v


def rest_status(line):
    v=base.hw.fields(line)
    if any(v.get(k)!=x for k,x in dict(FLT='0',BUSY='0',MODE='IDLE').items()):
        raise RuntimeError('Mechanical rest/idle precheck failed; no motion')
    for key in ('CTRL','DET'):
        try:value=float(v[key].removesuffix('rpm'))
        except (KeyError,ValueError):raise RuntimeError('Measured rest speed missing; no motion')
        if not math.isfinite(value) or abs(value)>2:
            raise RuntimeError('Rotor not at rest; no motion or automatic retry')
    return v


def setup(path):
    previous.setup(ROOT_RESTORE);base.baseline() # Exact B1007 / flux diagnostic first.
    for obj in (base,previous.gain,fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    previous.gain.SIZE=SIZE;fitted.SIZE=SIZE;fitted.PSI_WB=PSI
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


class MechanicalConsole(base.TokenConsole):
    def query(self,text,timeout=2):
        if text not in ('MOTOR TEST MECH STATUS','MOTOR TEST FF STATUS',
                        'MOTOR TEST FRIC STATUS','MOTOR TEST BEMF STATUS','MOTOR TEST MECH LIMITS'):
            return super().query(text,timeout)
        self.request+=1;request=self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=self.read_line(min(.02,max(0,end-time.monotonic())))
            if line is None:continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '):raise RuntimeError(line)
                return line
        raise TimeoutError('Read-only query ACK missing; no retry: '+text)


class MechanicalBoard(prior.BatchBoard):
    def send(self,command):
        request=super().send(command)
        if command.startswith('MOTOR TEST MECH RUN '):
            self.bemf_active=True;self.bemf_next=time.monotonic()+self.query_interval_s
        return request


def run_point(row,name,source,before,data,rpm,first):
    if rpm not in POINTS:raise ValueError('Unsupported mechanical point')
    port=base.support.support.open_port();uart=MechanicalConsole(port,row)
    try:
        row['hardware_attempted']=True
        commands=[*base.old.zero.off_gate(),*base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
                  'reset halt',*base.hw.off_commands()]
        if first:commands+=base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data)))
        commands+=['reset run','shutdown'];base.hw.debug(row,commands)
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('MECH_IDENT_DIAGNOSTIC: manual signed point' in x for x in uart.lines):
            raise RuntimeError('Wrong mechanical startup marker; no motion')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        base.profile(uart.query('MOTOR TEST PROFILE'));base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.ff_status(uart.query('MOTOR TEST FF STATUS'))
        base.friction_status(uart.query('MOTOR TEST FRIC STATUS'),True)
        bemf_status(uart.query('MOTOR TEST BEMF STATUS'))
        if LIMITS_QUERY:
            limits=base.hw.fields(uart.query('MOTOR TEST MECH LIMITS'))
            expected=dict(API_RPM='800',TRIP_RPM=str(TRIP_RPM),IQ_LIMIT_MA='500',
                TRAVEL_DEG=str(TRAVEL_DEG),DRIVE_MS='5000',STOP_MS='10500',LEASE_US='12000000')
            expected.update(LIMITS_EXTRA)
            if any(limits.get(k)!=v for k,v in expected.items()):
                raise RuntimeError('Exact supervised high-speed limits required; no motion')
            row['motion_limits']=limits
        initial=base.hw.fields(uart.query('MOTOR TEST MECH STATUS'))
        if any(initial.get(k)!=v for k,v in dict(USED='0',ACTIVE='0',DONE='0',FRIC='1',DRIVE_MS='5000',LEASE_US='12000000').items()):
            raise RuntimeError('Unused fixed mechanical diagnostic not ready')
        base.old.prior.wait_timing(uart,row)
        port.close();board=MechanicalBoard('COM5',row)
        try:
            base.require_idle_ready(board,'A')
            stack=base.motor_stack(board);row['motor_stack_preflight']=stack
            if stack.get('VALID')!='1' or int(stack.get('FREE_B','0'))<256:
                raise RuntimeError('Insufficient motor-task stack; no motion')
            # Repeat all compensation readbacks immediately before admission.
            base.ff_status(board.command('MOTOR TEST FF STATUS'))
            base.friction_status(board.command('MOTOR TEST FRIC STATUS'),True)
            bemf_status(board.command('MOTOR TEST BEMF STATUS'))
            row['rest_before_start']=rest_status(board.command('STATUS'))
            row['preflight_pass']=True;row['start_attempts']=1
            prior.checkpoint(row,'single_MECH_command_intent')
            command='MOTOR TEST MECH RUN '+('POS' if rpm>0 else 'NEG')+' '+str(abs(rpm))
            row['motion_ack']=board.command(command,.6)
            if ' OK MECH QUEUED RPM='+str(rpm) not in row['motion_ack']:
                raise RuntimeError('Mechanical command not admitted; no retry')
            end=time.monotonic()+CLOSURE_SECONDS
            while time.monotonic()<end:
                state=base.hw.fields(board.command('MOTOR TEST STATUS',.3))
                if state.get('FAULT')!='0' or state.get('FLAGS')!='0':
                    raise RuntimeError('Independent protection; stop entire batch')
                status=base.hw.fields(board.command('MOTOR TEST MECH STATUS',.3))
                if status.get('RPM')!=str(rpm) or status.get('FRIC')!='1':raise RuntimeError('Motion configuration mismatch')
                row['samples'].append(dict(at=time.monotonic(),status=status))
                prior.checkpoint(row,'mechanical_feedback')
                if status.get('DONE')=='1' and status.get('ACTIVE')=='0':
                    row['mechanical_terminal']=status;break
                until=min(end,time.monotonic()+.1)
                while time.monotonic()<until:board.read_line(min(.02,until-time.monotonic()))
            else:raise TimeoutError('Configured drive/deceleration closure did not finish; no next point')
        finally:
            try:base.stop(board)
            finally:
                try:
                    row['safe_ack']=board.command('ANALOG SAFE',.8)
                    row['safe']=base.hw.fields(board.command('ANALOG SAFE STATUS',.8))
                    if any(row['safe'].get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
                        raise RuntimeError('Output-off latch absent')
                    for cmd in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS'):
                        row['postflight'][cmd]=board.command(cmd,.8)
                    row['terminal_status']=base.hw.fields(row['postflight']['STATUS'])
                finally:board.close()
    finally:
        if port.is_open:
            try:row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error:row['stop_error']=str(error)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:
                previous.ORIGINAL_DECODE(row)
    if not analysis.board_acceptance(row) or not row.get('mechanical_terminal') or row.get('stop_error'):
        raise RuntimeError('Mechanical safety/closure evidence failed; no next point')
    frames=[x['values'] for x in row.get('bemf_samples',[]) if x['values'].get('VALID')=='1']
    active=[v for v in frames if abs(int(v.get('WE_MRAD_S','0')))>=50000]
    if not active or any(v.get('ON')!='1' or abs(int(v['VQ_FF_UV'])-int(v['WE_MRAD_S'])*PSI*1000)>3 for v in active):
        raise RuntimeError('Fixed BEMF formula evidence missing')
    row.update(pass_=True,acquisition_complete=True,tightening_success=False)
    prior.checkpoint(row,'captured_before_mechanical_decode')
    row['mechanical_capture']=analysis.decode(Path(row['receipt_path']),ELF)
    if not row['mechanical_capture']['board_verified']:raise RuntimeError('Mechanical capture provenance failed')


def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh powered whole-batch confirmation required')
    plan=json.loads(path.read_text())
    if plan.get('speeds_rpm')!=list(POINTS) or plan.get('ka_a_per_rpm_s')!=KA:
        raise ValueError('Exact mechanical point order and numeric-Ka plan required')
    if LIMITS_QUERY and (plan.get('overspeed_trip_rpm')!=TRIP_RPM or plan.get('travel_limit_deg')!=TRAVEL_DEG):
        raise ValueError('Exact high-speed trip/travel plan required')
    data=image();source,before=base.staged(path,data)
    for index,rpm in enumerate(POINTS,1):
        name='mechanical-ident-run-'+str(time.time_ns())
        row=prior.new_run(name,parent,True,index)
        row.update(rpm=rpm,ka_a_per_rpm_s=KA,psi_f_wb=PSI,friction_enabled=True,
            automatic_parameter_write=False,dob_control_enabled=False,
            overspeed_trip_rpm=TRIP_RPM,travel_limit_deg=TRAVEL_DEG,host_max_seconds=CLOSURE_SECONDS)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'point_'+str(index)+'_intent');prior.checkpoint(row,'prepared')
        print('MECHANICAL POINT %d/%d %+d rpm; Ka=0.000046875 A/(rpm/s)'%(index,len(POINTS),rpm),flush=True)
        try:
            run_point(row,name,source,before,data,rpm,index==1)
            prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(row['receipt_path'])
            source=Path(row['final_capture']);before=source.read_bytes()
            prior.checkpoint(parent,'point_'+str(index)+'_saved')
            print('ACQUIRED %d/%d bins=%d flags=%d'%(index,len(POINTS),row['mechanical_capture']['meta']['count'],row['mechanical_capture']['meta']['flags']),flush=True)
        except BaseException as error:
            row['pass_']=False;row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            prior.checkpoint(row,'batch_stopped_no_retry');raise
    captures=[analysis.decode(Path(p),ELF) for p in parent['runs']]
    parent['identification']=analysis.report(captures) # No assumed Kt, no actuator writes.
    parent.update(pass_=True,acquisition_complete=True,final_outputs_off=row['final_outputs_off'],final_cpu_halted=row['final_cpu_halted'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-six',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_six and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh whole-batch powered confirmation required')
    source=a.execute_six or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not(a.prepare_off or source):print('OFFLINE PASS: Ka=0.000046875 A/(rpm/s), %d mechanical points; no devices'%len(POINTS));return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='mechanical-ident-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},runs=[],attempts=[],image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),ka_a_per_rpm_s=KA,psi_f_wb=PSI,
        speeds_rpm=list(POINTS),physical_power_off=a.drive_off_unlocked_no_load_fixed,
        overspeed_trip_rpm=TRIP_RPM,travel_limit_deg=TRAVEL_DEG,
        automatic_retry=False,automatic_parameter_write=False,dob_control_enabled=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute(source,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())

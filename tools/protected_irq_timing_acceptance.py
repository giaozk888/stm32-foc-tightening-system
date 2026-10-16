"""One exact optimized-B trial; compute-only ADC/FOC observation, no motion.

Use only after the user enables drive 12 V with motor leads disconnected.
Preserves fallback and private regions. Normal health confirmation only.
"""
import argparse
import json
from pathlib import Path
import time

import protected_irq_optimized_stage as profile
import protected_closed_loop_acceptance as shared
from firmware_transfer_iap import fields
from powered_boot_probe import require_staged
from zero_retest_deploy import require_confirmed, compare_flash, latest_meta


class TimingConsole(shared.Console):
    READ=shared.Console.READ | frozenset(('ADC WINDOW','ADC BUFFER','ENC DIAG','MOTOR TEST COST','MOTOR TEST LATE'))
    def query(self,text,timeout=2):
        if text not in self.READ and text not in ('FW END','ANALOG SAFE'):
            raise ValueError('Compute-only: no motor, reset, clear or selection command')
        return super().query(text,timeout)

    def encoder_diag(self):
        """Collect all same-request ENC lines, including pre-clear fault evidence."""
        first=self.query('ENC DIAG')
        if ' OK ENC DMA ' not in first:
            raise RuntimeError('Encoder DMA status missing: '+first)
        request=first.split(' ',1)[0]
        result={'dma':fields(first)}
        kinds=(('ENC SNAP','snapshot'),('ENC SPI','spi'),('ENC DMAHW','dma_hw'),
               ('ENC IRQ','irq'),
               ('ENC DIAG','diag'),('ENC STACK','stack'))
        deadline=time.monotonic()+1.0
        while time.monotonic()<deadline:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if not line.startswith(request+' OK '): continue
            for marker,key in kinds:
                if ' OK '+marker+' ' in line:
                    result[key]=fields(line)
                    break
            if 'stack' in result: break
        if 'stack' not in result:
            raise TimeoutError('Encoder diagnostic lines incomplete')
        return result


def adc_timing(line):
    s=fields(line)
    if (s.get('DWT')!='1' or s.get('MISS')!='0' or s.get('PF')!='0' or
        not 0<int(s.get('MAX_CYC','0'))<8500 or int(s.get('PAIRS','0'))<1000):
        raise RuntimeError('ADC pair/IRQ budget evidence failed: '+line)
    return s


def read_sample(uart):
    row=dict(host_time=time.monotonic())
    row['state']=fields(uart.query('MOTOR TEST STATUS'))
    # Drain all tagged status/snapshot/IRQ lines from the same request;
    # preserve hardware evidence before enforcing acceptance criteria.
    encoder=uart.encoder_diag()
    row['encoder_dma']=encoder['dma']
    row['encoder_snapshot']=encoder.get('snapshot')
    row['encoder_spi']=encoder.get('spi')
    row['encoder_dma_hw']=encoder.get('dma_hw')
    row['encoder_irq']=encoder.get('irq')
    # Capture all diagnostics before enforcing their pass criteria, so a
    # stopped computation keeps useful timing/fault evidence in the receipt.
    for key,cmd in (('timing','MOTOR TEST TIMING'),('adc','ADC TIMING'),
                    ('protection','MOTOR TEST PROTECTION'),('buffer','ADC BUFFER'),
                    ('fault','MOTOR TEST FAULT')):
        row[key]=fields(uart.query(cmd))
    if getattr(profile,'REQUIRE_COST',False):
        row['cost']=fields(uart.query('MOTOR TEST COST'))
    if getattr(profile,'REQUIRE_LATE',False):
        row['late_frame']=fields(uart.query('MOTOR TEST LATE'))
    row['status']=uart.query('STATUS')
    return row


def validate_sample(row):
    def line(key): return 'OK '+' '.join(f'{k}={v}' for k,v in row[key].items())
    shared.protected_state(line('state'),ready=True)
    shared.timing(line('timing'))
    shared.protection(line('protection'))
    adc_timing(line('adc'))
    b=row['buffer']
    if b.get('STK_VALID')!='1' or int(b.get('FREE_B','0'))<256 or int(b.get('DONE','0'))<1:
        raise RuntimeError('Background double-buffer worker not validated')
    if fields(row['status']).get('FLT')!='0' or row['fault'].get('VALID')!='0':
        raise RuntimeError('Compute-only motor/fault status failed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',type=Path,required=True)
    p.add_argument('--allow-single-compute-trial',action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=p.parse_args()
    if not(args.allow_single_compute_trial and args.drive_12v_on_motor_disconnected):
        p.error('Compute trial permission and powered, motor-disconnected state required')
    data=profile.pinned_image()
    before,staged=shared.stage_evidence(args.stage,data,source_profile=profile)
    run=str(time.time_ns()); out=profile.OUTPUT/f'irq-compute-{run}.json'
    row=dict(pass_=False,image_sha256=profile.SHA,stage=str(args.stage.resolve()),
             steps=[],samples=[],motor_disconnected=True,force_confirmation=False,
             closed_loop_motor_test=False,automatic_host_retry=False)
    board=profile.Board(row,run); port=uart=None; activated=False
    try:
        if board.capture('before_trial')!=staged: raise RuntimeError('Stage Flash changed')
        row['before_outputs']=board.outputs('A',False)
        port=profile.open_port(); uart=TimingConsole(port)
        fw=uart.query('FW STATUS')
        require_staged(fw,'0 OK SAFE SOURCE=SWD SD=0 MOE=0 CEN=0',data)
        if fields(fw).get('GEN')!=str(latest_meta(before)[5]):
            raise RuntimeError('Not exact confirmed stage requester')
        activated=True
        try: row['commit_ack']=uart.query('FW END',5)
        except TimeoutError: row['commit_ack_uncertain']=True
        deadline=time.monotonic()+90; saw_b=False
        while time.monotonic()<deadline:
            try: fw=uart.query('FW STATUS',.5)
            except TimeoutError: continue
            f=fields(fw)
            if f.get('CURRENT')=='B':
                saw_b=True
                try: state=fields(uart.query('MOTOR TEST STATUS',.5))
                except TimeoutError: continue # read across normal confirmation reset
                if state.get('STATE')=='4':
                    encoder=uart.encoder_diag()
                    row['startup_encoder_dma']=encoder['dma']
                    row['startup_encoder_snapshot']=encoder.get('snapshot')
                    row['startup_encoder_spi']=encoder.get('spi')
                    row['startup_encoder_dma_hw']=encoder.get('dma_hw')
                    row['startup_encoder_irq']=encoder.get('irq')
                    row['startup_sample']=read_sample(uart)
                    row['startup_zero']=fields(uart.query('MOTOR TEST ZERO'))
                    raise RuntimeError('Startup fault; no reset/activation retry')
            if saw_b and f.get('CURRENT')=='A' and f.get('PENDING')=='-':
                raise RuntimeError('Bootloader rollback; no force confirmation')
            if (f.get('CURRENT')=='B' and f.get('CONFIRMED')=='B' and
                f.get('PENDING')=='-' and f.get('ACTIVE')=='0'):
                row['confirmed']=require_confirmed(fw,'B'); break
            uart.poll(.1)
        else: raise TimeoutError('Normal health confirmation absent')
        row['protected_regions']=compare_flash(before,board.capture('confirmed'),data,'B')
        row['compute_outputs']=board.outputs('B',True)
        row['zero']=fields(uart.query('MOTOR TEST ZERO'))
        row['window']=fields(uart.query('ADC WINDOW'))
        if row['window'].get('READY')!='1': raise RuntimeError('ADC window not ready')
        observation=float(getattr(profile,'OBSERVE_SECONDS',3.0))
        if not 3.0<=observation<=60.0:
            raise ValueError('Bounded compute observation must be 3..60 seconds')
        row['requested_observation_seconds']=observation
        end=time.monotonic()+observation
        while time.monotonic()<end:
            sample=read_sample(uart); row['samples'].append(sample)
            validate_sample(sample)
            uart.poll(.05)
        first,last=row['samples'][0],row['samples'][-1]
        for key,counter in (('adc','PAIRS'),('timing','WORK'),('timing','OUTER'),('buffer','DONE')):
            if int(last[key][counter])<=int(first[key][counter]):
                raise RuntimeError('Sampling, FOC or worker stopped: '+counter)
        row['observed_seconds']=last['host_time']-first['host_time']
        row['observed_pairs']=int(last['adc']['PAIRS'])-int(first['adc']['PAIRS'])
        row['irq_max_us']=int(last['adc']['MAX_CYC'])/170.0
        row['compute_max_us']=int(last['timing']['MAX_US'])
        row['coarse_remaining_alarm']=int(last['adc']['LATE'])
        row['coarse_alarm_not_physical_sample_misses']=True
        row['pass_']=True
    except BaseException as error:
        row['failure']=str(error); raise
    finally:
        if uart and activated:
            try:
                row['final_fw']=f=fields(uart.query('FW STATUS'))
                row['maintenance_off']=uart.query('ANALOG SAFE')
                row['final_safe']=s=fields(uart.query('ANALOG SAFE STATUS'))
                if any(s.get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))):
                    raise RuntimeError('Final output lock missing')
                slot=f.get('CURRENT')
                if slot not in ('A','B'): raise RuntimeError('Unknown final slot')
                row['final_outputs']=board.outputs(slot,False)
                final=board.capture('final')
                if row.get('confirmed'): compare_flash(before,final,data,'B')
                row['final_outputs_off']=True
            except BaseException as error:
                row['pass_']=False; row['cleanup_failure']=str(error)
                print('Cleanup not proved: turn off drive 12 V; no retries',flush=True)
        if uart:
            row['uart']=uart.lines; row['host_trial_commits']=uart.ends
            row['host_motor_commands']=uart.starts
        if port: port.close()
        out.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(('COMPUTE TIMING PASS' if row['pass_'] else 'COMPUTE TIMING FAIL')+
              ': no motor command; not motor closed-loop qualification',flush=True)
        print('Evidence: '+str(out),flush=True)

if __name__=='__main__': main()

"""One SD-low PWM signal capture on exact confirmed B446; never bridge/motor."""
import argparse
import json
import re
import statistics
import subprocess
import time
from firmware_transfer_iap import fields
from switch_feedback_acceptance import Console as BaseConsole, require_switch
from switch_trend_off_capture import Console as OffConsole, require_trend
from switch_feedback_off_capture import analyze
from switch_trend_compare_deploy import SHA, OLD_A, OUTPUT, image
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers

OFF_EVIDENCE=OUTPUT/'off-1791879204193467700.json'

def zero_reference(line):
    # The legacy shared fields() parser intentionally accepts letters/underscores
    # only; U0/V0 need explicit parsing here, not a global protocol change.
    values=dict(re.findall(r'\b(U0|V0)=(\d+)\b',line))
    if set(values)!=set(('U0','V0')): raise RuntimeError('Missing calibrated zero fields')
    result=tuple(int(values[key]) for key in ('U0','V0'))
    if any(not 0<=value<=4095 for value in result): raise RuntimeError('Invalid calibrated zero')
    return result

class Console(OffConsole):
    def query(self,text,timeout=2):
        if text in ('SWITCH START PWM','ZERO FILTER STATUS'):
            return BaseConsole.query(self,text,timeout)
        if text=='SWITCH START OFF': raise ValueError('PWM-only capture')
        return super().query(text,timeout)

def before_capture(line):
    row=require_switch(line,mode=1,complete=True)
    if int(row['DONE']) & 18 != 18 or int(row['ATTEMPTS']) & 4:
        raise RuntimeError('Guard/OFF prerequisites missing or PWM already attempted')
    if row.get('WAVE')!='0': raise RuntimeError('Unexpected physical waveform marker')
    return row

def start_proof(line):
    row=require_switch(line,mode=2)
    if row.get('SD')!='0': raise RuntimeError('SD must remain low')
    if row['ACTIVE']=='1' and any(row.get(k)!=v for k,v in
                                  (('MOE','1'),('CCER','1365'),('CEN','1'))):
        raise RuntimeError('Unexpected PWM signal state')
    return row

def common_reference(samples,zero):
    return dict(pairs=len(samples),reference=list(zero),
                outside_100_pairs=sum(any(abs(p[c]-zero[c])>100 for c in (0,1)) for p in samples),
                channels=[dict(mean=statistics.mean(p[c] for p in samples),
                               stddev=statistics.pstdev(p[c] for p in samples),
                               minimum=min(p[c] for p in samples),maximum=max(p[c] for p in samples),
                               max_abs_deviation=max(abs(p[c]-zero[c]) for p in samples)) for c in (0,1)])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-sd-low-pwm',action='store_true')
    args=parser.parse_args()
    if not args.allow_sd_low_pwm: parser.error('Explicit SD-low signal switching required')
    image()
    off=json.loads(OFF_EVIDENCE.read_text('utf-8'))
    if not off.get('pass_') or off.get('image_sha256')!=SHA or off['capture']['MODE']!='1':
        raise RuntimeError('Pinned saved OFF evidence missing')
    analyze(off['samples'],off['capture'])
    OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F',
                    '*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'pwm-{run}.json'
    record=dict(pass_=False,image_sha256=SHA,mode='SD_LOW_PWM_SIGNALS',resets=0,flash_writes=0,
                bridge_enabled=False,motion_commands=False,automatic_retry=False,
                waveform_physically_verified=False,steps=[])
    port=uart=None; start_sent=False; stopped=False
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD failed; no retry')
        return p.stdout+p.stderr
    def outputs():
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        return require_registers(cli(*tokens),'B')
    try:
        record['before_outputs']=outputs()
        backup=private/f'{run}-pwm-identity.bin'; cli('-u','0x08000000','0x80000',backup)
        record['identity_backup']=str(backup)
        base=locked_baseline(backup.read_bytes(),known={'A':frozenset((OLD_A,)),'B':frozenset((SHA,))})
        if base['current']!='B' or base['generation']!=446: raise RuntimeError('Exact B446 required')
        record['baseline']=base
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        record['before_fw']=fw=require_confirmed(uart.query('FW STATUS'),'B')
        if fw.get('GEN')!='446': raise RuntimeError('UART/Flash mismatch')
        record['before_zero_line']=uart.query('ZERO STATUS')
        record['before_zero']=zero=require_service(record['before_zero_line'])
        calibrated_reference=zero_reference(record['before_zero_line'])
        if zero.get('STATE')!='3' or zero.get('N')!='4000': raise RuntimeError('Expected existing median calibration missing')
        record['before_filter']=fields(uart.query('ZERO FILTER STATUS'))
        record['before_switch']=before_capture(uart.query('SWITCH STATUS'))
        record['analog_before']=analog=fields(uart.query('ANALOG VOLT'))
        if (analog.get('VALID')!='1' or not 10000<=int(analog.get('VBUS_EST_MV','0'))<=14000
            or not 3000<=int(analog.get('VDDA_BOOT_MV','0'))<=3600):
            raise RuntimeError('Sensing supply not ready; PWM not sent')
        start_sent=True
        record['start_line']=uart.query('SWITCH START PWM')
        record['start']=start_proof(record['start_line'])
        time.sleep(.25)  # No UART polling or SWD while capturing.
        record['capture_line']=uart.query('SWITCH STATUS')
        row=require_switch(record['capture_line'],mode=2)
        if row.get('ACTIVE')!='0':
            record['abort']=uart.query('SWITCH ABORT')
            raise RuntimeError('Active past cutoff; aborted, no restart')
        record['final_outputs']=outputs(); stopped=True
        record['capture']=row
        n=int(row['N'])
        if not 0<n<=3600: raise RuntimeError('Bounded capture has no valid samples')
        record['samples']=samples=[]
        for i in range(n):
            pair=fields(uart.query(f'SWITCH READ {i}'))
            if pair.get('I')!=str(i): raise RuntimeError('Saved index mismatch')
            samples.append((int(pair['U']),int(pair['V'])))
            if (i+1)%900==0: print(f'Read saved pairs {i+1}/{n}; outputs already OFF',flush=True)
        record['analysis']=analyze(samples,row)
        record['analysis']['nominal_reference_not_published_calibration']=False
        record['trend_line']=uart.query('SWITCH TREND STATUS')
        record['trend']=require_trend(record['trend_line'],samples)
        reference=tuple(map(int,row['ZERO'].split(',')))
        if reference!=calibrated_reference: raise RuntimeError('Calibration reference mismatch')
        record['comparison']=dict(reference=list(reference),off_evidence=str(OFF_EVIDENCE),
                                  off=common_reference(off['samples'],reference),
                                  pwm=common_reference(samples,reference),
                                  single_non_simultaneous_comparison_not_causal_proof=True)
        record['final_fw']=fw=require_confirmed(uart.query('FW STATUS'),'B')
        if fw.get('GEN')!='446': raise RuntimeError('Unexpected generation change')
        require_switch(record['capture_line'],mode=2,complete=True)
        if int(row['DONE']) & 22 != 22 or row.get('WAVE')!='0': raise RuntimeError('Unexpected completion/wave marker')
        record['pass_']=True
        print(record['capture_line'],flush=True)
        print('SD-LOW PWM CAPTURE PASS: raw/median/Trend4 replay matches; bridge and motor NOT tested',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if start_sent and not stopped and uart:
            # Lost ACK is not a reason to resend START; request OFF only.
            try: record['emergency_abort']=uart.query('SWITCH ABORT')
            except Exception as error: record['abort_failure']=str(error)
            try: record['cleanup_outputs']=outputs()
            except Exception as error: record['off_proof_failure']=str(error)
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

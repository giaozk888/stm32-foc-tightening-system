"""One hard-off ZERO SAMPLE on exact B446. Never starts PWM, bridge or motor.

Raw and median qualifiers are reported separately; neither is silently
substituted for the other. No reset, Flash write, fault clear or retry.
"""
import argparse
import json
import subprocess
import time
from firmware_transfer_iap import fields
from switch_feedback_zero_check import ZeroConsole
from switch_feedback_acceptance import require_switch
from switch_trend_compare_deploy import SHA, OLD_A, OUTPUT, image
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers

def qualification(zero, filtered):
    median_ready=(zero.get('STATE')=='3' and zero.get('REASON')=='0'
                  and zero.get('N')=='4000' and filtered.get('FILTER_STATE')=='3'
                  and filtered.get('FILTER_REASON')=='0')
    raw_ready=(filtered.get('RAW_STATE')=='3' and filtered.get('RAW_REASON')=='0'
               and filtered.get('RAW_N')=='4000' and filtered.get('OUT')=='0')
    return dict(median_zero_ready=median_ready,raw_zero_ready=raw_ready,
                both_zero_qualifiers_pass=median_ready and raw_ready,
                motor_qualified=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-hard-off-zero-check',action='store_true')
    args=parser.parse_args()
    if not args.allow_hard_off_zero_check: parser.error('Explicit one-shot calibration required')
    image(); OUTPUT.mkdir(parents=True,exist_ok=True)
    private=OUTPUT/'private'; private.mkdir(exist_ok=True)
    subprocess.run(['icacls',str(private),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F',
                    '*S-1-5-32-544:(OI)(CI)F'],check=True,capture_output=True)
    run=str(time.time_ns()); target=OUTPUT/f'zero-b-{run}.json'
    record=dict(pass_=False,capture_completed=False,image_sha256=SHA,resets=0,flash_writes=0,
                pwm_enabled=False,bridge_enabled=False,motion_commands=False,automatic_retry=False,steps=[])
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe only')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD failed; no reset/retry')
        return p.stdout+p.stderr
    def outputs():
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        return require_registers(cli(*tokens),'B')
    try:
        record['before_outputs']=outputs()
        backup=private/f'{run}-zero-identity.bin'; cli('-u','0x08000000','0x80000',backup)
        record['identity_backup']=str(backup)
        base=locked_baseline(backup.read_bytes(),known={'A':frozenset((OLD_A,)),'B':frozenset((SHA,))})
        if base['current']!='B' or base['generation']!=446: raise RuntimeError('Exact B446 required')
        record['baseline']=base
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=ZeroConsole(port)
        record['before_fw']=fw=require_confirmed(uart.query('FW STATUS'),'B')
        if fw.get('GEN')!='446': raise RuntimeError('UART/Flash identity mismatch')
        record['before_zero']=zero=require_service(uart.query('ZERO STATUS'))
        record['before_filter']=filtered=fields(uart.query('ZERO FILTER STATUS'))
        record['before_switch']=require_switch(uart.query('SWITCH STATUS'))
        if zero.get('STATE')!='0' or zero.get('N')!='0' or filtered.get('PAIRS')!='0':
            raise RuntimeError('Zero already attempted; no reset/repeat')
        record['analog_before']=analog=fields(uart.query('ANALOG VOLT'))
        if (analog.get('VALID')!='1' or not 10000<=int(analog.get('VBUS_EST_MV','0'))<=14000
            or not 3000<=int(analog.get('VDDA_BOOT_MV','0'))<=3600):
            raise RuntimeError('Sensing supply not ready; ZERO SAMPLE not sent')
        record['start']=uart.query('ZERO SAMPLE')
        time.sleep(5.3)  # Full firmware timeout, quiet UART/SWD throughout.
        record['zero_line']=uart.query('ZERO STATUS')
        record['filter_line']=uart.query('ZERO FILTER STATUS')
        record['zero']=zero=require_service(record['zero_line'])
        record['filter']=filtered=fields(record['filter_line'])
        record['final_outputs']=outputs()
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['final_switch']=require_switch(uart.query('SWITCH STATUS'))
        if record['final_fw'].get('GEN')!='446': raise RuntimeError('Unexpected generation change')
        record['capture_completed']=True
        record['qualification']=qualification(zero,filtered)
        record['pass_']=record['qualification']['both_zero_qualifiers_pass']
        print(record['zero_line'],flush=True); print(record['filter_line'],flush=True)
        print('B ZERO '+('QUALIFIED' if record['pass_'] else 'NOT FULLY QUALIFIED')+
              ': SD/PWM OFF; no motor/bridge command',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

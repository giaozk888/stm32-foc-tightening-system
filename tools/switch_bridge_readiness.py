"""Read-only bridge admission audit. Never starts PWM, bridge or motor."""
import json
import subprocess
import time
from current_observe_acceptance import image, SHA, ROOT
from firmware_transfer_iap import fields
from median_control_acceptance import Console
from zero_retest_deploy import CLI, SN, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers

OUTPUT=ROOT/'safety_backups/bridge-readiness-20261013'

class ReadConsole(Console):
    def command(self,*args,**kwargs): raise ValueError('Read-only audit')
    def query(self,text,timeout=2):
        if text not in ('FW STATUS','ANALOG SAFE STATUS','BENCH STATUS',
                        'BENCH ZERO','BENCH ZERO FILTER','FAULT SNAPSHOT','BENCH STACK'):
            raise ValueError('Read-only audit')
        return super().query(text,timeout)

def main():
    image()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    target=OUTPUT/f'audit-{time.time_ns()}.json'
    record=dict(read_only=True,expected_local_A_sha256=SHA,resets=0,flash_writes=0,
                capture_started=False,bridge_enabled=False,motion_commands=False)
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'
    try:
        port.open(); uart=ReadConsole(port)
        record['fw']=require_confirmed(uart.query('FW STATUS'),'A')
        if record['fw'].get('GEN')!='449': raise RuntimeError('Unexpected firmware state; no switching')
        record['uart']={q:uart.query(q) for q in ('ANALOG SAFE STATUS','BENCH STATUS',
                       'BENCH ZERO','BENCH ZERO FILTER','FAULT SNAPSHOT','BENCH STACK')}
        bench=fields(record['uart']['BENCH STATUS'])
        if any(bench.get(k)!=v for k,v in (('ACTIVE','0'),('LOCK','1'),('SD','0'),
                                         ('MOE','0'),('CCER','0'),('CEN','0'))):
            raise RuntimeError('Stopped hard-off proof missing; no operation')
        tokens=[token for address in ADDRESSES for token in ('-r32',hex(address),'4')]
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*tokens],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['swd']=dict(code=p.returncode,output=p.stdout+p.stderr)
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('Read-only SWD failed')
        record['outputs']=require_registers(p.stdout+p.stderr,'A')
        filtered=fields(record['uart']['BENCH ZERO FILTER'])
        record['bridge_admitted']=False
        record['blockers']=['Active A is compute-only and has no bridge switching profile',
                            'Pinned B bridge profile requires its own fresh guard/PWM/zero state',
                            'No current all-six physical waveform evidence']
        if filtered.get('RAW_STATE')!='3':
            record['blockers'].append('Current raw zero qualifier is not READY; not overridden')
        record['audit_completed']=True
        print('READ-ONLY AUDIT: outputs OFF; bridge NOT started',flush=True)
        print(json.dumps(record,ensure_ascii=False,indent=2),flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

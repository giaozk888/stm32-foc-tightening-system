"""Read-only readiness inspection; no capture, reset, Flash or motion commands."""
import json
import subprocess
import time
from switch_trend_off_capture import Console
from switch_trend_compare_deploy import OUTPUT, image
from zero_retest_deploy import CLI, SN
from zero_span100_acceptance import ADDRESSES, require_registers

def main():
    image()  # Expected local artifact only, not a claim of current Flash identity.
    record=dict(read_only=True,resets=0,flash_writes=0,motion_commands=False)
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'
    try:
        port.open(); uart=Console(port)
        record['uart']={q:uart.query(q) for q in
                        ('FW STATUS','ZERO STATUS','SWITCH STATUS','ANALOG VOLT')}
        tokens=[]
        for address in ADDRESSES: tokens.extend(('-r32',hex(address),'4'))
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*tokens],
                         capture_output=True,text=True,errors='replace',timeout=30)
        record['swd']=dict(code=p.returncode,output=p.stdout+p.stderr)
        if p.returncode or 'Error:' in p.stdout+p.stderr:
            raise RuntimeError('Read-only SWD failed; no reset/retry')
        record['outputs']=require_registers(p.stdout+p.stderr,'B')
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        port.close()
        OUTPUT.mkdir(parents=True,exist_ok=True)
        path=OUTPUT/f'inspect-{time.time_ns()}.json'
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False,indent=2),flush=True)
        print('Evidence: '+str(path),flush=True)

if __name__=='__main__': main()

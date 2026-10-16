"""Read-only fresh confirmation and 3 seconds of output-locked selftest status.
No Flash write, reset, sampling, threshold change or motor command.
"""
import json
import subprocess
import time
import overcurrent_layers_selftest_acceptance as acceptance

def main():
    import serial
    record=dict(read_only=True,reset=False,motion=False,current_sampling=False,pass_=False)
    target=acceptance.OUTPUT/f'inspect-{time.time_ns()}.json'
    port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'
    uart=acceptance.Console(port)
    try:
        port.open()
        start=time.monotonic(); samples=0
        while time.monotonic()-start<3:
            record['zero']=acceptance.require_new_service(uart.query('ZERO STATUS'))
            record['fw']=acceptance.require_confirmed(uart.query('FW STATUS'),'B')
            if record['fw']['GEN']!='436': raise RuntimeError('Unexpected confirmed generation')
            record['selftest']=acceptance.require_selftest(uart.query('OC LAYERS SELFTEST'))
            samples+=1
            until=time.monotonic()+.3
            while time.monotonic()<until: uart.poll(min(.05,until-time.monotonic()))
        record['duration_seconds']=time.monotonic()-start
        record['status_checks']=samples
        p=subprocess.run([acceptance.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000',
            'sn='+acceptance.SN,*(x for a in acceptance.ADDRESSES for x in ('-r32',hex(a),'4'))],
            capture_output=True,text=True,errors='replace',timeout=30)
        out=p.stdout+p.stderr
        if p.returncode or 'Error:' in out: raise RuntimeError('Read-only SWD failed')
        record['outputs']=acceptance.require_registers(out,'B')
        record['pass_']=True
        print(f"READ-ONLY PASS: {samples} checks over {record['duration_seconds']:.3f}s; B436, 36/36, outputs locked.")
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        port.close(); record['uart']=uart.lines
        target.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target))

if __name__=='__main__': main()

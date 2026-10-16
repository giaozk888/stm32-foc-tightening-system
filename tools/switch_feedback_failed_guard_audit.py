"""Read-only closeout after the failed power-OFF TIM7 test. No reset or start."""
import json
import subprocess
import time
from switch_feedback_acceptance import OUTPUT, IMAGE, SHA, image, baseline, Console
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers

def main():
    prior=OUTPUT/'deploy-1791797136121918300.json'
    old=json.loads(prior.read_text(encoding='utf-8'))
    if old.get('pass_') or old.get('failure')!='Independent TIM7 cutoff failed; no bridge admitted':
        raise RuntimeError('Only the pinned failed guard deployment may be audited')
    private=(OUTPUT/'private').resolve()
    before_path=__import__('pathlib').Path(old['before_backup']).resolve()
    if before_path.parent!=private: raise RuntimeError('Invalid private baseline')
    before=before_path.read_bytes(); baseline(before); data=image()
    run=str(time.time_ns()); record={'read_only':True,'resets':0,'bridge_enabled':False,'pass_':False}
    def cli(*args):
        if args[0] not in ('-u','-r32'): raise ValueError('Read-only operations only')
        p=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,args)],
                         capture_output=True,text=True,errors='replace',timeout=30)
        if p.returncode or 'Error:' in p.stdout+p.stderr: raise RuntimeError('SWD read failed')
        return p.stdout+p.stderr
    tokens=[]
    for addr in ADDRESSES: tokens.extend(('-r32',hex(addr),'4'))
    record['outputs']=require_registers(cli(*tokens),'B')
    final=private/f'{run}-failed-guard-final.bin'
    cli('-u','0x08000000','0x80000',final)
    record['protected_flash']=compare_flash(before,final.read_bytes(),data,'B')
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'; port.open()
    try:
        uart=Console(port)
        record['fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['status']=uart.query('SWITCH STATUS')
        record['uart']=uart.lines
    finally: port.close()
    record['pass_']=True
    target=OUTPUT/f'failed-guard-audit-{run}.json'
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('READ-ONLY CLOSEOUT PASS: confirmed B, all outputs OFF; A/bootloader/KVS/parameters unchanged')
    print('Evidence: '+str(target))

if __name__=='__main__': main()

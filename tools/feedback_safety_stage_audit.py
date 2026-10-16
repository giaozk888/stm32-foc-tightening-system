"""Read-only closeout of the exact staged B after BENCH was transaction-gated.
Never transfer, reset, clear, abort or commit. Preserve original failed record.
"""
import json
from pathlib import Path
import subprocess
import time
import feedback_safety_stage as staging
from zero_retest_deploy import CLI,SN,compare_flash
from zero_span100_acceptance import ADDRESSES,require_registers
from tighten_synthetic_acceptance import locked
from firmware_transfer_iap import fields

PRIOR=staging.OUTPUT/'stage-1791887444841198200.json'

def prior_evidence(row):
    if (row.get('pass_') is not False or row.get('failure')!='95253 ERR 101 FW_UPDATE_ACTIVE' or
            row.get('image_sha256')!=staging.SHA or row.get('fw_end') is not False or
            row.get('resets')!=0 or row.get('activation') is not False or
            row.get('all_bytes_outside_b_unchanged') is not True or
            not row.get('protected_flash',{}).get('all_protected_regions_unchanged')):
        raise RuntimeError('Only the preserved post-readback BENCH gate failure admitted')
    return row

def main():
    old=prior_evidence(json.loads(PRIOR.read_text('utf-8')))
    private=(staging.OUTPUT/'private').resolve()
    p=Path(old['before_backup']).resolve()
    if p.parent!=private: raise RuntimeError('Private original path mismatch')
    original=p.read_bytes(); staging.baseline(original); data=staging.image()
    run=str(time.time_ns()); target=staging.OUTPUT/f'stage-audit-{run}.json'
    record=dict(pass_=False,stage_only=True,read_only_closeout=True,image_sha256=staging.SHA,
                prior_evidence=str(PRIOR),before_backup=str(p),fw_end=False,resets=0,
                activation=False,motion_commands=False,sampling_commands=False,
                motor_qualified=False,steps=[])
    port=uart=None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                              capture_output=True,text=True,errors='replace',timeout=30)
        out=result.stdout+result.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('Read failed; no reset/retry')
        return out
    try:
        dest=private/f'{run}-audit-staged.bin'; cli('-u','0x08000000','0x80000',dest)
        record['staged_backup']=str(dest); actual=dest.read_bytes()
        record['protected_flash']=compare_flash(original,actual,data,'B',staged=True)
        if original[:0x40000]!=actual[:0x40000] or original[0x78000:]!=actual[0x78000:]:
            raise RuntimeError('Bytes outside B changed')
        record['all_bytes_outside_b_unchanged']=True
        record['after_outputs']=require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),'A')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=staging.Console(port)
        record['staged_fw']=staging.require_staged(uart.query('FW STATUS'),staging.GEN,data)
        record['post_stage_console_diagnostics_gated']=True
        record['pass_']=True
        print('READ-ONLY STAGE CLOSEOUT PASS: exact inactive B; all non-B bytes unchanged; A449 locked; NO RESET.',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

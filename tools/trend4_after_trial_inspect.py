"""Read-only post-rollback protection proof; never reset or sample."""
import argparse
import hashlib
import json
import subprocess
import time
import zlib
from pathlib import Path
import trend4_control_acceptance as pinned
from trend4_control_commit import evidence
from zero_retest_deploy import CLI,SN,require_confirmed,require_service,latest_meta
from zero_span100_acceptance import ADDRESSES,require_registers

def validate_rollback(original, actual, image):
    """Check this exact failed B trial without admitting arbitrary invalid APPs.

    Boot_CommitRollbackV3 clears the failed pending image's size/CRC when
    attempts are exhausted, but leaves physical APP bytes intact.
    """
    pinned.baseline(original)
    if len(actual)!=0x80000: raise RuntimeError('Complete rollback capture required')
    meta=latest_meta(actual); before=latest_meta(original)
    if meta[2:6]!=(1,0,0,433): raise RuntimeError('Expected exact confirmed A433 rollback')
    if meta[8:10]!=(0,0): raise RuntimeError('Failed B metadata must be invalidated')
    if meta[6:8]!=before[6:8]: raise RuntimeError('A metadata changed')
    a=actual[0x8000:0x8000+meta[6]]
    if hashlib.sha256(a).hexdigest()!=pinned.OLD_A or zlib.crc32(a)!=meta[7]:
        raise RuntimeError('Confirmed A image invalid')
    if hashlib.sha256(image).hexdigest()!=pinned.SHA:
        raise RuntimeError('Unpinned B artifact')
    if actual[0x40000:0x40000+len(image)]!=image:
        raise RuntimeError('Pinned B changed')
    regions=(('bootloader',0,0x8000),('fallback_A',0x8000,0x40000),
             ('KVS_reserved',0x78000,0x7e800),('parameters',0x7f800,0x80000))
    for name,start,end in regions:
        if actual[start:end]!=original[start:end]:
            raise RuntimeError('Protected bytes changed: '+name)
    return dict(current='A',generation=meta[5],failed_B_metadata_invalidated=True,
                all_protected_regions_unchanged=True,active_sha256=pinned.OLD_A,
                physical_B_sha256=pinned.SHA,physical_B_bytes=len(image))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-evidence',type=Path,required=True)
    parser.add_argument('--saved-capture',type=Path,
                        help='Audit an existing private capture offline; no hardware access')
    args=parser.parse_args()
    original=evidence(args.stage_evidence); image=pinned.image()
    run=str(time.time_ns()); target=pinned.OUTPUT/f'after-trial-{run}.json'
    record=dict(pass_=False,read_only=True,reset=False,sampling=False,motion=False,steps=[])
    if args.saved_capture:
        path=args.saved_capture.resolve()
        if path.parent!=(pinned.OUTPUT/'private').resolve():
            raise RuntimeError('Capture outside restricted private directory')
        record.update(offline=True,private_backup=str(path),
                      flash=validate_rollback(original,path.read_bytes(),image),pass_=True)
        target=pinned.OUTPUT/f'rollback-offline-{run}.json'
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('OFFLINE FLASH PASS: A433 intact; B bytes exact, failed B metadata invalidated; protected regions unchanged.')
        print('Evidence: '+str(target))
        return
    port=uart=None
    def cli(*tokens):
        if tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD only')
        result=subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,
                               *map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out=result.stdout+result.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=result.returncode,output=out))
        if result.returncode or 'Error:' in out: raise RuntimeError('Read failed; no retry')
        return out
    try:
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=pinned.StageConsole(port)
        record['fw']=fw=require_confirmed(uart.query('FW STATUS'),'A')
        if int(fw['GEN'])<433: raise RuntimeError('Expected completed rollback')
        record['zero']=require_service(uart.query('ZERO STATUS'))
        record['outputs']=require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),'A')
        path=pinned.OUTPUT/'private'/f'{run}-after-trial.bin'
        cli('-u','0x08000000','0x80000',path); actual=path.read_bytes()
        record['private_backup']=str(path)
        record['flash']=validate_rollback(original,actual,image)
        record['pass_']=True
        print('READ-ONLY PASS: A confirmed, outputs locked; bootloader/A/KVS/parameters unchanged; B exact.',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

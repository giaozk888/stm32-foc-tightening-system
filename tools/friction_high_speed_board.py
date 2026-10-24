"""Pinned 200/240/260/280rpm signed A grid, stable B untouched. Files default.

Reuse the verified per-point runner and its strict electrical/timing stop
policy. Only isolated NO_ROTATION/measurement failures permit the next boot.
"""
import json
from pathlib import Path
import zlib
import friction_calibration_board as cal

base=cal.base;TMP=cal.TMP
RESTORE=TMP/'friction-cal-restore-1792492251662379600.json'
BASE_SHA='d311b5287ffd6398a2a85a312f33a4fa9b3d52877cc4e5bdadb9e556fae06823'
OLD_CAL_SHA='a23a7c8760e92cd498d3753065aad12a220ce66514aeac245421869a24a117f0'
IMAGE=base.old.ROOT/'foc2_app_a/build/FrictionCalibrationHighSpeedDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='f4231c660daab2cbc3dc955bee7057416c3e0b041da6d74471e0959159ab73d6'
ELF_SHA='7f0f33ca6223d6d5e004c09bbde8f2fc639716eaea3792c621d9d83b8eed0c7c'
SIZE=212964
POINTS=(200,240,260,280,-200,-240,-260,-280)


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(data)!=SIZE or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        base.symbols(ELF).get('friction_calibration',(0,0))[1]!=84 or
        any(flag not in cmd for flag in ('-DFOC_FRICTION_HIGH_SPEED_GRID=1',
            '-DFOC_FRICTION_CALIBRATION_DIAG=1','-DFOC_FRICTION_ENABLED_DEFAULT=0',
            '-DFOC_SPEED_FRICTION_CANDIDATE=1')) or
        b'FCAL_DIAGNOSTIC: manual single point; FRIC OFF; no START' not in data or
        b'TRIP_MA=4000' not in data):
        raise ValueError('Exact offline-tested high-speed A BIN/ELF required')
    return data


def configure(path=RESTORE):
    path=path.resolve()
    if path!=RESTORE.resolve():raise ValueError('Exact preserved B792 baseline receipt required')
    base.configure_baseline(cal.ROOT_RESTORE)
    root=base.baseline();r=json.loads(path.read_text('utf-8'))
    capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('image_sha256')!=OLD_CAL_SHA or
        r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
          ('pass_','all_app_private_unchanged','b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Preserved halted B792 restoration required')
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or r.get('final_sha256')!=BASE_SHA or
        meta[2:10]!=(2,0,0,792,212836,4012794631,227964,627317606) or list(meta)!=r.get('metadata') or
        base.old.zero.digest(raw[0x8000:0x8000+212836])!=OLD_CAL_SHA or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or off.get('VTOR')!=0x08040000 or
        not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
        raise ValueError('B792 baseline identity/preservation/output mismatch')
    data=image()
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=path
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;base.image=image
    cal.SELECTED_RESTORE=path
    return data


def main():
    cal.IMAGE,cal.ELF,cal.SHA,cal.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    cal.RESTORE=RESTORE;cal.SELECTED_RESTORE=RESTORE;cal.REQUIRED_API_RPM=280
    cal.analysis.POINTS=POINTS
    cal.image=image;cal.configure=configure
    return cal.main()


if __name__=='__main__':raise SystemExit(main())

"""Restore original B after interrupted SB1 acquisition; drive OFF only.

Existing bootloader mailbox, no Flash programming or motion; stop before B
application instructions. Exact saved Flash and application identities required.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import sb1_speed_acceptance as candidate
from latest_original_fsm_stage import full_compare_commands,off_commands,write_mailbox
from original_closed_loop_updated_stage import debug,off_report,check_off
from original_closed_loop_trial import emergency_off


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--restore-b-drive-off',action='store_true')
    p.add_argument('--from-speed-receipt',type=Path)
    a=p.parse_args()
    if not a.restore_b_drive_off:
        print('OFFLINE ONLY: no hardware operation'); return 0
    image,baseline=candidate.baseline()
    expected=candidate.TMP/'sb1-speed-interrupted-final-flash.bin'
    expected_meta=(1,0,0,644)
    source=None
    if a.from_speed_receipt:
        source=json.loads(a.from_speed_receipt.read_text('utf-8'))
        expected=Path(source.get('final_capture','')).resolve()
        if (a.from_speed_receipt.resolve().parent!=candidate.TMP.resolve() or
                expected.parent!=candidate.TMP.resolve() or source.get('image_sha256')!=candidate.zero.SHA or
                source.get('start_attempts')!=1 or source.get('pass_') is not False or
                source.get('failure')!='Last 0.5s not within provisional 20 +/-5rpm band' or
                any(source.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged')) or
                source.get('snapshot',{}).get('first_fault',{}).get('valid')!=0):
            raise ValueError('Exact stopped speed-tracking failure receipt required')
        expected_meta=(1,0,0,648)
    before=expected.read_bytes(); meta=candidate.zero.latest_meta(before)
    if source and candidate.zero.digest(before)!=source.get('final_sha256'):
        raise ValueError('Stopped speed capture changed')
    if (len(before)!=0x80000 or meta[2:6]!=expected_meta or
            before[:0x7e800]!=baseline[:0x7e800] or
            before[0x7f800:]!=baseline[0x7f800:] or
            before[0x8000:0x8000+len(image)]!=image or
            meta[6:10]!=candidate.zero.latest_meta(baseline)[6:10]):
        raise ValueError('Exact stopped A644/preserved B image required')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]:
        raise ValueError('B reset entry outside preserved image')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    name='sb1-speed-interrupted-restore-'+str(time.time_ns())
    final=candidate.TMP/(name+'-flash.bin')
    row=dict(pass_=False,steps=[],drive_12v_off=True,motor_start_commands=0,
        flash_programming=False,force_confirmation=False,direct_metadata_write=False)
    try:
        output=debug(row,[*candidate.zero.off_gate(),
            *full_compare_commands(candidate.TMP/(name+'-before.bin'),expected),
            'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),
            'reset run','wait_halt 25000',f'rbp {entry:#x}',
            f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped at B entry"}}',
            *off_commands(),*off_report(),
            f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
        raw=final.read_bytes(); current=candidate.zero.latest_meta(raw)
        if (len(raw)!=0x80000 or raw[:0x7e800]!=before[:0x7e800] or
                raw[0x7f800:]!=before[0x7f800:] or current[2:5]!=(2,0,0) or
                current[5]<=meta[5] or current[6:10]!=meta[6:10]):
            raise RuntimeError('B selection or application/private preservation failed')
        row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
            final_metadata=list(current),final_capture=str(final),
            final_sha256=candidate.zero.digest(raw),all_app_private_unchanged=True,
            final_cpu_halted=True,final_outputs_off=True,b_application_not_run=True)
    except Exception as error:
        row['failure']=str(error)
        try: emergency_off(row,candidate.TMP/(name+'-failed.bin'))
        except Exception as cleanup: row['cleanup_error']=str(cleanup)
    receipt=candidate.TMP/(name+'.json')
    receipt.write_text(json.dumps(row,indent=2)+'\n',encoding='utf-8')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(receipt))
    if row.get('failure'): print(row['failure'])
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())

"""Pinned SB1 inactive-A stage or power-off-output startup test; no START.

The physical drive stays OFF during staging and ON only after the user says
so for --trial-powered. Neither mode sends motor motion commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import zlib

from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from pipeline_closed_loop_trial import Console
from health_confirmation_wait import wait_health_confirmation
from tighten_synthetic_swd_recovery import latest_meta

ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'tmp'
IMAGE=ROOT/'foc2_app_a/build/SpeedStartupBrakeTrial/foc2.bin'
BASE=TMP/'loaded-fsm-motion-1792300223073650000-flash.bin'
SHA='98a90620404a9daa1210f7f8e61aa9cbda6b8d612b8a884cc6d83a950e25f50f'
BASE_SHA='99c3145804882b1cca9bd6aebcc1a861acbb530f8b0651946899829181ec7830'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image():
    data=IMAGE.read_bytes()
    if len(data)!=229316 or digest(data)!=SHA or image_info(data)[0]!='A':
        raise ValueError('Exact offline-tested SB1 A image required')
    for marker in (b'SPEED_CTRL=SB1',b'RPM=20 LEASE_US=12000000',
                   b'METHOD=TWO_SAMPLE',b'FILTER=NONE OC=RAW_CONFIRM_4'):
        if marker not in data:
            raise ValueError('Candidate/protection marker absent')
    return data


def stage(row,name,data):
    baseline=BASE.read_bytes()
    if (len(baseline)!=0x80000 or digest(baseline)!=BASE_SHA
            or latest_meta(baseline)[2:6]!=(2,0,0,634)):
        raise ValueError('Exact confirmed B634 with no pending trial required')
    before=TMP/(name+'-before.bin')
    after=TMP/(name+'-staged.bin')
    row['hardware_attempted']=True
    debug(row,['init','halt',
        'if {[mrw 0xE000ED08] != 0x08040000} {error wrong_current_slot}',
        *off_commands(),*full_compare_commands(before,BASE),'shutdown'])
    row['programming_attempted']=True
    debug(row,['init','halt',
        *full_compare_commands(TMP/(name+'-recheck.bin'),before),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{after.as_posix()}}} 0x08000000 0x80000','shutdown'])
    captured=after.read_bytes()
    end=(0x8000+len(data)+0x7ff)&~0x7ff
    if (len(captured)!=0x80000 or captured[:0x8000]!=baseline[:0x8000]
            or captured[end:]!=baseline[end:]
            or captured[0x8000:0x8000+len(data)]!=data
            or captured[0x8000+len(data):end]!=b'\xff'*(end-0x8000-len(data))):
        raise RuntimeError('Inactive-A full Flash verification failed')
    row.update(staged_capture=str(after),staged_sha256=digest(captured),
               metadata=list(latest_meta(captured)),b_and_private_unchanged=True,
               activation=False,pass_=True)


def trial(row,name,receipt,data):
    r=json.loads(receipt.read_text('utf-8'))
    staged=Path(r['staged_capture'])
    if (staged.resolve().parent!=TMP.resolve() or r.get('pass_') is not True
            or r.get('image_sha256')!=SHA
            or digest(staged.read_bytes())!=r['staged_sha256']):
        raise ValueError('Exact SB1 stage receipt required')
    port=open_port()
    uart=Console(port)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        words=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True
        debug(row,['init','halt',
            *full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(words),'reset run','shutdown'])
        row['trial_submitted']=True
        wait_health_confirmation(uart,row,fields)
        commands=('FW STATUS','MOTOR TEST PROFILE','MOTOR TEST STATUS','MOTOR TEST ZERO',
                  'SELFTEST STATUS','MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS','ANALOG SAFE STATUS')
        row['preflight']={command:uart.query(command) for command in commands}
        expected={
            'MOTOR TEST PROFILE':dict(SPEED_CTRL='SB1',RPM='20',LEASE_US='12000000'),
            'MOTOR TEST STATUS':dict(STATE='1',USED='0',ZERO='3',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0'),
            'SELFTEST STATUS':dict(READY='1',MASK='0x000'),
            'MOTOR TEST FAULT':dict(VALID='0'),
            'STATUS':dict(BUSY='0',MODE='IDLE',FLT='0'),
            'ANALOG SAFE STATUS':dict(LATCHED='0',SD='0',MOE='0')}
        for command,wanted in expected.items():
            actual=fields(row['preflight'][command])
            if any(actual.get(k)!=v for k,v in wanted.items()):
                raise RuntimeError('Candidate startup preflight failed: '+command)
        end=time.monotonic()+12
        while time.monotonic()<end:
            uart.poll(.05)
        last=fields(uart.query('MOTOR TEST STATUS'))
        if any(last.get(k)!=v for k,v in expected['MOTOR TEST STATUS'].items()):
            raise RuntimeError('Candidate lost READY or output-off state')
        text='\n'.join(uart.lines)
        row['timing']={}
        for key in ('wall_max_us','deadline_miss','actual_late_commit_count','actual_margin_min_us'):
            values=re.findall(r'\b'+key+r'=([+-]?[0-9.]+)',text)
            if not values:
                raise RuntimeError('No real timing value: '+key)
            row['timing'][key]=float(values[-1])
        t=row['timing']
        if (t['wall_max_us']>=50 or t['deadline_miss'] or t['actual_late_commit_count']
                or t['actual_margin_min_us']<=1):
            raise RuntimeError('Candidate timing preflight failed')
        row['pass_']=True
    finally:
        row['uart']=uart.lines
        port.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--trial-powered',type=Path)
    args=parser.parse_args()
    data=image()
    if not(args.stage_off or args.trial_powered):
        print('OFFLINE SB1 image identity PASS; no device operation')
        return 0
    name='speed-startup-brake-'+('stage-' if args.stage_off else 'trial-')+str(time.time_ns())
    row=dict(pass_=False,image_sha256=SHA,steps=[],host_start_commands=0,
             automatic_retry=False,direct_metadata_write=False)
    try:
        if args.stage_off:
            stage(row,name,data)
        else:
            trial(row,name,args.trial_powered,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted'):
            try:
                emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup:
                row['cleanup_error']=str(cleanup)
    path=TMP/(name+'.json')
    path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(('PASS' if row['pass_'] else 'FAIL')+': '+str(path),flush=True)
    if row.get('failure'):
        print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':
    raise SystemExit(main())

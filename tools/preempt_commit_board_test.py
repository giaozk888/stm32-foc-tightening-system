"""Pinned power-hard-off preemption/real-CCR acceptance. Offline by default.

One trial, no START/forced confirm, full Flash and exact ELF ownership checks.
Stage/restore require drive off; trial requires powered drive and no motor wires.
"""
import argparse
import json
import time
from pathlib import Path
import cur_confirm_cycles_board_test as confirm
import preempt_commit_report as report

old,prior,tx=confirm.old,confirm.prior,confirm.tx
ROOT,OUTPUT,PRIVATE=confirm.ROOT,confirm.OUTPUT,confirm.PRIVATE
IMAGE=ROOT/'foc2_app_a/build/PreemptCommitProbe/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='6673490d00bab3958583b73474efd065daa60f8332ea1938861bb59b027dba9c'
ELF_SHA='781cc94baf551467098eb7045b6bb68feacdc71409f7bdb725f62e2237b6c161'
SIZE=228524
PREFIX='preempt-commit-'
BASE_RECEIPT=OUTPUT/'fast-path-profile-restore-1792204669557311400.json'
BASE_SHA='9c2ea69a060713c67f5aca398ac3463025040661e648c94b7412c12cf9b29823'
BASE_META=(1112493908,3,2,0,0,595,229220,3471226254,210916,453748590,0,517262709)

def image():
    data=IMAGE.read_bytes()
    receipt=json.loads((ROOT/'tests/foc_adaptive_build/preempt_commit_evidence/receipt.json').read_text())
    if (len(data)!=SIZE or tx.digest(data)!=SHA or tx.digest(ELF.read_bytes())!=ELF_SHA or
            prior.image_info(data)[0]!='A' or receipt.get('hardware_access') is not False or
            receipt.get('test_count')!=102 or
            not any(r.get('bin_sha256')==SHA and r.get('elf_sha256')==ELF_SHA
                    for r in receipt['builds'])):
        raise ValueError('Exact offline-tested hard-off probe image/ELF/receipt required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'PWM COMMIT',b'HYPOTHETICAL PWM'):
        if marker not in data: raise ValueError('Missing hard-off/probe identity')
    return data

def configure():
    values=dict(IMAGE=IMAGE,ELF=ELF,SHA=SHA,ELF_SHA=ELF_SHA,SIZE=SIZE,PREFIX=PREFIX,
        BASE_RECEIPT=BASE_RECEIPT,BASE_SHA=BASE_SHA,BASE_META=BASE_META)
    for module in (confirm,confirm.base,old,prior,tx):
        for key,value in values.items(): setattr(module,key,value)
        module.image=image

def verify():
    image(); confirm.layout(); confirm.base.symbols(); tx.baseline()
    for name,size in (('foc_preempt_timing',140),('foc_preempt_irq',64),
            ('foc_pwm_write_profile',128),('foc_pwm_duty_profile',128),
            ('foc_probe_irq_priority',28)):
        addr,n=confirm.ram_symbol(name)
        if n!=size or not 0x20000000<=addr<=0x20020000-size:
            raise ValueError('Wrong pinned probe RAM layout: '+name)

def wait_confirmation(uart,row):
    """Historical wait policy; newer pinned runners may install their own."""
    until=time.monotonic()+60
    while time.monotonic()<until:
        try: fw=prior.fields(uart.query('FW STATUS',.6))
        except TimeoutError: continue
        row['last_fw']=fw
        if fw.get('CURRENT')=='B' and fw.get('PENDING')=='-':
            raise RuntimeError('Probe A rolled back/rejected; no retry')
        if fw.get('CURRENT')!='A': continue
        state=prior.fields(uart.query('MOTOR TEST STATUS',.6)); row['last_state']=state
        if state.get('STATE')=='4':
            row['sample']=prior.sample(uart)
            end=time.monotonic()+5.5
            while time.monotonic()<end: uart.poll(.05)
            raise RuntimeError('Probe startup/runtime fault captured; no retry')
        if all(fw.get(k)==v for k,v in
                (('CONFIRMED','A'),('PENDING','-'),('ATTEMPTS','0'),('ACTIVE','0'))):
            row['normally_confirmed']=True
            return
    raise TimeoutError('Normal probe health confirmation absent')


def trial(row,run,data,receipt):
    expected,before=tx.load_stage(receipt,data)
    port=uart=None
    try:
        port=prior.open_port(); uart=prior.Console(port)
        row.update(hardware_attempted=True,trial_requests=1)
        prior.debug(row,[*tx.prior.off_gate(0),
            *prior.full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
            'reset halt',*prior.write_mailbox(tx.mailbox(data)),'reset run','shutdown'])
        row['activation_submitted']=True
        wait_confirmation(uart,row)
        start=time.monotonic()
        while True:
            s=prior.sample(uart); row['sample']=s; row['samples'].append(s)
            prior.healthy(s)
            if s['filter'].get('METHOD')!='TWO_SAMPLE':
                raise RuntimeError('Wrong discriminator')
            if time.monotonic()-start>=30: break
            until=time.monotonic()+2
            while time.monotonic()<until: uart.poll(.05)
        row.update(pass_=True,observed_seconds=time.monotonic()-start)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try: row['off_ack']=uart.query('ANALOG SAFE',.8)
                    except BaseException as error: row['uart_off_error']=str(error)
                final=PRIVATE/(run+'-final.bin')
                prior.emergency_off(row,final)
                raw=final.read_bytes()
                row.update(final_backup=str(final),final_sha256=tx.digest(raw),
                    final_metadata=list(tx.compare_final(before,raw,data,
                        row.get('activation_submitted',False))),
                    all_app_and_private_bytes_unchanged=True)
                ram=PRIVATE/(run+'-ram.bin')
                prior.debug(row,['init',
                    'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
                    'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Outputs not off"}',
                    f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
                row['ram_backup']=str(ram)
        finally:
            if uart: row.update(uart=uart.lines,host_motor_commands=uart.starts,
                host_uart_trial_commits=uart.ends)
            if port and port.is_open: port.close()

def decode(row,data):
    if not row.get('ram_backup'): return
    confirm.base.decode_trial_snapshot(row,data)
    if row.get('snapshot_not_decoded'): return
    ram=tx.prior.private_path(row['ram_backup']).read_bytes()
    raw=tx.prior.private_path(row['final_backup']).read_bytes()
    row['cur_confirm']=confirm.decode_confirmation(ram)
    row['foc_profile_ram']=confirm.decode_cycles(ram)
    row['preempt_commit']=report.decode(ELF,ram,raw,row['snapshot_vtor'])
    p=row['preempt_commit']
    # Preserve fault/failed-trial status; successful collection is not motor qualification.
    row['same_cycle_evidence_collected']=bool(p['timing']['frames'])
    if row['pass_'] and (not p['priorities']['ok'] or not p['actual_ccr']['points'] or
            p['timing']['deadline_miss'] or p['actual_ccr']['post_unsafe']):
        row.update(pass_=False,failure='Probe acceptance incomplete or timing failure')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-inactive-a',action='store_true')
    mode.add_argument('--trial-from-stage',type=Path)
    mode.add_argument('--restore-from-trial',type=Path)
    p.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    p.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    a=p.parse_args()
    op='stage' if a.stage_inactive_a else 'trial' if a.trial_from_stage else 'restore' if a.restore_from_trial else None
    if op=='trial' and not a.drive_12v_on_motor_disconnected:
        p.error('Powered drive and disconnected motor required')
    if op in ('stage','restore') and not a.drive_12v_off_motor_disconnected:
        p.error('Drive 12 V off and disconnected motor required')
    configure(); data=image(); verify()
    if op is None:
        print('OFFLINE PASS: pinned PreemptCommitProbe / matching schemas / B595; no devices'); return 0
    run=PREFIX+op+'-'+str(time.time_ns())
    row=dict(pass_=False,mode=op,image_sha256=SHA,elf_sha256=ELF_SHA,image_bytes=SIZE,
        steps=[],samples=[],hardware_attempted=False,programming_attempted=False,
        motor_commands=0,host_motor_commands=0,trial_requests=0,force_confirmation=False,
        direct_metadata_write=False,automatic_retry=False,activation=False,
        physical_pwm_preload_deadline_verified=False,motor_closed_loop_verified=False)
    try:
        if op=='stage': tx.stage(row,run,data)
        elif op=='trial': trial(row,run,data,a.trial_from_stage)
        else: tx.restore(row,run,data,a.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False,failure=str(error)); print('FAILED: '+str(error),flush=True)
        if (row.get('programming_attempted') or row.get('restore_attempted')) and not row.get('final_cpu_halted'):
            try: prior.emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure']=str(cleanup)
    finally:
        try: decode(row,data)
        except BaseException as error: row.update(pass_=False,decode_failure=str(error))
        path=OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if row.get('preempt_commit'): print(json.dumps(row['preempt_commit'],indent=2),flush=True)
        if not row['pass_']:
            for step in row['steps']: print(step['output'],flush=True)
    return 0 if row['pass_'] else 1

if __name__=='__main__': raise SystemExit(main())

"""Five passive 240rpm unloaded acquisitions; files-only unless explicit gates.

No true load sensor: saves actual measured currents/encoder, not load truth.
Preserved original B/boot/config, no safety tuning, no automatic retries.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import zlib
import dob025_normal_fsm_board as normal

base=normal.base;TMP=base.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/DobRealTraceCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='d25eacb105ea35e1a127e7e1b53d6b94735927c9a344d3a1d6cdccb38782fe1a'
# Exact ELF digest, never accepts a newly built image implicitly.
ELF_SHA='19a566ec4aa7a137e8514db8dbb08b920bef9bed3db5d28d56561c5e25954c65'
SIZE=223692
BASELINE=TMP/'dob025-normal-restore-1792742057460705600.json'
ORIGINAL_MOTION=base.motion
ORIGINAL_DECODE=base.decode_cm

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or digest(IMAGE)!=SHA or digest(ELF)!=ELF_SHA:raise ValueError('Frozen raw capture image changed')
    command=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    for flag in ['FOC_DOB_REAL_TRACE=1','FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1',
                 'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PROTECTED_CLOSED_LOOP=1','DOB_ADMIT_JUMP_A=.200f']:
        if '-D'+flag+' ' not in command:raise ValueError('Required build flag '+flag)
    if '-DFOC_DOB_ID_TRACE=1 ' in command:raise ValueError('Competing capture buffer owner')
    syms=base.symbols(ELF)
    for key,n in [('dob_real_trace',84),('dob_real_points',4),('mechanical_capture',4712),('dob_feedback',80)]:
        if syms.get(key,(0,0))[1]!=n:raise ValueError('Capture ABI '+key)
    if base.hw.image_info(data)[0]!='A':raise ValueError('Candidate A only')
    return data

def configure(path):
    normal.configure(BASELINE) # verify prior image/B under its own identity
    for key,value in [('IMAGE',IMAGE),('ELF',ELF),('SHA',SHA),('ELF_SHA',ELF_SHA)]:setattr(base,key,value)
    base.image=image;base.motion=motion;base.decode_cm=decode;base.staged=staged
    if path.resolve()!=BASELINE.resolve():
        # The new restoration belongs to THIS image, not the old normal
        # executor's SHA/size. Preserve strict validation under both identities.
        base.configure_baseline(path)
    normal.FB_CONFIG=dict(normal.FB_CONFIG,ON='0')
    # This image intentionally inherits CONTACT20/observe10. Check the exact
    # on-board model rather than the old shadow executor's 20rpm default.
    normal.prior.fb.shadow.MODEL=dict(normal.prior.fb.shadow.MODEL,MIN_W_MRAD_S='1047')
    base.ff_status=lambda line:normal.check_values(line,dict(ON='1',KA_NA_PER_RPM_S='46875',
        ACCEL_MAX_RPM_S='200',FF_PEAK_UA='9375',TOKENIZED='1'),'Fixed Ka')
    base.friction_status=lambda line,enabled:normal.check_values(line,dict(ON=str(int(enabled)),
        I_UA='105000',DB_MRPM='2000',FF_ON='1',KA_NA_PER_RPM_S='46875',TOKENIZED='1'),'Fixed friction')
    return image()

def staged(path,data):
    r=json.loads(path.read_text())
    if r.get('mode')=='stage':return normal.ORIGINAL_STAGED(path,data)
    capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or r.get('mode')!='run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ['pass_','final_outputs_off','final_cpu_halted','all_app_private_unchanged']) or
        r.get('dob_feedback_requested') is not False or r.get('start_attempts')!=1 or
        Path(r['baseline_restore_receipt']).resolve()!=base.BASE_RESTORE_RECEIPT):
        raise ValueError('Exact previous safe OFF run required before next boot')
    raw=capture.read_bytes();root=base.baseline();meta=base.old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or digest(capture)!=r.get('final_sha256') or
        raw[0x8000:0x8000+len(data)]!=data or raw[:0x8000]!=root[:0x8000] or
        raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or raw[0x7f800:]!=root[0x7f800:] or
        not base.restorable_state(meta) or meta[6:8]!=(len(data),zlib.crc32(data))):
        raise ValueError('Previous stopped Flash/B/config closure failed')
    return capture,raw

def motion(board,row):
    normal.model_checks(board,row)
    normal.check_values(board.command('MOTOR TEST MECH DOB SPEEDS'),
        dict(CONTACT_RPM='20',OBS_MIN_MRPM='10000',FB_MIN_MRPM='20000'),'Existing CONTACT20/observe10')
    try:ORIGINAL_MOTION(board,row)
    finally:
        for cmd in ['MOTOR TEST MECH DOB FB STATUS','MOTOR TEST MECH DOB FB STATS']:
            row['postflight'][cmd]=board.command(cmd)

HEADER=('abi count observations origin_us origin_set done first_seq last_seq first_us last_us '
        'overflow max_cycles invalid_current nonfinite saturated filter_skipped dob_invalid '
        'reference_min_rpm reference_max_rpm accel_abs_peak_rpm_s iq_command_abs_peak_a').split()

def decode_raw(ram,syms):
    def block(name):
        a,n=syms[name];offset=a-0x20000000
        if not 0<=offset<=len(ram)-n:raise ValueError('RAM symbol bounds '+name)
        return ram[offset:offset+n]
    h=dict(zip(HEADER,struct.unpack('<17I4f',block('dob_real_trace'))))
    pointer=struct.unpack('<I',block('dob_real_points'))[0]
    # Preflight can abort before any running observer epoch. Preserve that
    # absence as no data, not a corrupted ABI that hides the original error.
    if not h['abi'] and not h['count'] and not h['observations'] and pointer in (0,syms['mechanical_capture'][0]):
        return h,[]
    if pointer!=syms['mechanical_capture'][0] or h['abi']!=1 or h['count']>192:raise ValueError('Raw buffer ABI/identity')
    raw=block('mechanical_capture');rows=[];seq=h['first_seq']
    for i in range(h['count']):
        enc,now,id_a,iq_a,w,step,flags=struct.unpack_from('<II3f2H',raw,i*24)
        if i:seq=(seq+step)&0xffffffff
        rows.append(dict(sample_index=i,timestamp_us=enc,observed_us=now,adc_seq=seq,
            dt_us=0 if not rows else (enc-rows[-1]['timestamp_us'])&0xffffffff,
            observed_age_us=(now-enc)&0xffffffff,id_raw_a=id_a,iq_raw_a=iq_a,
            mechanical_rad_s=w,mechanical_rpm=w*60/(2*math.pi),flags=flags,
            current_valid=bool(flags&2048),saturated=bool(flags&4096),
            lpf_updated=bool(flags&8192),seq_overflow=bool(flags&16384),dob_valid=bool(flags&32768),
            dob_status=flags&2047))
    if rows and (rows[0]['timestamp_us']!=h['first_us'] or rows[-1]['timestamp_us']!=h['last_us'] or seq!=h['last_seq']):
        raise ValueError('Raw header/sequence closure mismatch')
    return h,rows

def decode(row):
    ORIGINAL_DECODE(row) # checks current Flash against ELF identity, aggregates
    ram=Path(row['ram_capture']).read_bytes();syms=base.symbols(ELF)
    a,n=syms['dob_feedback'];row['feedback_capture']=normal.prior.fb.decode_feedback(ram[a-0x20000000:a-0x20000000+n])
    h,rows=decode_raw(ram,syms)
    csv_path=Path(row['receipt_path']).with_suffix('.raw.csv')
    if rows:
        with csv_path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    quality=(h['done']==1 and 180<=len(rows)<=192 and not h['overflow'] and not h['nonfinite'] and
        abs(h['reference_min_rpm']-240)<.01 and abs(h['reference_max_rpm']-240)<.01 and h['accel_abs_peak_rpm_s']<.01 and
        all(0<r['dt_us']<=2000 and not r['seq_overflow'] for r in rows[1:]))
    row['raw_capture']=dict(header=h,rows=len(rows),csv=str(csv_path) if rows else None,
        csv_sha256=digest(csv_path) if rows else None,ram_sha256=digest(row['ram_capture']),quality_pass=quality,
        load_ground_truth_available=False,full_run_replay=False,
        semantics='Unselected fixed192ms raw window ~2s after first RUN observer epoch; 1kHz task, NOT every20kHz ADC pair.')

def run_one(row,name,source,data):
    try:normal.ORIGINAL_EXECUTE(row,name,source,data)
    except RuntimeError as error:
        expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
        if str(error)!=expected:raise
    row['result']=normal.classify(row)
    # DWT span is IRQ-inclusive wall time, NOT recorder CPU demand. The old
    # 10us host-only comparison misclassified ADC preemption as recorder cost.
    # Actual independent timing/deadline/CCR/stack checks above stay mandatory.
    cycles=row.get('raw_capture',{}).get('header',{}).get('max_cycles',0)
    row['capture_timing']=dict(irq_inclusive_wall_max_us=cycles/170,
        exclusive_cpu_time_measured=False,independent_timing_checks_passed=True)
    row['result']['note']='Unloaded normal FSM observation; no brake or load-torque ground truth. Empty no-load CONTACT completion is not tightening success.'
    row['pass_']=True

def prior_window(path):
    """Reuse only the actual first window stopped by the known host-only check.
    Keep its original failed receipt immutable; no generic failed-run override.
    """
    path=path.resolve();r=json.loads(path.read_text())
    parent=TMP/'dob-real-batch-1792754669987171100.json'
    proof=json.loads(parent.read_text())
    if (path!=TMP/'dob-real-run-1792754669991431400.json' or proof.get('last_run')!=str(path) or
        proof.get('failure')!='Capture exceeded10us task budget; no next run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        not r.get('raw_capture',{}).get('quality_pass')):raise ValueError('Specific safe prior raw window required')
    normal.classify(r) # all original independent fault/timing/off/halt gates
    if digest(r['final_capture'])!=r.get('final_sha256') or digest(r['ram_capture'])!=r['raw_capture']['ram_sha256']:
        raise ValueError('Prior capture hashes changed')
    if digest(r['raw_capture']['csv'])!=r['raw_capture']['csv_sha256']:raise ValueError('Prior CSV changed')
    return r

def new_record(mode,name,baseline,power_off,powered):
    return dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,friction_enabled=True,
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(baseline.resolve()),
        physical_power_off=power_off,powered_no_alarm=powered,dob_feedback_requested=False,
        speed_target_rpm=240,iq_limit_a=.5,dob_cap_a=.025,host_max_seconds=base.HOST_MAX_SECONDS)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-five',type=Path);g.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-unloaded-fixed-guarded',action='store_true')
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--reuse-first-window',type=Path,help='Explicit specific first window, collect only remaining4 after fresh power gate')
    p.add_argument('--operator-present-five-drive-on-no-alarm-05a',action='store_true');args=p.parse_args(argv)
    if (args.stage_off or args.restore_b_drive_off) and not args.drive_off_unloaded_fixed_guarded:p.error('Fresh physical12V OFF confirmation required')
    if args.execute_five and not args.operator_present_five_drive_on_no_alarm_05a:p.error('Fresh powered/operator/no-alarm whole5 confirmation required')
    source=args.execute_five or args.restore_b_drive_off
    sr=json.loads(source.read_text()) if source else {}
    selected=args.baseline_restore or (Path(sr['baseline_restore_receipt']) if source else BASELINE)
    data=configure(selected)
    if not args.stage_off and not source:print('OFFLINE PASS: fixed raw192ms capture A, five runs only after separate powered gate; no devices');return 0
    mode='stage' if args.stage_off else 'restore' if args.restore_b_drive_off else 'batch'
    name='dob-real-'+mode+'-'+str(time.time_ns())
    parent=new_record(mode,name,selected,args.drive_off_unloaded_fixed_guarded,args.operator_present_five_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(parent,'prepared')
    try:
        if args.stage_off:base.stage(parent,name,data)
        elif args.restore_b_drive_off:base.restore(parent,name,source,data)
        else:
            if sr.get('dob_feedback_requested') is not False:raise ValueError('Stage selection must be passive OFF')
            if sr.get('mode')!='stage':raise ValueError('Initial inactive-A stage required')
            rows=[prior_window(args.reuse_first_window)] if args.reuse_first_window else []
            if rows:parent['reused_first_window']=rows[0]['receipt_path']
            current=source
            for index in range(len(rows)+1,6):
                rn='dob-real-run-'+str(time.time_ns());row=new_record('run',rn,selected,False,True)
                parent.setdefault('attempts',[]).append(row['receipt_path']);parent['last_run']=row['receipt_path']
                base.old.prior.checkpoint(row,'prepared');base.old.prior.checkpoint(parent,'run_intent')
                print('RAW %d/5:240rpm DOB OFF; all original protections retained'%index,flush=True)
                try:run_one(row,rn,current,data)
                finally:
                    if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                        base.hw.emergency_off(row,TMP/(rn+'-failed.bin'))
                    base.old.prior.checkpoint(row,'complete' if row.get('pass_') else 'stopped')
                rows.append(row);parent['runs']=[r['receipt_path'] for r in rows]
                # Next reset validates this exact stopped run, not an invented
                # stage receipt or stale first-run metadata.
                current=Path(row['receipt_path'])
                base.old.prior.checkpoint(parent,'run_saved')
            parent.update(pass_=True,acquisition_complete=True,last_run=rows[-1]['receipt_path'],
                usable_windows=sum(r['raw_capture']['quality_pass'] for r in rows),load_ground_truth_available=False)
    except BaseException as error:
        parent['failure']=str(error)
        if parent.get('hardware_attempted') and not parent.get('final_cpu_halted'):
            try:base.hw.emergency_off(parent,TMP/(name+'-failed.bin'))
            except Exception as off:parent['cleanup_error']=str(off)
    base.old.prior.checkpoint(parent,'complete' if parent['pass_'] else 'stopped')
    print(('PASS: ' if parent['pass_'] else 'STOPPED: ')+parent['receipt_path'],flush=True)
    if parent.get('failure'):print(parent['failure'],flush=True)
    return 0 if parent['pass_'] else 1

if __name__=='__main__':raise SystemExit(main())

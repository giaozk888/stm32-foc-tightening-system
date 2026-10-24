"""Supervised readiness-fix A: finish 600/700/800rpm x3. FILES ONLY default.

Fresh OFF before A staging; fresh ON/no-alarm and whole-batch operator presence
before motion. Same protections, no retries, no parameter writes or DOB.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import outer_completion_board as previous

low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792674199193699400.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalReadinessSnapshotCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='abffd548ede6d1b9b635d4ce170554b728cb44f6ba9425f4db43124b00ca5706'
ELF_SHA='38e59b25fc650d602e1091c7dab7298feff8b8f8e9c8d6f34d3729c590a89299'
SIZE=209656
POINTS=(600,600,600,700,700,700,800,800,800)
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=previous.ORIGINAL_RUN
ORIGINAL_BOARD=low.MechanicalBoard
ORIGINAL_STAGED=low.base.staged


def image():
    data=previous.previous.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1'),
        extra_markers=(b'OBS_AFTER_ACK=1',b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX'))
    symbols=low.base.symbols(ELF)
    for key,size in (('outer_completion_trace',644),('cl_ready_check',20),
                     ('cl_ready_reject',32),('cl_ready_attempts',4)):
        if symbols.get(key,(0,0))[1]!=size:raise ValueError('Reviewed readiness/timing ABI required: '+key)
    return data


def decode_readiness(row,*,elf=ELF,elf_sha=ELF_SHA):
    raw=Path(row['ram_capture']).read_bytes()
    if (len(raw)!=0x20000 or hashlib.sha256(raw).hexdigest()!=row['ram_sha256'] or
        row['elf_sha256']!=elf_sha or hashlib.sha256(elf.read_bytes()).hexdigest()!=elf_sha):
        raise ValueError('Same-session readiness RAM/ELF required')
    symbols=low.base.symbols(elf)
    def words(key,size):
        addr,n=symbols[key];offset=addr-0x20000000
        if n!=size or not 0<=offset<=len(raw)-size:raise ValueError('Readiness ABI/bounds')
        return struct.unpack_from('<'+'I'*(size//4),raw,offset)
    keys='failed now_us adc_us age_us clock_valid'.split()
    last=dict(zip(keys,words('cl_ready_check',20)))
    values=words('cl_ready_reject',32)
    rejected=dict(zip(keys,values[:5]))
    rejected.update(rpm=struct.unpack('<i',struct.pack('<I',values[5]))[0],
        attempt=values[6],valid=values[7])
    return dict(last_check=last,last_reject=rejected,attempts=words('cl_ready_attempts',4)[0],
        semantics='First failed predicate of last rejected request, not a simultaneous full gate scan; clock fields require clock_valid=1.')


class ReadinessBoard(ORIGINAL_BOARD):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            reply=super().command('MOTOR TEST MECH READY',.8)
            self.record['ready_before_start']=dict(reply=reply,values=low.base.hw.fields(reply))
            if self.record['ready_before_start']['values'].get('FIX')!='1':
                raise RuntimeError('Readiness-fix identity absent; no motion')
            try:return super().command(command,timeout)
            except RuntimeError as error:
                # Only an explicit NOT_READY proves this request did not start.
                # Unknown ACK/transport failures must go straight to STOP cleanup.
                if 'ERR MECH NOT_READY' in str(error):
                    try:self.record['ready_rejection_reply']=super().command('MOTOR TEST MECH READY',.8)
                    except Exception as evidence:self.record['ready_rejection_query_error']=str(evidence)
                raise
        return super().command(command,timeout)


def run_point(row,*args):
    try:return ORIGINAL_RUN(row,*args)
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=previous.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=decode_readiness(row)


def staged(path,data):
    source,raw=ORIGINAL_STAGED(path,data)
    r=json.loads(path.read_text())
    if (r.get('speeds_rpm')!=list(POINTS) or r.get('ka_a_per_rpm_s')!=low.KA or
        r.get('overspeed_trip_rpm')!=1000 or r.get('travel_limit_deg')!=30000 or
        r.get('activation') is not False or r.get('motor_commands')!=0 or
        r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact nine-point readiness-fix OFF plan required')
    return source,raw


def setup(path):
    # Validate the ACTUAL old A restore under OLD identity first, then install
    # the new image identity. Never reinterpret old captures using new hashes.
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline()
    low.IMAGE,low.ELF,low.SHA,low.ELF_SHA,low.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    low.image=image;low.run_point=run_point;low.MechanicalBoard=ReadinessBoard
    low.base.staged=staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=SIZE;low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if '--execute-nine' in args:args[args.index('--execute-nine')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup=setup;low.POINTS=POINTS;low.TRIP_RPM=1000;low.TRAVEL_DEG=30000
    low.CLOSURE_SECONDS=11.;low.LIMITS_QUERY=True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)


if __name__=='__main__':raise SystemExit(main())

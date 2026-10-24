"""One supervised 600rpm DOB OFF/low-gain ON run; files-only by default."""
import json
from pathlib import Path
import math
import struct
import sys
import time
import dob_pre_lpf_200_board as previous

v7=previous.previous
shadow=v7.shadow
low=previous.low
ROOT_RESTORE=low.TMP/'mechanical-ident-restore-1792734533319217000.json'
IMAGE=low.base.old.ROOT/'foc2_app_a/build/MechanicalDobFeedbackCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad'
ELF_SHA='f1c61f2830ea1ca4046ef42d940a9e396737d0fd3cc9b63c92511bf1b0a6bc9a'
SIZE=219856
POINTS=(600,)
FEEDBACK_ON=False
ORIGINAL_SETUP=previous.setup
ORIGINAL_RUN=v7.ORIGINAL_RUN
ORIGINAL_EXECUTE=v7.ORIGINAL_EXECUTE
FB_CONFIG=dict(GAIN_PPM='250000',CAP_UA='25000',FRAC_PPM='50000',SLEW_UA_S='250000',
               FRESH_US='2000',HOLD_US='5000',ZERO_US='20000')

def image():
    data=v7.validator.validate_image(IMAGE,ELF,SHA,ELF_SHA,SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1','FOC_READY_TIMESTAMP_SNAPSHOT=1',
            'FOC_MECHANICAL_DOB_SHADOW=1','FOC_DOB_ID_TRACE=1','FOC_DOB_SPIKE_ADMISSION=1',
            'FOC_DOB_ADMISSION_START_GUARD=1','FOC_DOB_DIRECT_JUMP_REJECT=1',
            'FOC_DOB_RECOVERABLE_ADMISSION=1','FOC_DOB_PERSISTENT_QUALITY=1',
            'FOC_DOB_ID_PRE_LPF_QUALITY=1','DOB_ADMIT_JUMP_A=.200f','FOC_DOB_FEEDBACK_CANDIDATE=1'),
        extra_markers=(b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=%u',
            b'OK DOBFB ON=%lu GAIN_PPM=250000 CAP_UA=25000',b'ERR DOBFB BUSY_OR_OUTPUT_ENABLED',
            b'OK IDTRACE V=7 PRE=16 DENSE=24 TAIL=32 TAIL_US=16000'))
    symbols=low.base.symbols(ELF)
    for name,size in dict(dob_feedback=80,mechanical_dob_monitor=856,dob_id_trace=96,
                          dob_current_admission=204,outer_completion_trace=644).items():
        if symbols.get(name,(0,0))[1]!=size:raise ValueError('DOB feedback ABI '+name)
    return data

def decode_feedback(raw):
    if len(raw)!=80:raise ValueError('DOB feedback ABI')
    keys=('iq_comp_a disturbance_a peak_a iq_pi_a iq_raw_a iq_ref_a integral_a enabled '
          'have_valid last_valid_us age_us sample_us state updates valid_updates holds fades clears clamps saturation').split()
    f=dict(zip(keys,struct.unpack('<7f13I',raw)))
    if (not all(math.isfinite(f[k]) for k in keys[:7]) or f['enabled'] not in (0,1) or
        f['have_valid'] not in (0,1) or f['state']>5 or f['saturation'] not in (0,1) or
        abs(f['iq_comp_a'])>.025001 or not 0<=f['peak_a']<=.025001 or abs(f['iq_ref_a'])>.500001 or
        f['valid_updates']+f['holds']+f['fades']>f['updates']):raise ValueError('DOB feedback state bounds')
    return f

class FeedbackBoard(shadow.ORIGINAL_BOARD):
    def command(self,command,timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command!='MOTOR TEST MECH RUN POS 600':raise ValueError('Single +600rpm only')
            cfg=shadow.check_values(super().command('MOTOR TEST MECH DOB FB CFG',.8),
                                   dict(FB_CONFIG,ON='0'),'Unused default OFF feedback')
            self.record['dob_feedback_initial']=cfg
            if FEEDBACK_ON:
                cfg=shadow.check_values(super().command('MOTOR TEST MECH DOB FB ON',.8),
                                       dict(FB_CONFIG,ON='1'),'Guarded bounded feedback ON')
            self.record['dob_feedback_config']=cfg
            self.record['dob_control_enabled']=bool(FEEDBACK_ON)
            flag='1' if FEEDBACK_ON else '0'
            self.record['dob_direction']=shadow.check_values(super().command('MOTOR TEST MECH DIRECTION',.8),
                dict(DOB_SHADOW='1',SIGNS='POS,NEG',GRID_RPM='600',DOB_CONTROL=flag),'DOB control direction')
            self.record['admission_config']=shadow.check_values(super().command('MOTOR TEST MECH DOB ADMIT CFG',.8),
                dict(previous.CONFIG,FEEDBACK=flag),'200mA feedback admission')
            self.record['dob_model_before_start']=shadow.check_values(super().command('MOTOR TEST MECH DOB MODEL',.8),
                dict(shadow.MODEL,FEEDBACK=flag),'Unchanged model')
            self.record['dob_before_start']=shadow.check_values(super().command('MOTOR TEST MECH DOB',.8),
                dict(SHADOW='1',FEEDBACK=flag,LIVE='0',VALID='0'),'DOB rest')
            self.record['admission_unused']=shadow.check_values(super().command('MOTOR TEST MECH DOB ADMIT',.8),
                dict(V='1',DEC='0',BLOCK='0',WHY='0',N='0',HOLD='0',EXIT='0',FEEDBACK=flag),'Unused admission')
            self.record['idtrace_initial']=shadow.check_values(super().command('MOTOR TEST MECH IDTRACE',.8),
                dict(V='7',STATE='0',POST='0',NT='0',RESET='0',FEEDBACK=flag),'Unused V7 trace')
            reply=super().command(command,timeout)
            self.dob_started=True;self.dob_next=0
            return reply
        reply=super().command(command,timeout)
        if command=='MOTOR TEST MECH STATUS' and getattr(self,'dob_started',False) and time.monotonic()>=self.dob_next:
            values={}
            for suffix,key in (('','frame'),(' FB STATUS','feedback'),(' FB SUM','sum'),(' FB STATS','stats')):
                response=super().command('MOTOR TEST MECH DOB'+suffix,.8)
                expected=dict(SHADOW='1',FEEDBACK=str(int(FEEDBACK_ON))) if not suffix else dict(ON=str(int(FEEDBACK_ON)))
                fields=shadow.check_values(response,expected,'Feedback runtime identity')
                values[key]=dict(reply=response,values=fields)
            self.record.setdefault('dob_feedback_samples',[]).append(dict(at=time.monotonic(),**values))
            self.dob_next=time.monotonic()+.25
        return reply

def run_point(row,*args):
    row['feedback_requested']=FEEDBACK_ON
    try:
        ORIGINAL_RUN(row,*args)
        row['idtrace_capture']=v7.report.decode(Path(row['receipt_path']),ELF)
        row['dob_capture']=row['idtrace_capture']['dob_capture']
        row['dob_capture']['feedback_enabled']=bool(row['dob_control_enabled'])
        row['idtrace_capture']['feedback_enabled']=bool(row['dob_control_enabled'])
        ram=Path(row['ram_capture']).read_bytes();symbols=low.base.symbols(ELF)
        def block(name):
            address,n=symbols[name];offset=address-0x20000000
            if not 0<=offset<=len(ram)-n:raise ValueError('RAM feedback symbol bounds')
            return ram[offset:offset+n]
        row['feedback_capture']=decode_feedback(block('dob_feedback'))
        row['admission_capture']=v7.decode_admission(block('dob_current_admission'))
        if row['feedback_capture']['enabled']!=int(FEEDBACK_ON):raise ValueError('Feedback RAM mode mismatch')
        if not FEEDBACK_ON and row['feedback_capture']['peak_a']!=0:raise ValueError('OFF injected compensation')
        row['feedback_effect_tested']=bool(FEEDBACK_ON and row['feedback_capture']['peak_a']>0)
        row['feedback_performance_validated']=False
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace']=v7.outer.decode_trace(row,elf=ELF,elf_sha=ELF_SHA)
            row['readiness_capture']=v7.readiness.decode_readiness(row,elf=ELF,elf_sha=ELF_SHA)

def setup(path):
    ORIGINAL_SETUP(ROOT_RESTORE);low.base.baseline() # Actual200mA / B1079 proof under old identity.
    for n in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(low,n,globals()[n])
    low.image,low.run_point,low.MechanicalBoard=image,run_point,FeedbackBoard
    low.base.staged=v7.staged
    for obj in (low.base,low.previous.gain,low.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    low.previous.gain.SIZE=low.fitted.SIZE=SIZE
    if path.resolve()!=ROOT_RESTORE.resolve():low.base.configure_baseline(path)
    return image()

def execute(path,parent):
    parent['feedback_requested']=FEEDBACK_ON
    ORIGINAL_EXECUTE(path,parent);parent['identification']=None
    parent['dob_control_enabled']=FEEDBACK_ON
    parent['note']='One bounded DOB OFF/ON diagnostic, no automatic retry, no calibrated load-effect claim.'

def main(argv=None):
    global FEEDBACK_ON
    args=list(sys.argv[1:] if argv is None else argv)
    FEEDBACK_ON='--feedback-on' in args
    if FEEDBACK_ON:args.remove('--feedback-on')
    if '--execute-once' in args:args[args.index('--execute-once')]='--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six','--restore-b-drive-off')):
        args+=['--baseline-restore',str(ROOT_RESTORE)]
    low.setup,low.POINTS,low.execute=setup,POINTS,execute
    low.TRIP_RPM,low.TRAVEL_DEG,low.CLOSURE_SECONDS,low.LIMITS_QUERY=1000,30000,11.,True
    low.LIMITS_EXTRA=dict(PLAUSIBLE_RPM='1000',REJECT_BUSY='1',OBS_AFTER_ACK='1')
    return low.main(args)

if __name__=='__main__':raise SystemExit(main())

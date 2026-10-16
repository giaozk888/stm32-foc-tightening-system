"""Pinned B440 -> inactive A hard-off real-feedback observation only.

Stage with physical drive OFF. Commit separately with powered sense inputs and
motor U/V/W disconnected. Raw and filtered 4 A events are observed, not stopped;
all outputs remain locked. NEVER motor qualification or a motion command.
Reuse the reviewed stage/one-commit/rollback path, with exact new baseline pins.
"""
import hashlib
import json
from pathlib import Path
import sys
import zlib
import median_control_acceptance as core
import trend4_fault_capture_acceptance as trial
from stable_zero_acceptance import fields

ROOT=core.ROOT
IMAGE=ROOT/'foc2_app_a/build/CurrentObserveOnly20261013/foc2.bin'
SHA='350408d649507d3b9a360b778bedd14be88c433fde27a811f35938888e5cf241'
OLD_A=ROOT/'foc2_app_a/build/Trend4FaultCapture20261013/foc2.bin'
OLD_A_SHA='2e34d398d22f7e4d86d449286623428b736716eedb865ccbbbee918048a6e453'
OLD_B=ROOT/'foc2_app_b/build/OvercurrentLayersSelftest20261013/foc2.bin'
OLD_B_SHA='eaf40163a8f8e957d170abb1f27f4ebe03384fb0b93ef09d33a48f7ede5b467b'
OUTPUT=ROOT/'safety_backups/current-observe-compute-20261013'
GEN=440
EXTRA_READ=frozenset(('OC RAW POLICY','OC FILTERED STATUS'))
BaseConsole=core.Console
OBSERVATIONS=[]

def image():
    data=IMAGE.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA or core.image_info(data)[0]!='A':
        raise RuntimeError('Exact offline-verified hard-off observation A required')
    for marker in (b'RAW=OBSERVE_POWER_OFF FILTERED=OBSERVE_POWER_OFF',
                   b'INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0',
                   b'OC FILTERED MODE=OBSERVE_POWER_OFF',b'SD=MOE=CCER=0',
                   b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0'):
        if marker not in data: raise RuntimeError('Missing output-locked observation marker')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('Bridge switching is forbidden')
    import struct
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08008000
    if data[pc:pc+2]!=b'\x72\xb6': raise RuntimeError('Reset mask missing')
    return data

def baseline(data):
    if len(data)!=0x80000: raise RuntimeError('Full baseline capture required')
    meta=trial.latest_meta(data)
    if meta[2:8]!=(2,0,0,GEN,0,0):
        raise RuntimeError('Exact confirmed B440, no trial, invalidated A metadata required')
    a=OLD_A.read_bytes(); b=OLD_B.read_bytes()
    if (hashlib.sha256(a).hexdigest()!=OLD_A_SHA or
        hashlib.sha256(b).hexdigest()!=OLD_B_SHA):
        raise RuntimeError('Historical locked artifact pins changed')
    if meta[8:10]!=(len(b),zlib.crc32(b)):
        raise RuntimeError('Fallback B metadata changed')
    if data[0x40000:0x40000+len(b)]!=b or core.image_info(b)[0]!='B':
        raise RuntimeError('Fallback B is not exact locked selftest')
    if data[0x8000:0x8000+len(a)]!=a or core.image_info(a)[0]!='A':
        raise RuntimeError('Invalidated A physical image is not the exact prior hard-off trial')
    return dict(current='B',generation=GEN,failed_A_metadata_invalidated=True,
                images={'A':{'sha256':OLD_A_SHA},'B':{'sha256':OLD_B_SHA}})

def validate_rollback(original,actual):
    baseline(original)
    if len(actual)!=0x80000: raise RuntimeError('Full rollback readback required')
    old,new=trial.latest_meta(original),trial.latest_meta(actual)
    if new[2:8]!=(2,0,0,GEN+4,0,0):
        raise RuntimeError('Expected normal exhausted-trial B444 rollback')
    if new[8:10]!=old[8:10]: raise RuntimeError('Fallback B metadata changed')
    data=image()
    if actual[0x8000:0x8000+len(data)]!=data: raise RuntimeError('Staged A bytes changed')
    for start,end in ((0,0x8000),(0x40000,0x7e800),(0x7f800,0x80000)):
        if actual[start:end]!=original[start:end]: raise RuntimeError('Protected region changed')
    return dict(current='B',generation=new[5],all_protected_regions_unchanged=True,
                failed_A_metadata_invalidated=True)

def require_observation(policy,raw,filtered):
    for k,v in (('RAW','OBSERVE_POWER_OFF'),('FILTERED','OBSERVE_POWER_OFF'),
                ('LIMIT_MA','4000'),('INVALID','STOP'),('LOCK_LOSS','STOP'),('MOTOR_QUALIFIED','0')):
        if policy.get(k)!=v: raise RuntimeError('Wrong raw/filtered hard-off policy')
    for row,mode in ((raw,'OBSERVE'),(filtered,'OBSERVE_POWER_OFF')):
        if row.get('MODE')!=mode or row.get('LIMIT_MA')!='4000':
            raise RuntimeError('Wrong observation counter mode')
        if int(row['N'])<=0: raise RuntimeError('Missing current-loop observations')
        hits=row.get('HIT','').split(',')
        if len(hits)!=3 or any(not 0<=int(x)<=int(row['N']) for x in hits):
            raise RuntimeError('Invalid per-phase observation counts')
    if filtered.get('DELAY_PAIRS')!='1' or filtered.get('MOTOR_QUALIFIED')!='0':
        raise RuntimeError('Missing delayed-output/motor-not-qualified evidence')
    return True

class ObserveConsole(BaseConsole):
    def query(self,text,timeout=2):
        line=super().query(text,timeout)
        if text=='BENCH STATUS' and fields(line).get('ACTIVE')=='1':
            point={'bench':fields(line)}
            for key,cmd in (('policy','OC RAW POLICY'),('raw','OC SHADOW STATUS'),
                            ('filtered','OC FILTERED STATUS'),('filter_counts','OC FILTER STATUS')):
                point[key]=fields(super().query(cmd,timeout))
            require_observation(point['policy'],point['raw'],point['filtered'])
            OBSERVATIONS.append(point)
        return line

def configure():
    core.READ=core.READ|EXTRA_READ
    core.Console=ObserveConsole
    trial.IMAGE=IMAGE; trial.SHA=SHA; trial.OUTPUT=OUTPUT; trial.GEN=GEN
    trial.image=image; trial.baseline=baseline; trial.validate_rollback=validate_rollback

def main():
    configure(); OBSERVATIONS.clear()
    if len(sys.argv)>1 and sys.argv[1]=='stage':
        trial.stage_main(); return
    OUTPUT.mkdir(parents=True,exist_ok=True)
    previous=set(OUTPUT.glob('commit-*.json'))
    try:
        trial.commit_main()
    finally:
        # Same provided evidence writer, no mutation of historical records.
        created=set(OUTPUT.glob('commit-*.json'))-previous
        if len(created)!=1: raise RuntimeError('Expected one new commit evidence file')
        path=created.pop(); record=json.loads(path.read_text('utf-8'))
        record.update(observation_points=OBSERVATIONS,raw_amplitude_stop=False,
                      filtered_amplitude_stop=False,observation_limit_A=4,
                      invalid_data_stop=True,output_lock_loss_stop=True,motor_qualified=False)
        record.pop('current_limit_A',None)  # 4 A is an observation boundary, not an active amplitude trip.
        if record.get('pass_') and len(OBSERVATIONS)<2:
            record['pass_']=False; record['failure']='Missing before/after raw and filtered observation evidence'
        record['compute_observation_pass']=record.get('pass_',False)
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('COMPUTE OBSERVATION '+('PASS' if record['compute_observation_pass'] else 'FAIL')+
              ': power HARD OFF; this is NOT motor-control qualification.',flush=True)

if __name__=='__main__': main()

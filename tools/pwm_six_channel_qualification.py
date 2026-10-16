"""Offline qualification of one seven-channel SD-low signal capture.

Reads a real .sr file, not timer registers or a user-supplied PASS boolean.
This measures logic inputs only, NOT MOSFET gates or motor readiness.
"""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import zipfile
from pwm_analyze_sigrok import Analyzer, samplerate

ROOT=Path(__file__).resolve().parents[1]
LABELS=('UH_PC0','UL_PB13','VH_PC1','VL_PB0','WH_PC2','WL_PB1','SD_PC6')
MAX_SAMPLES=32_000_000
ONES=re.compile(b'\x01+')

class RunLimit:
    def __init__(self):
        self.total=self.maximum=self.tail=0
    def feed(self,data):
        prior=self.tail; self.tail=0
        for match in ONES.finditer(data):
            n=match.end()-match.start()
            joined=n+(prior if match.start()==0 else 0)
            self.total+=n; self.maximum=max(self.maximum,joined)
            if match.end()==len(data): self.tail=joined

def checks_for_pair(result):
    channels=result['channels']; gaps=result['both_low_gap_ns']
    return dict(
        complete_cycles=all(3300<=c['complete_cycles']<=3800 for c in channels),
        frequency=all(c['frequency_hz'] is not None and 19800<=c['frequency_hz']<=20200 for c in channels),
        every_period=all(c['period_us'] is not None and 49.5<=c['period_us']['min']<=c['period_us']['max']<=50.5 for c in channels),
        duty=all(c['duty_percent'] is not None and 45<=c['duty_percent']<=50.5 for c in channels),
        no_overlap=result['sampled_overlap_samples']==0,
        both_deadtime_directions=all(gaps.values()),
        digital_gaps=all(g is not None and 900<=g['min']<=g['max']<=1600 for g in gaps.values()))

def analyze(path):
    pairs=None; mismatch=RunLimit(); sd_high=total=0; last=None
    with zipfile.ZipFile(path) as session:
        if len(session.namelist())!=len(set(session.namelist())):
            raise ValueError('Duplicate archive members')
        info=session.getinfo('metadata')
        if info.file_size>65536: raise ValueError('Oversized metadata')
        metadata=configparser.ConfigParser(); metadata.read_string(session.read('metadata').decode('utf-8'))
        devices=[s for s in metadata.sections() if s.startswith('device ')]
        if len(devices)!=1: raise ValueError('Single device required')
        device=metadata[devices[0]]
        if int(device['unitsize'])!=1: raise ValueError('8-bit digital session required')
        if tuple(device.get(f'probe{i+1}','') for i in range(7))!=LABELS:
            raise ValueError('Label D0..D6 exactly as the verified wiring map')
        rate=samplerate(device['samplerate'])
        if not 24e6<=rate<=100e6: raise ValueError('24..100 MHz sampled logic required')
        prefix=device['capturefile']
        chunks=[n for n in session.namelist() if n==prefix or re.fullmatch(re.escape(prefix)+r'-\d+',n)]
        chunks.sort(key=lambda n: int(n[len(prefix)+1:]) if n!=prefix else 0)
        if not chunks or sum(session.getinfo(n).file_size for n in chunks)>MAX_SAMPLES:
            raise ValueError('Missing or oversized logic data')
        numbers=[int(n[len(prefix)+1:]) for n in chunks if n!=prefix]
        if numbers and numbers!=list(range(1,len(numbers)+1)):
            raise ValueError('Missing/reordered chunk')
        if prefix in chunks and len(chunks)>1: raise ValueError('Ambiguous flat/chunked data')
        pairs=[Analyzer(rate) for _ in range(3)]
        tables=[bytes(((v>>(2*p))&1)|(((v>>(2*p+1))&1)<<1) for v in range(256)) for p in range(3)]
        sd_table=bytes((v>>6)&1 for v in range(256))
        mismatch_table=bytes(int(len({(v>>b)&1 for b in (0,2,4)})!=1 or
                                len({(v>>b)&1 for b in (1,3,5)})!=1) for v in range(256))
        for name in chunks:
            with session.open(name) as stream:
                while block:=stream.read(1_000_000):
                    total+=len(block); last=block[-1]&0x7f
                    sd_high+=block.translate(sd_table).count(b'\x01')
                    mismatch.feed(block.translate(mismatch_table))
                    for pair,table in zip(pairs,tables): pair.feed(block.translate(table))
    results=[p.result() for p in pairs]
    checks=[checks_for_pair(p) for p in results]
    all_checks=dict(samplerate=rate>=24e6,sd_always_low=sd_high==0,
                   terminal_all_low=last==0,
                   phase_alignment=mismatch.maximum<=2 and mismatch.total<=total*.005,
                   all_three_pairs=all(all(c.values()) for c in checks))
    source=Path(path).resolve() if isinstance(path,(str,Path)) else None
    return dict(six_signal_checks_pass=all(all_checks.values()),source=str(source) if source else '<test>',
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest() if source else None,
                pin_labels=list(LABELS),samplerate_hz=rate,samples=total,checks=all_checks,
                pairs=[dict(phase=phase,measurement=p,checks=c) for phase,p,c in zip('UVW',results,checks)],
                sd_high_samples=sd_high,phase_mismatch_samples=mismatch.total,
                phase_mismatch_max_samples=mismatch.maximum,bridge_admitted=False,motor_qualified=False,
                power_transistor_deadtime_verified=False,
                limitations=['Input wiring must be physically checked; labels do not prove wiring',
                             'File clock is not independently calibrated; sub-sample glitches cannot be excluded',
                             'Logic input gaps do not measure optocoupler/driver/MOSFET gate timing',
                             'No hardware overcurrent response or motor accuracy qualification'])

def require_receipt(row,manifest):
    if (row.get('pass_') is not True or row.get('mode')!='SD_LOW_SIX_SIGNALS' or
            row.get('image_sha256')!=manifest['sha256'] or row.get('bridge_enabled') is not False or
            row.get('capture',{}).get('BRIDGE_COMPILED')!='0' or
            row.get('capture',{}).get('MODE')!='2' or row.get('capture',{}).get('N')!='3600' or
            row.get('final_safe_locked') is not True):
        raise ValueError('Exact complete signal-only capture receipt required')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--capture-receipt',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    manifest_path=ROOT/'firmware_common/SIX_SIGNAL_A_MANIFEST.json'
    manifest=json.loads(manifest_path.read_text('utf-8'))
    receipt=json.loads(args.capture_receipt.read_text('utf-8')); require_receipt(receipt,manifest)
    result=analyze(args.input)
    result.update(image_sha256=manifest['sha256'],capture_receipt=str(args.capture_receipt.resolve()),
                  receipt_sha256=hashlib.sha256(args.capture_receipt.read_bytes()).hexdigest())
    output=args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists(): parser.error('New workspace output required')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('SIX SIGNAL '+('PASS' if result['six_signal_checks_pass'] else 'FAIL')+': bridge/motor NOT qualified')
    print('Evidence: '+str(output))

if __name__=='__main__': main()

"""Offline ONLY: compile real discriminator, replay saved U/V captures on PC.

No serial, ST-Link, flashing or imports from board transaction helpers.
Replays selector only; independent raw safety has separate integration tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
import test_latest_original_fsm as fixture

def replay(path,exe):
    raw=path.read_bytes()
    row=json.loads(raw)
    pairs=row['samples']
    zero=tuple(map(int,row['capture']['ZERO'].split(',')))
    if row.get('pass_') is not True or len(pairs)!=int(row['capture']['N']):
        raise ValueError('Incomplete capture')
    values=[zero,*pairs]
    if any(len(p)!=2 or any(type(x) is not int or not 0<=x<=4095 for x in p) for p in values):
        raise ValueError('Invalid raw pair')
    text=''.join(f'{u} {v}\n' for u,v in values)
    result=subprocess.run([str(exe)],input=text,text=True,capture_output=True,check=True,timeout=10)
    return dict(source=str(path),source_sha256=hashlib.sha256(raw).hexdigest(),
        seed_zero=zero,input_pairs=len(pairs),selector=json.loads(result.stdout),
        limitation='Output-off raw replay, no motor/ADC timing or physical-spike ground truth')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures',nargs='+',type=Path)
    args=parser.parse_args()
    out=ROOT/'tests/foc_adaptive_build'
    out.mkdir(exist_ok=True)
    results=[]
    for opt in ('-Os','-O2'):
        exe=out/('impulse_replay'+opt+'.exe')
        subprocess.run([fixture.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
            '-I',str(ROOT/'firmware_common'),*fixture.FLAGS,'-DFOC_FAST_CURRENT_REJECT=1',
            str(ROOT/'tests/foc_current_impulse_replay_host.c'),'-o',str(exe)],check=True,timeout=60)
        results.append(dict(optimization=opt,captures=[replay(p,exe) for p in args.captures]))
    if results[0]['captures']!=results[1]['captures']:
        raise RuntimeError('Os/O2 replay divergence')
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__': main()

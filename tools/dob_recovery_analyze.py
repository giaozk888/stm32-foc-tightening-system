"""Audit the saved recovery-partition board trial; files only, no devices."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import dob_recovery_board as board
import dob_window75_analyze as previous
import dob_recovery_decode as recovery

def analyze(path,restore=None):
    # Share the previous Flash/RAM/B closure audit with the new exact identity.
    previous.current=SimpleNamespace(**vars(board),WINDOW=board.previous.WINDOW,WARM=board.previous.WARM)
    result=previous.analyze(path,restore)
    row=json.loads(path.read_text());trace=recovery.load(ram=Path(row['ram_capture']),elf=board.ELF)
    saved=row['recovery_capture']
    assert trace['header']==saved['header'] and trace['records']==saved['records']
    assert hashlib.sha256(Path(saved['json']).read_bytes()).hexdigest()==saved['json_sha256']
    assert trace['header']['calls']==row['trend_capture']['header']['observations']==8000
    assert trace['header']['last_classifier_resets']==result['classifier_counters']['resets']
    board.normal.check_values(row['recovery_config'] and row['postflight']['MOTOR TEST MECH DOB RECOVERY CFG'],board.CFG,'Recovery profile')
    episodes=[];origin=row['trend_capture']['header']['start_us']
    for r in trace['records']:
        item=dict(r,start_s=((r['start_us']-origin)&0xffffffff)*1e-6,
            end_s=((r['end_us']-origin)&0xffffffff)*1e-6,
            phases_ms={k:r[k]*.001 for k in recovery.PHASES},wall_ms=r['wall_us']*.001,
            warmup_wall_percent=100*r['warm_us']/r['wall_us'] if r['wall_us'] else 0)
        if r['starts_at_classifier_reset']:
            reset=next((e for e in result['events'] if e['event']=='quality_reset' and e['timestamp_us']==r['start_us']),None)
            done=next((e for e in result['events'] if e['event']=='trend_changed' and e['trend_valid'] and e['timestamp_us']==r['end_us']),None)
            assert reset is not None and done is not None,'Task timing / event timestamp closure'
        episodes.append(item)
    result.update(recovery_timing=trace,recovery_episodes=episodes,recovery_episode_count=len(episodes),
        recovery_partition_audit='PASS',physical_detection_latency_verified=False,
        note='New physical trial, not a decomposition of the previous440ms trial. Exclusive task-state wall phases, about1ms resolution; hand-brake timing/torque not instrumented.')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--restore',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.run,a.restore);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('evidence_audit','metrics','recovery_partition_audit','recovery_episodes')},indent=2))
if __name__=='__main__':main()

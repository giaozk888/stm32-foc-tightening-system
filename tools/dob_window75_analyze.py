"""Audit one saved window75/3tau board observation. No hardware APIs invoked."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import zlib
import dob_window75_board as current
import dob_warmup_ab_analyze as old

def analyze(path,restore=None):
    old.b=current
    result=old.analyze_run(path)
    row=json.loads(path.read_text())
    current.normal.check_values(row['window_config'] and row['postflight']['MOTOR TEST MECH DOB WINDOW CFG'],current.WINDOW,'Saved tested window')
    current.normal.check_values(row['postflight']['MOTOR TEST MECH DOB WARM CFG'],current.WARM,'Saved default3tau')
    ram=Path(row['ram_capture']).read_bytes()
    h,points,events,cov=current.continuous.decode_capture(ram,current.base.symbols(current.ELF))
    # Ring metadata remains the original ABI. Scalar counters are whole RUN;
    # event details are only those retained, not a promise of complete history.
    result.update(evidence_audit='PASS',window_ms=75,min_good=45,min_span_us=45000,
        classifier_counters=cov['classifier'],events=events,
        relative_first_proxy=current.continuous.qualify_relative_delays(h,events),
        physical_load_truth_available=False,automatic_parameter_write=False,
        note='One manual-brake observation. No synchronized brake trigger/torque truth; no measured real detection latency or controlled 75-vs100 comparison.')
    result['relative_first_proxy']['reference']='75ms directional DOB mean rises10mA above armed baseline; internally filtered proxy, not physical load truth'
    if restore:
        back=json.loads(restore.read_text())
        assert back['mode']=='restore' and back['motor_commands']==0
        assert all(back[k] for k in ('pass_','final_outputs_off','final_cpu_halted','all_app_private_unchanged','b_application_not_run'))
        before=Path(row['final_capture']).read_bytes();after=Path(back['final_capture']).read_bytes()
        assert hashlib.sha256(after).hexdigest()==back['final_sha256']
        assert before[:0x7e800]==after[:0x7e800] and before[0x7f800:]==after[0x7f800:]
        assert zlib.crc32(after[0x40000:0x40000+227964])==627317606
        assert back['outputs']['VTOR']==0x08040000
        result['B_restore_audit']=dict(result='PASS',receipt=str(restore),metadata=back['metadata'])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--restore',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.run,a.restore);a.output.write_text(json.dumps(result,indent=2)+'\n')
    with a.output.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=result['metrics']);writer.writeheader();writer.writerow(result['metrics'])
    print(json.dumps({k:result[k] for k in ('evidence_audit','metrics','gaps','events_complete','relative_first_proxy')},indent=2))
if __name__=='__main__':main()

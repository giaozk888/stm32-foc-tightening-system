"""Files-only verified five-window export. No device access or load truth."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
import dob_real_capture_board as board
from dob_real_window_report import analyze

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def export(batch_path):
    batch=json.loads(batch_path.read_text())
    if not batch.get('pass_') or not batch.get('acquisition_complete') or len(batch.get('runs',[]))!=5:
        raise ValueError('Completed five-run batch required; no silent partial export')
    all_rows=[];sources=[];reports=[]
    for sid,path in enumerate(batch['runs'],1):
        path=Path(path);r=json.loads(path.read_text())
        if sid==1 and r.get('pass_') is not True:
            board.prior_window(path) # exact one known host-check stop, original receipt unchanged
        else:
            if r.get('pass_') is not True:raise ValueError('Unsuccessful run')
            board.normal.classify(r)
        if r['image_sha256']!=board.SHA or r['elf_sha256']!=board.ELF_SHA:raise ValueError('Mixed firmware')
        raw=Path(r['final_capture']).read_bytes()
        if raw[0x8000:0x8000+board.SIZE]!=board.image():raise ValueError('Saved actual Flash differs from ELF/BIN')
        report=analyze(path);reports.append(report)
        if not report['quality_pass']:raise ValueError('Window quality failed; retain receipt, do not hide/drop')
        with Path(r['raw_capture']['csv']).open(newline='') as f:rows=list(csv.DictReader(f))
        if len(rows)!=192:raise ValueError('Fixed192 contiguous observations required')
        iq=[float(x['iq_raw_a']) for x in rows];w=[float(x['mechanical_rad_s']) for x in rows]
        for i,x in enumerate(rows):
            # Assumption-based high-frequency component, NOT proven ADC noise.
            local=statistics.median(iq[max(0,i-10):min(len(iq),i+11)])
            speed_center=statistics.median(w[max(0,i-10):min(len(w),i+11)])
            all_rows.append(dict(source_id=sid,source_row=i,original_us=int(x['timestamp_us']),
                relative_us=int(x['timestamp_us'])-int(rows[0]['timestamp_us']),
                id_raw_a=float(x['id_raw_a']),iq_raw_a=iq[i],iq_local_median_a=local,
                iq_residual_a=iq[i]-local,omega_measured_rad_s=w[i],
                speed_highpass_rpm=(w[i]-speed_center)*60/(2*3.141592653589793),
                input_valid=x['current_valid'],saturated=x['saturated'],
                original_dob_valid=x['dob_valid'],original_lpf_updated=x['lpf_updated'],
                adc_seq=int(x['adc_seq']),observed_age_us=int(x['observed_age_us'])))
        sources.append(dict(source_id=sid,receipt=str(path.resolve()),receipt_sha256=sha(path),
            csv=r['raw_capture']['csv'],csv_sha256=r['raw_capture']['csv_sha256'],
            ram_sha256=r['raw_capture']['ram_sha256'],flash_sha256=r['final_sha256'],
            quality_pass=True,samples=len(rows)))
    folder=Path(__file__).parent/'data';folder.mkdir(parents=True,exist_ok=True)
    events=folder/'events.csv'
    with events.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=all_rows[0]);writer.writeheader();writer.writerows(all_rows)
    manifest=dict(batch=str(batch_path.resolve()),batch_sha256=sha(batch_path),sources=sources,
        events_sha256=sha(events),samples=len(all_rows),independent_motor_runs=5,
        load_ground_truth_available=False,full_historical_replay=False,
        current_spikes_proven_noise_only=False,speed_highpass_is_proven_sensor_noise=False,
        occurrence_rate_generalizable=False,
        note='Five fixed192ms steady windows only. Median21 residual contains possible real dynamics. '
             '100 software seeds do not create100 independent physical recordings.')
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (folder/'window_reports.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch',type=Path)
    print(json.dumps(export(p.parse_args().batch),indent=2))

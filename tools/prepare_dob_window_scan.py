"""Files-only preparation of a Simulink window scan using the MCU classifier.
Only generated copies change; firmware and frozen real/simulation data stay put.
"""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import struct
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'simulation/dob_simulink/trend_scan_results/20261024_122413'
OUT=ROOT/'simulation/dob_simulink/window_scan_work'
WINDOWS=(100,75,50,30)
COLS=('time_s','dob_estimate_a','dob_valid','lpf_updated','observer_source_us',
      'simulation_guard_fault','target_rpm','load_ground_truth_a')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def prepare():
    OUT.mkdir(exist_ok=True);generated=OUT/'generated';generated.mkdir(exist_ok=True)
    frozen=ROOT/'simulation/dob_simulink/window_scan_results/20261024_154439/firmware_sources'
    source_dir=frozen if frozen.is_dir() else ROOT/'firmware_common'
    c=source_dir/'dob_trend_shadow.c';h=source_dir/'dob_trend_shadow.h'
    header=h.read_text();assert header.count('#define DTS_WINDOW 100U')==1
    header=header.replace('#define DTS_WINDOW 100U','#define DTS_WINDOW DOB_WINDOW_POINTS')
    # MATLAB's MSVC C mode lacks the C11 spelling; retain compile-time checks.
    header='''/* Offline MSVC adapter; compile-time assertions remain active. */
#if defined(_MSC_VER)
#define DOB_WA_JOIN_(a,b) a##b
#define DOB_WA_JOIN(a,b) DOB_WA_JOIN_(a,b)
#define _Static_assert(c,msg) typedef char DOB_WA_JOIN(DobWindowAssert,__LINE__)[(c)?1:-1]
#endif
'''+header
    source=c.read_text()
    replacements={'span<60000U':'span<DOB_WINDOW_MIN_SPAN_US','n<60U':'n<DOB_WINDOW_MIN_GOOD',
                  '(float)n*.01f':'(float)n*(1.f/(float)DTS_WINDOW)'}
    for old,new in replacements.items():
        assert source.count(old)==1,(old,source.count(old));source=source.replace(old,new)
    (generated/'dob_trend_shadow.h').write_text(header)
    (generated/'dob_trend_shadow.c').write_text(source)
    config=json.loads((SOURCE/'config.json').read_text());runs=[]
    for name in config['classification']['scenarios']:
        for seed in config['scan']['seeds']:
            file=SOURCE/f'{name}_seed{seed:03d}.csv.gz';dest=OUT/f'{name}_seed{seed:03d}.input.bin'
            count=0
            with gzip.open(file,'rt',newline='') as f,dest.open('wb') as out:
                for row in csv.DictReader(f):
                    values=[float(row[k]) for k in COLS]
                    assert abs(values[0]-count*.001)<1e-9 and values[5]==0
                    out.write(struct.pack('<8d',*values));count+=1
            assert count==7001
            runs.append(dict(scenario=name,seed=seed,rows=count,input=str(dest),input_sha256=sha(dest),
                original=str(file),original_sha256=sha(file)))
    manifest=dict(windows_ms=list(WINDOWS),min_good=[60,45,30,18],min_span_ms=[60,45,30,18],
        trend_tau_ms=100,trend_dwell_ms=80,level_dwell_ms=30,
        coverage_ratio=.6,repeats=10,eval_s=[2.3,6.9],event_s=config['base']['event_s'],
        unload_s=config['base']['unload_s'],event_match_max_s=.8,input_columns=COLS,
        original_c=str(c),original_c_sha256=sha(c),original_h=str(h),original_h_sha256=sha(h),
        generated_c_sha256=sha(generated/'dob_trend_shadow.c'),generated_h_sha256=sha(generated/'dob_trend_shadow.h'),
        modifications=replacements,runs=runs,hardware_access=False,
        data_semantics='1 ms software logs, including measured-noise/physical-current hypotheses. Not full-rate replay of recent 60 ms board telemetry. Upstream DOB and its original warmup are frozen; isolates downstream classifier window only.')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('PREPARED',len(runs),'paired traces x',len(WINDOWS),'windows; no firmware changes')
    return manifest
if __name__=='__main__':prepare()

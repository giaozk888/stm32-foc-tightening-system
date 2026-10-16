"""Offline completion of saved PWM evidence; never accesses hardware."""
import json
from switch_trend_pwm_capture import OUTPUT, OFF_EVIDENCE, common_reference, zero_reference
from switch_trend_off_capture import require_trend
from switch_feedback_acceptance import require_switch
from switch_feedback_off_capture import analyze
from zero_retest_deploy import require_confirmed

def main():
    capture_path=OUTPUT/'pwm-1791880594613936800.json'
    inspect_path=OUTPUT/'inspect-1791880697603124600.json'
    capture=json.loads(capture_path.read_text('utf-8'))
    inspect=json.loads(inspect_path.read_text('utf-8'))
    off=json.loads(OFF_EVIDENCE.read_text('utf-8'))
    row=require_switch(capture['capture_line'],mode=2,complete=True)
    final=require_switch(inspect['uart']['SWITCH STATUS'],mode=2,complete=True)
    if row!=final or int(row['DONE'])&22!=22 or row['WAVE']!='0':
        raise RuntimeError('Saved capture and final read-only proof differ')
    fw=require_confirmed(inspect['uart']['FW STATUS'],'B')
    if fw.get('GEN')!='446' or capture['final_outputs']!=inspect['outputs']:
        raise RuntimeError('Final identity/output proof mismatch')
    original_zero_line=next(line for line in capture['uart'] if ' OK ZERO PROFILE=' in line)
    zero=zero_reference(original_zero_line)
    if tuple(map(int,row['ZERO'].split(',')))!=zero or zero_reference(inspect['uart']['ZERO STATUS'])!=zero:
        raise RuntimeError('Existing calibrated reference changed')
    analysis=analyze(capture['samples'],row)
    analysis['nominal_reference_not_published_calibration']=False
    trend=require_trend(capture['trend_line'],capture['samples'])
    analyze(off['samples'],off['capture'])
    report=dict(acquisition_and_replay_pass=True,host_original_failed_on='U0/V0 digit-suffix parsing',
                original_evidence_preserved=True,no_repeat=True,hardware_access=False,
                capture_evidence=str(capture_path),final_inspection=str(inspect_path),
                final_outputs=inspect['outputs'],final_fw=fw,analysis=analysis,trend=trend,
                comparison=dict(reference=list(zero),off=common_reference(off['samples'],zero),
                                pwm=common_reference(capture['samples'],zero)),
                bridge_tested=False,motor_tested=False,physical_six_waveforms_verified=False,
                raw_zero_qualified=capture['before_filter']['RAW_STATE']=='3')
    target=OUTPUT/'pwm-1791880594613936800-analysis.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Derived analysis: '+str(target))

if __name__=='__main__': main()

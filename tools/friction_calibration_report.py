"""Offline calibration of effective running friction, amperes (never writes firmware)."""
import argparse
import json
import math
from pathlib import Path

POINTS=(40,80,120,240,-40,-80,-120,-240)


def plan():
    return dict(speeds_rpm=POINTS,passes=3,friction_enabled=False,
        drive_seconds_per_point=5,stop_deadline_seconds=7,
        board_lease_seconds_unchanged=12,iq_limit_a_unchanged=.5,
        overspeed_rpm_unchanged=300,automatic_current_increase=False,
        stop_on_protection=True,automatic_retry=False,
        continue_on_expected_no_rotation=True,continue_on_unqualified_plateau=True,
        qualification='Running friction only; no breakaway or calibrated Nm measurement')


def point(s):
    duration=s['valid_s']
    if not s.get('passed') or not math.isfinite(duration) or duration<2:
        raise ValueError('Point lacks qualified steady-state coverage')
    keys=('iq_sum','iq_ref_sum','id_sum','abs_id_sum','speed_sum','iq_sq_sum','speed_error_sum')
    if not all(math.isfinite(s[k]) for k in keys): raise ValueError('Nonfinite evidence')
    result=dict(rpm=s['rpm'],samples=s['valid'],valid_s=duration,
        mean_iq_a=s['iq_sum']/duration,mean_iq_ref_a=s['iq_ref_sum']/duration,
        mean_id_a=s['id_sum']/duration,mean_abs_id_a=s['abs_id_sum']/duration,
        mean_speed_rpm=s['speed_sum']/duration,speed_mae_rpm=s['speed_error_sum']/duration,
        iq_std_a=math.sqrt(max(0,s['iq_sq_sum']/duration-(s['iq_sum']/duration)**2)),
        reject=s['reject'],net_travel_deg=s['net_travel'],total_abs_travel_deg=s['abs_travel'])
    # Evidence quality flags, NOT motor-trip thresholds. Do not silently
    # suppress high Id or poor Iq tracking to manufacture a friction fit.
    result['quality_flags']=[]
    if abs(result['mean_iq_a']-result['mean_iq_ref_a'])>.05:
        result['quality_flags'].append('IQ_TRACKING_UNCERTAIN')
    if result['mean_abs_id_a']>max(.05,.5*abs(result['mean_iq_a'])):
        result['quality_flags'].append('ID_NOT_SMALL')
    if result['iq_std_a']>max(.05,.5*abs(result['mean_iq_a'])):
        result['quality_flags'].append('CURRENT_FEEDBACK_NOISY')
    if result['mean_speed_rpm']*result['rpm']<=0:
        result['quality_flags'].append('WRONG_MEAN_DIRECTION')
    return result


def solve3(a,b):
    m=[list(row)+[v] for row,v in zip(a,b)]
    for i in range(3):
        pivot=max(range(i,3),key=lambda k:abs(m[k][i]))
        m[i],m[pivot]=m[pivot],m[i]
        v=m[i][i]
        if abs(v)<1e-10: raise ValueError('Insufficient independent speeds/directions')
        m[i]=[x/v for x in m[i]]
        for k in range(3):
            if k!=i:
                v=m[k][i];m[k]=[x-v*y for x,y in zip(m[k],m[i])]
    return [row[3] for row in m]


def report(stats,points_grid=None):
    invalid=[dict(rpm=s.get('rpm'),valid_s=s.get('valid_s'),reject=s.get('reject'),
                  reason='Request refused before motion' if s.get('not_admitted') else 'Plateau did not qualify')
             for s in stats if not s.get('passed')]
    points=[point(s) for s in stats if s.get('passed')]
    clean=[p for p in points if not p['quality_flags']]
    covered={p['rpm'] for p in clean}
    grid=tuple(points_grid) if points_grid is not None else POINTS
    complete=all(sum(p['rpm']==r for p in clean)>=3 for r in grid)
    output=dict(points=points,invalid_points=invalid,complete_repeated_grid=complete,fit=None,
        automatic_parameter_write=False,units='A and A/rpm, not calibrated Nm',
        breakaway_current=None,deadband_changed=False)
    matched={abs(r) for r in covered if -r in covered}
    if len(matched)<2:
        output['reason']='Missing clean signed speed points; do not guess I_FRIC'
        return output
    a=[[0.]*3 for _ in range(3)];b=[0.]*3
    for p in clean:
        measured=p['mean_speed_rpm']
        x=[1.,math.copysign(1,measured),measured];y=p['mean_iq_a']
        for i in range(3):
            b[i]+=x[i]*y
            for j in range(3): a[i][j]+=x[i]*x[j]
    offset,coulomb,viscous=solve3(a,b)
    residuals=[p['mean_iq_a']-(offset+coulomb*math.copysign(1,p['mean_speed_rpm'])+
        viscous*p['mean_speed_rpm']) for p in clean]
    output['fit']=dict(bias_a=offset,coulomb_a=coulomb,viscous_a_per_rpm=viscous,
        positive_zero_speed_intercept_a=offset+coulomb,
        negative_zero_speed_magnitude_intercept_a=coulomb-offset,
        clean_point_count=len(clean),matched_speed_magnitudes_rpm=sorted(matched),
        speed_basis='measured steady-state mean rpm, not requested command',
        residual_rms_a=math.sqrt(sum(x*x for x in residuals)/len(residuals)),
        physical_signs_plausible=coulomb>=0 and viscous>=0,
        qualification='Effective current-based unloaded model; direction asymmetry/bias and current scaling still require review')
    if not complete: output['reason']='Incomplete grid: fit uses only clean measured points; inspect coverage/repeats and extrapolation uncertainty'
    return output


def admitted_window_sensitivity(stats,points_grid=None):
    """Exploratory only: keep formal PASS flags immutable.

    A complete >=2s aggregate can exist even when total settling/reject rate
    made the original point FAIL. Show a SEPARATE model using those admitted
    samples to expose dependence on that global quality gate; never label this
    accepted calibration, change a threshold or write a controller parameter.
    """
    candidates=[];included_failed=[]
    for index,s in enumerate(stats):
        if not math.isfinite(s.get('valid_s',0)) or s.get('valid_s',0)<2:continue
        candidate=dict(s);candidate['passed']=1
        if point(candidate)['quality_flags']:continue
        candidates.append(candidate)
        if not s.get('passed'):included_failed.append(dict(index=index,rpm=s['rpm'],
            valid_s=s['valid_s'],reject=s['reject']))
    output=report(candidates,points_grid)
    output.update(calibration_accepted=False,original_failed_points_included=included_failed,
        qualification='EXPLORATORY sensitivity only; admitted windows from globally rejected points may be included, not accepted I_FRIC')
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',nargs='?',type=Path)
    args=p.parse_args()
    data=json.loads(args.receipt.read_text('utf-8')) if args.receipt else None
    print(json.dumps(report(data['calibration_points'],data.get('plan',{}).get('speeds_rpm')) if data else plan(),indent=2))

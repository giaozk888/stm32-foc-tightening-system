"""FILES ONLY: pair signed mechanical captures, separate friction/bias, prepare DOB.

No residual selection, sign repair, invented Kt, device access or parameter write.
Direction intercepts use SIGNED Iq/omega/alpha in BOTH directions.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import mechanical_identification_report as original

MAX_DIRECTION_REL_DIFF=.30  # Analysis qualification, never a protection threshold.
DOB_SHADOW_BANDWIDTH_RAD_S=2*math.pi*2  # 2 Hz candidate, OBSERVE ONLY.
SPEEDS=(600,600,600,700,700,700,800,800,800)


def signed_three_term(points):
    """Independent weighted QR fit: Iq=a*alpha+b*omega+c. No abs/sign flip."""
    if len(points)<3:raise ValueError('INSUFFICIENT_WINDOWS')
    x=[[p['alpha'],p['omega'],1.] for p in points]
    columns=[[math.sqrt(p['dt_s'])*row[j] for p,row in zip(points,x)] for j in range(3)]
    y=[math.sqrt(p['dt_s'])*p['iq'] for p in points]
    q=[];r=[[0.]*3 for _ in range(3)]
    for j in range(3):
        v=columns[j][:]
        for i in range(j):
            r[i][j]=sum(a*b for a,b in zip(q[i],v))
            v=[a-r[i][j]*b for a,b in zip(v,q[i])]
        r[j][j]=math.sqrt(sum(a*a for a in v))
        if r[j][j]<1e-10*max(1.,math.sqrt(sum(a*a for a in columns[j]))):
            raise ValueError('RANK_DEFICIENT')
        q.append([a/r[j][j] for a in v])
    z=[sum(a*b for a,b in zip(v,y)) for v in q];c=[0.]*3
    for j in range(2,-1,-1):c[j]=(z[j]-sum(r[j][k]*c[k] for k in range(j+1,3)))/r[j][j]
    sw=sum(p['dt_s'] for p in points)
    mean=sum(p['dt_s']*p['iq'] for p in points)/sw
    sse=sum(p['dt_s']*(p['iq']-sum(a*b for a,b in zip(c,row)))**2 for p,row in zip(points,x))
    sst=sum(p['dt_s']*(p['iq']-mean)**2 for p in points)
    return dict(j_over_kt=c[0],b_over_kt=c[1],intercept_a=c[2],
        r2=1-sse/sst if sst>1e-20 else 0.,residual_rms_a=math.sqrt(sse/sw))


def direction_fit(rows,sign,group=1):
    points,rejected=original.windows(rows,group)
    points=[p for p in points if p['direction']==sign]
    result=dict(n=len(points),rejected_n=len(rejected),group=group,sign=sign,
        problems=[],qualified=False)
    if len(points)<40:result['problems'].append('INSUFFICIENT_WINDOWS');return result
    if statistics.pstdev(p['alpha'] for p in points)<5:result['problems'].append('INSUFFICIENT_ACCELERATION_EXCITATION')
    if statistics.pstdev(p['omega'] for p in points)<2:result['problems'].append('INSUFFICIENT_SPEED_EXCITATION')
    try:result.update(signed_three_term(points))
    except ValueError as e:result['problems'].append(str(e));return result
    if result['j_over_kt']<=0 or result['b_over_kt']<0:result['problems'].append('NONPHYSICAL_COEFFICIENT')
    if result['r2']<.7 or result['residual_rms_a']>.03:result['problems'].append('POOR_MODEL_FIT')
    result['qualified']=not result['problems'];return result


def report(captures):
    rows=[row for c in captures for row in c['rows']]
    pos=direction_fit(rows,1);neg=direction_fit(rows,-1)
    joint=original.report(captures)
    problems=list(joint['problems']);asymmetry={};separation=None
    for label,side in (('POSITIVE',pos),('NEGATIVE',neg)):
        if not side['qualified']:problems.append(label+'_FIT_FAILED')
    if pos['qualified'] and neg['qualified']:
        for key in ('j_over_kt','b_over_kt'):
            fraction=abs(pos[key]-neg[key])/max(abs(pos[key]),abs(neg[key]),1e-12)
            asymmetry[key]=100*fraction
            if fraction>MAX_DIRECTION_REL_DIFF:problems.append('DIRECTION_ASYMMETRY_'+key.upper())
        separation=dict(c_plus_a=pos['intercept_a'],c_minus_a=neg['intercept_a'],
            coulomb_equivalent_a=(pos['intercept_a']-neg['intercept_a'])/2,
            current_bias_a=(pos['intercept_a']+neg['intercept_a'])/2,
            caveat='Independent directional fits are diagnostic; shared-model joint fit defines the final candidate.')
        if separation['coulomb_equivalent_a']<0:problems.append('NEGATIVE_COULOMB_EQUIVALENT')
    for sign in (-1,1):
        sessions={r['session'] for r in rows if r['omega_mean_rad_s']*sign>original.MIN_SPEED_RAD_S}
        if len(sessions)<3:problems.append('THREE_INDEPENDENT_SESSIONS_PER_DIRECTION_REQUIRED')
    if any(c.get('expected_sign') in (-1,1) and any(
        p['direction']!=c['expected_sign'] for p in original.windows(c['rows'],1)[0]) for c in captures):
        problems.append('MEASURED_DIRECTION_DISAGREES_WITH_COMMAND')
    problems=sorted(set(problems));qualified=not problems
    model=None
    if qualified:
        p=joint['primary']
        model=dict(j_over_kt=p['j_over_kt'],b_over_kt=p['b_over_kt'],
            coulomb_over_kt=p['coulomb_over_kt'],bias_a=p['bias_a'],
            bandwidth_rad_s=DOB_SHADOW_BANDWIDTH_RAD_S,
            min_speed_rad_s=original.MIN_SPEED_RAD_S,qualified=1)
    return dict(positive=pos,negative=neg,directional_separation=separation,
        direction_difference_percent=asymmetry,joint=joint,problems=problems,
        normalized_bidirectional_qualified=qualified,candidate_dob_shadow_model=model,
        formulas=dict(model='Iq = J/Kt*alpha + B/Kt*omega + Ic*sign(omega) + bias',
            c_plus='Ic+bias',c_minus='-Ic+bias',Ic='(c_plus-c_minus)/2',bias='(c_plus+c_minus)/2',
            dob='Q(s)[Iq - B/Kt*omega - Ic*sign(omega) - bias] - J/Kt*s*Q(s)*omega'),
        units=dict(omega='mechanical rad/s',alpha='mechanical rad/s^2',current='dq A',disturbance='A equivalent'),
        limitations='Symmetric Coulomb + constant current-bias assumption. Direction-dependent mechanical load can mimic bias; no independent electrical bias or Nm calibration is claimed.',
        absolute_parameters=None,kt_independently_identified=False,
        parameter_writes=False,dob_control_enabled=False)


def load_batch(path,elf,sign):
    batch=json.loads(path.read_text())
    expected=[sign*rpm for rpm in SPEEDS]
    if (not batch.get('pass_') or batch.get('speeds_rpm')!=expected or len(batch.get('runs',[]))!=9 or
        len(set(batch['runs']))!=9 or batch.get('automatic_parameter_write') is not False or
        batch.get('dob_control_enabled') is not False):raise ValueError('Exact completed nine-point signed batch required')
    captures=[];contexts=[]
    for receipt,rpm in zip(batch['runs'],expected):
        r=json.loads(Path(receipt).read_text())
        if r.get('rpm')!=rpm or not r.get('pass_'):raise ValueError('Signed point not completed')
        c=original.decode(Path(receipt),elf)
        if not c['board_verified']:raise ValueError('Independent board safety/provenance failed')
        c['expected_sign']=sign;captures.append(c)
        contexts.append((r.get('ka_a_per_rpm_s'),r.get('psi_f_wb'),r.get('friction_enabled'),
            r.get('overspeed_trip_rpm'),r.get('travel_limit_deg'),
            tuple(sorted(r.get('motion_limits',{}).items()))))
    if len({c['session_hash'] for c in captures})!=9:raise ValueError('Duplicate RAM sessions')
    if len(set(contexts))!=1:raise ValueError('Within-batch control configuration mismatch')
    return captures,contexts[0]


def matching_profiles(positive_elf,negative_elf):
    def flags(elf):
        commands=json.loads((elf.parent/'compile_commands.json').read_text())
        command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
        return set(re.findall(r'(?:^| )-D(\S+)',command))
    a=flags(positive_elf);b=flags(negative_elf)
    reverse='FOC_MECHANICAL_REVERSE_IDENT_DIAG=1'
    if reverse in a or reverse not in b or a!=b-{reverse}:
        raise ValueError('Paired compiled profiles may differ ONLY in reverse-command whitelist')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--positive-batch',type=Path,required=True);p.add_argument('--positive-elf',type=Path,required=True)
    p.add_argument('--negative-batch',type=Path,required=True);p.add_argument('--negative-elf',type=Path,required=True)
    a=p.parse_args(argv)
    matching_profiles(a.positive_elf,a.negative_elf)
    positive,pc=load_batch(a.positive_batch,a.positive_elf,1)
    negative,nc=load_batch(a.negative_batch,a.negative_elf,-1)
    if pc!=nc:raise ValueError('Positive/negative control configuration mismatch')
    if len({c['session_hash'] for c in positive+negative})!=18:raise ValueError('Duplicate cross-batch RAM')
    print(json.dumps(report(positive+negative),indent=2,allow_nan=False))


if __name__=='__main__':main()

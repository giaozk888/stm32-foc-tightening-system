"""Offline-only locked-rotor candidate estimator. Never opens a device/writes PI.

Input: {runs:[{mode:'RS'/'LD'/'LQ', status:3, fault:0, rows:[...]}]}.
Float binary rows use motor_identification.h names, us relative to admission.
L fitting also requires explicit independently checked PWM latch evidence; a
current-loop closed-loop rise time is NEVER treated as the motor time constant.
"""
import argparse
import json
import math
import statistics as st
import re


class Insufficient(ValueError):
    pass


def decode_uart(text,mode):
    """Decode ONE stopped run, no transport. Scalar logs use uA/uV/urad/mrpm."""
    if mode not in ('RS','LD','LQ'):raise ValueError('Explicit mode required')
    rows={};status=None;geometry=None;reject_stats=None;first_reject=None;rs_gaps=None
    for line in text.splitlines():
        if ' OK IDENT MODE=' in ' '+line:
            f={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
            if f.get('STATUS',0)>=3:
                if status and status!=f:raise Insufficient('Conflicting final snapshots')
                status=f
        if ' OK MID ARR=' in ' '+line:
            geometry={k:int(v) for k,v in re.findall(r'\b([A-Z0-9_]+)=(-?\d+)',line)}
        if ' OK MID REJECT=' in ' '+line:
            reject_stats={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
        if ' OK MID RS_GAPS=' in ' '+line:
            rs_gaps={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
        if ' OK MID FIRST_US=' in ' '+line:
            first_reject={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
        if ' OK MID K=' not in ' '+line:continue
        f={k:int(v) for k,v in re.findall(r'\b([A-Z_]+)=(-?\d+)',line)}
        row=dict(us=f['US'],seq=f['SEQ'],pending_before=f['PSEQ'],mode=f['M'],
            status=f['S'],reason=f['F'])
        row.update({name:f[key]*scale for key,name,scale in (
            ('DR','id_ref',1e-6),('QR','iq_ref',1e-6),('D','id',1e-6),('Q','iq',1e-6),
            ('VD','vd',1e-6),('VQ','vq',1e-6),('A','angle',1e-6),('RPM','speed',1e-3))})
        if f['K'] in rows and rows[f['K']]!=row:raise Insufficient('Mixed trace row')
        rows[f['K']]=row
    expected={'RS':1,'LD':2,'LQ':3}[mode]
    if (not status or status.get('MODE')!=expected or status.get('N')!=len(rows) or
        sorted(rows)!=list(range(len(rows)))):
        raise Insufficient('Complete matching frozen STATUS/ROW set required')
    return dict(mode=mode,status=status['STATUS'],fault=status['REASON'],
        rows=[rows[k] for k in sorted(rows)],geometry=geometry,
        current_admission=reject_stats,first_current_reject=first_reject,rs_gap_admission=rs_gaps,
        latch_evidence={'verified':False},source='UART scaled diagnostic; not physical voltage metrology')


def guard(run):
    rows=run.get('rows',[])
    if run.get('status')!=3 or run.get('fault')!=0 or len(rows)<16:
        raise Insufficient('Completed fault-free locked-rotor capture required')
    proof=run.get('protection_evidence',{})
    if (proof.get('verified') is not True or not proof.get('source') or
        any(proof.get(k)!=0 for k in ('fault','deadline_miss','ccr_late'))):
        raise Insufficient('Same-session original protection/timing evidence required')
    l_adapted=(run.get('mode') in ('LD','LQ') and
               run.get('admission_policy')=='L_RS_ADMISSION_V1' and
               run.get('time_policy',{}).get('L_RS_ADMISSION')=='1' and
               run.get('time_policy',{}).get('L_DT_MAX')=='100')
    admission=run.get('current_admission')
    if admission:
        if admission.get('TOTAL_STOP',1)==0:
            # Explicit Rs candidate policy, not a global bypass for old/L data.
            reject=admission.get('REJECT',-1);good=admission.get('GOOD',-1)
            max_run=admission.get('MAX_RUN',-1)
            run_only=admission.get('RUN_STOP',1)==0
            if ((run.get('mode')!='RS' and not l_adapted) or admission.get('REJECT_MAX')!=0 or
                admission.get('RUN_STOP',1) not in (0,1) or
                admission.get('RUN_LIMIT')!=(0 if run_only else 3) or not isinstance(reject,int) or reject<0 or
                not isinstance(good,int) or good<len(rows) or len(rows)!=32 or
                not isinstance(max_run,int) or not 0<=max_run<=(255 if run_only else 2) or max_run>reject or
                (reject==0)!=(max_run==0)):
                raise Insufficient('Invalid Rs reject-only policy or insufficient accepted samples')
            start,end,spacing,ceiling=(99800,104000,45,2080) if l_adapted else (200000,400000,6250,8000)
            if run_only and (admission.get('RUN_SAT')!=255 or reject+good>ceiling or
                    any(not start<=r['us']<end for r in rows) or
                    any(b['us']-a['us']<spacing for a,b in zip(rows,rows[1:]))):
                raise Insufficient('Explicit saturated-run statistics and full settled Rs window required')
        elif (admission.get('TOTAL_STOP',1)!=1 or admission.get('REJECT_MAX')!=16 or
              admission.get('RUN_LIMIT')!=3 or not 0<=admission.get('REJECT',-1)<=16 or
              not 0<=admission.get('MAX_RUN',-1)<3):
            raise Insufficient('Current reject budget/continuous envelope exceeded')
    gaps=run.get('rs_gap_admission')
    if gaps is not None:
        count_only=gaps.get('TOTAL_STOP',1)==0
        # No old/L capture may silently adopt the new Rs-only policy. A full
        # 32-row settled window and unchanged 400ms lease are still required.
        limit=(2080 if l_adapted else 8000) if count_only else 16
        if ((run.get('mode')!='RS' and not l_adapted) or gaps.get('BUDGET')!=(0 if count_only else 16) or
            gaps.get('TOTAL_STOP',1) not in (0,1) or gaps.get('RUN_LIMIT')!=2 or
            not 0<=gaps.get('RS_GAPS',-1)<=gaps.get('SKIPPED',-1)<=limit or
            not 0<=gaps.get('MAX_GAP',-1)<=2 or
            (gaps['RS_GAPS']==0)!=(gaps['SKIPPED']==0) or
            not gaps['RS_GAPS']<=gaps['SKIPPED']<=2*gaps['RS_GAPS'] or
            (gaps['SKIPPED']==0)!=(gaps['MAX_GAP']==0)):
            raise Insufficient('Invalid Rs-only held-pair gap budget/metadata')
        start,end,spacing=(99800,104000,45) if l_adapted else (200000,400000,6250)
        if count_only and (len(rows)!=32 or any(not start<=r['us']<end for r in rows) or
                any(b['us']-a['us']<spacing for a,b in zip(rows,rows[1:]))):
            raise Insufficient('Full bounded settled Rs window required for count-only gaps')
    for r in rows:
        if any(not math.isfinite(r[k]) for k in ('id_ref','iq_ref','id','iq','vd','vq','angle','speed','us')):
            raise Insufficient('Nonfinite sample')
        if abs(r['speed'])>2 or max(abs(r['id']),abs(r['iq']))>.20 or math.hypot(r['vd'],r['vq'])>.200001:
            raise Insufficient('Diagnostic motion/current/voltage bound exceeded')
    angles=[r['angle'] for r in rows]
    # Circular distance against first row, not raw wrap discontinuity.
    if max(abs(math.remainder(x-angles[0],2*math.pi)) for x in angles) > math.radians(1):
        raise Insufficient('Electrical angle moved more than 1 degree')
    if any(b['us']<=a['us'] or b['seq']<=a['seq'] for a,b in zip(rows,rows[1:])):
        raise Insufficient('Nonmonotonic samples')
    return rows


def qualify_rs_point(run):
    """Original single-point gates, shared by fit and batch quality labels."""
    rows=guard(run)
    if run['mode']!='RS':raise Insufficient('Wrong Rs capture mode')
    i=st.mean(r['id'] for r in rows);v=st.mean(r['vd'] for r in rows)
    ref=st.mean(r['id_ref'] for r in rows)
    if (min(r['us'] for r in rows)<200000 or max(abs(r['iq_ref']) for r in rows)>1e-8 or
        abs(i-ref)>max(.015,.2*abs(ref)) or st.pstdev(r['id'] for r in rows)>.025 or
        abs(st.mean(r['iq'] for r in rows))>.02):
        raise Insufficient('Rs settling/tracking/cross-axis/noise gate')
    n=len(rows)//4
    if abs(st.mean(r['id'] for r in rows[-n:])-st.mean(r['id'] for r in rows[:n]))>.01:
        raise Insufficient('Rs current not settled')
    return dict(id_a=i,vd_v=v,ratio_ohm=v/i if i else None,
        requested_a=ref,n=len(rows),v_sem=st.pstdev(r['vd'] for r in rows)/math.sqrt(len(rows)))


def fit_rs(runs):
    points=[qualify_rs_point(run) for run in runs]
    if len(points)<3 or len({round(p['requested_a'],4) for p in points})<3:
        raise Insufficient('At least three independently confirmed current points required')
    x=[p['id_a'] for p in points];y=[p['vd_v'] for p in points]
    if max(x)-min(x)<.025:raise Insufficient('Insufficient current span')
    mx,my=st.mean(x),st.mean(y)
    sxx=sum((v-mx)**2 for v in x)
    rs=sum((a-mx)*(b-my) for a,b in zip(x,y))/sxx
    bias=my-rs*mx
    residual=sum((b-(rs*a+bias))**2 for a,b in zip(x,y))
    syy=sum((v-my)**2 for v in y)
    r2=1-residual/syy if syy else 0
    if rs<=0 or r2<.9 or max(y)-min(y)<max(.001,4*max(p['v_sem'] for p in points)):
        raise Insufficient('Rs slope/noise/fit quality inadequate')
    return dict(rs_ohm=rs,voltage_bias_v=bias,r_squared=r2,points=points,
        qualification='Command-voltage effective phase/Y-equivalent candidate; not Kelvin winding resistance')


def fit_l(run,rs):
    rows=guard(run)
    if run['mode'] not in ('LD','LQ') or rs<=0:raise Insufficient('Valid Rs then LD/LQ required')
    evidence=run.get('latch_evidence',{})
    fraction=evidence.get('sample_to_bottom_fraction')
    if (evidence.get('verified') is not True or evidence.get('command_lag_cycles')!=2 or
        not isinstance(fraction,(int,float)) or not 0<fraction<1 or
        not evidence.get('source') or evidence.get('late_count')!=0):
        raise Insufficient('TIMING_UNQUALIFIED: independently verify sample/bottom/latch alignment; no guessed lag')
    axis='d' if run['mode']=='LD' else 'q'
    current='i'+axis;voltage='v'+axis
    if len(rows)!=32:raise Insufficient('Full consecutive 32-pair transient required')
    if any(b['seq']!=a['seq']+1 or not 45<=b['us']-a['us']<=55 for a,b in zip(rows,rows[1:])):
        raise Insufficient('Held/rejected/missing pair; do not interpolate')
    if any(r['pending_before']!=r['seq']-1 for r in rows):
        raise Insufficient('Pending-source pipeline chain not consecutive')
    other='iq' if axis=='d' else 'id'
    if any(abs(r[other+'_ref'])>1e-8 for r in rows):raise Insufficient('Wrong axis reference')
    span=max(r[current] for r in rows)-min(r[current] for r in rows)
    if span<.015 or abs(st.mean(r[other] for r in rows))>.02:
        raise Insufficient('Transient amplitude or cross-axis quality inadequate')
    # Existing pipeline commits cmd[k-1] AFTER ADC[k], latches at following
    # bottom. Interval ADC[k]..ADC[k+1]: cmd[k-2] for f*dt, cmd[k-1] thereafter.
    # f must come from qualified physical sample aperture/bottom evidence.
    pairs=[]
    for k in range(2,len(rows)-1):
        dt=(rows[k+1]['us']-rows[k]['us'])*1e-6
        pairs.append((rows[k][current],rows[k+1][current],
            rows[k-2][voltage],rows[k-1][voltage],dt))
    dt=st.mean(p[-1] for p in pairs)
    lo=3*dt;hi=(rows[-1]['us']-rows[0]['us'])*1e-6/2
    if hi<=lo:raise Insufficient('Insufficient transient time span')
    def evaluate(tau):
        terms=[]
        for i,j,old,new,dt in pairs:
            a=math.exp(-dt/tau);b=math.exp(-(1-fraction)*dt/tau)
            predicted=a*i+(b-a)*old/rs+(1-b)*new/rs
            terms.append((j-predicted,(1-a)/rs))
        bias=sum(y*x for y,x in terms)/sum(x*x for _,x in terms)
        mse=st.mean((y-bias*x)**2 for y,x in terms)
        return mse,bias
    grid=[lo*(hi/lo)**(k/319) for k in range(320)]
    errors=[evaluate(t) for t in grid];best=min(range(len(grid)),key=lambda k:errors[k][0])
    tau=grid[best];mse,bias=errors[best]
    if best<3 or best>316 or math.sqrt(mse)>min(.005,.15*span):
        raise Insufficient('Unresolved tau boundary or noisy/model-inconsistent transient')
    # A flat error profile cannot identify L even when a numeric minimizer exists.
    alternatives=[evaluate(tau*.75)[0],evaluate(tau*1.25)[0]]
    if min(alternatives)<max(mse*1.2,1e-10):
        raise Insufficient('Time constant not identifiable above noise')
    return dict(tau_s=tau,inductance_h=tau*rs,current_prediction_rms_a=math.sqrt(mse),
        fitted_voltage_bias_v=bias,samples=len(rows),axis=axis,
        qualification='RL fit to delayed actual controller voltage waveform, NOT closed-loop rise-time tau')


def report(data,wc):
    if not math.isfinite(wc) or wc<=0:raise ValueError('wc must be positive rad/s')
    result=dict(candidate_only=True,automatic_pi_write=False,rs=None,ld=None,lq=None,
        errors={},pi_suggestion=None,wc_rad_s=wc)
    runs=data.get('runs',[])
    try:result['rs']=fit_rs([r for r in runs if r['mode']=='RS'])
    except (Insufficient,KeyError,ValueError) as e:result['errors']['rs']=str(e)
    for mode,key in (('LD','ld'),('LQ','lq')):
        group=[r for r in runs if r['mode']==mode]
        if not result['rs']:result['errors'][key]='Rs not qualified';continue
        if len(group)!=1:result['errors'][key]='Exactly one manually confirmed capture required';continue
        try:result[key]=fit_l(group[0],result['rs']['rs_ohm'])
        except (Insufficient,KeyError,ValueError) as e:result['errors'][key]=str(e)
    if all(result[k] for k in ('rs','ld','lq')):
        result['pi_suggestion']=dict(kp_d=result['ld']['inductance_h']*wc,
            ki_d=result['rs']['rs_ohm']*wc,kp_q=result['lq']['inductance_h']*wc,
            ki_q=result['rs']['rs_ohm']*wc,
            ki_units='V/(A*s); verify discrete Ts convention before manual use')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=__import__('pathlib').Path)
    p.add_argument('--wc-rad-s',type=float)
    p.add_argument('--decode-mode',choices=('RS','LD','LQ'),help='One stopped UART capture -> one JSON run')
    a=p.parse_args()
    if a.decode_mode:out=decode_uart(a.capture.read_text('utf-8'),a.decode_mode)
    else:
        if a.wc_rad_s is None:p.error('--wc-rad-s required for candidate estimates')
        out=report(json.loads(a.capture.read_text('utf-8')),a.wc_rad_s)
    print(json.dumps(out,indent=2))


if __name__=='__main__':main()

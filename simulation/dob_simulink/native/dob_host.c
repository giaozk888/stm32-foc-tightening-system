/* Offline SPEED-mode orchestration of existing C primitives; never linked to
 * firmware. No hardware APIs. See AUDIT_AND_DESIGN.md for abstraction limits. */
#include <string.h>
#include <math.h>
#include "dob_host.h"
#include "mechanical_dob_monitor.h"
#include "dob_feedback_candidate.h"
#include "speed_scurve.h"
#include "speed_bumpless.h"
#include "dob_contact20_observe10.h"

float dob_host_gain=.25f;
static MechanicalDobMonitor monitor;
static DobFeedbackCandidate feedback;
static SpeedScurve trajectory;
static float integral,speed_lpf,cap_a,travel;
static unsigned resets,epoch_resets,reset_reason,fault,have_speed;
static double last_time=-1,cached[DOB_NY];
typedef struct {
    MechanicalDobMonitor monitor;
    DobCurrentAdmission admission;
    DobFeedbackCandidate feedback;
    SpeedScurve trajectory;
    float integral,speed_lpf,cap_a,travel,gain;
    unsigned resets,epoch_resets,reset_reason,fault,have_speed;
    double last_time,cached[DOB_NY];
} OfflineSnapshot;
unsigned dob_host_state_size(void){return (unsigned)sizeof(OfflineSnapshot);}
void dob_host_save(void *buffer){
    OfflineSnapshot s={0};
    s.monitor=monitor;s.admission=dob_current_admission;s.feedback=feedback;s.trajectory=trajectory;
    s.integral=integral;s.speed_lpf=speed_lpf;s.cap_a=cap_a;s.travel=travel;s.gain=dob_host_gain;
    s.resets=resets;s.epoch_resets=epoch_resets;s.reset_reason=reset_reason;s.fault=fault;s.have_speed=have_speed;
    s.last_time=last_time;memcpy(s.cached,cached,sizeof cached);memcpy(buffer,&s,sizeof s);
}
void dob_host_restore(const void *buffer){
    OfflineSnapshot s;memcpy(&s,buffer,sizeof s);
    monitor=s.monitor;dob_current_admission=s.admission;feedback=s.feedback;trajectory=s.trajectory;
    integral=s.integral;speed_lpf=s.speed_lpf;cap_a=s.cap_a;travel=s.travel;dob_host_gain=s.gain;
    resets=s.resets;epoch_resets=s.epoch_resets;reset_reason=s.reset_reason;fault=s.fault;have_speed=s.have_speed;
    last_time=s.last_time;memcpy(cached,s.cached,sizeof cached);
}

/* Real reset hook supplied by mechanical_dob_shadow.h under the host-only
 * trace flag. Counts calls, not inferred changes of initialized/elapsed. */
void DobIdTrace_ResetEvent(uint32_t reason) {
    ++resets;++epoch_resets;reset_reason=reason;
}
void dob_host_configure(const double *config){
    feedback.enabled=(uint32_t)(config[0]!=0);dob_host_gain=(float)config[1];
    cap_a=fminf(.025f,fmaxf(0,(float)config[2]));
    if(!feedback.enabled)DobFeedback_Clear(&feedback);
}
void dob_host_reset(const double *config) {
    memset(&monitor,0,sizeof monitor);memset(&feedback,0,sizeof feedback);
    memset(&dob_current_admission,0,sizeof dob_current_admission);
    dob_host_configure(config);
    SpeedScurve_Reset(&trajectory,0);integral=0;speed_lpf=0;travel=0;
    resets=epoch_resets=reset_reason=fault=have_speed=0;last_time=-1;
    memset(cached,0,sizeof cached);
}
void dob_host_step(double time_s,const double *u,double *y) {
    /* Same discrete timestamp may be represented one double ULP differently
     * by CSV replay / Simulink. This is far below a microsecond timestamp. */
    if(last_time>=0&&fabs(time_s-last_time)<1e-10){memcpy(y,cached,sizeof cached);return;}
    const float dt=.001f,pi=3.14159265358979323846f;
    uint32_t now=(uint32_t)(time_s*1e6+.5)+100000U;
    epoch_resets=0;reset_reason=0;
    float raw_rpm=(float)(u[1]*60/(2*3.14159265358979323846)+u[3]);
    float iq=(float)(u[2]+u[4]),id=(float)u[5];
    if(!have_speed){speed_lpf=raw_rpm;have_speed=1;}
    else speed_lpf+=dt/(.020f+dt)*(raw_rpm-speed_lpf);
    travel+=fabsf((float)u[1])*dt*180/pi;
    if(!isfinite(raw_rpm)||!isfinite(iq)||!isfinite(id)||!isfinite(u[0]))fault=1;
    if(fabsf((float)u[1])*60/(2*pi)>300||travel>20000||time_s>12)fault=1;
    uint8_t running=(uint8_t)(u[9]!=0&&!fault);
    MechanicalDobMonitor_Lifecycle(&monitor,running,(uint8_t)fault);
    float comp=0;
    float ref=0,error=0,p=0,candidate=integral;uint8_t release=0;
    SpeedFrictionResult result={0};
    if(running){
        ref=SpeedScurve_Step(&trajectory,(float)u[0],dt);
        error=ref-speed_lpf;p=.003f*error;
        /* Mirrors reviewed SPEED branch: legacy bleed then original SB2.
         * SB3 is disabled in selected A. No position/FSM/PI retuning here. */
        if(fabsf(speed_lpf)>=5&&fabsf(error)>=5&&error*speed_lpf<0&&integral*speed_lpf>0){
            candidate=DobFb_Move(integral,0,5*dt);release=1;
        }else candidate=integral+.020f*error*dt;
        SpeedStartupBrakeResult b=SpeedBumpless_Apply(integral,candidate,ref,speed_lpf,dt,5,5);
        candidate=DobFb_Clamp(b.integral_A,.35f);
        if(b.flags&SPEED_BUMPLESS_UNLOAD)release=1;
        comp=DobFeedback_Update(&feedback,now+20,1000,
            monitor.current.sample_us,monitor.current.disturbance_a,
            (uint8_t)(monitor.current.valid&&monitor.running&&!monitor.frozen&&
                DobObserve10_FeedbackSpeedQualified(monitor.current.omega_rad_s)),running,
            fminf(.5f,cap_a/.05f));
        result=SpeedFrictionDob_Apply(integral,candidate,p,trajectory.acceleration_rpm_s,
            .000046875f,ref,.105f,2,.5f,.35f,release,1,1,comp);
        integral=result.speed.integral_a;
        MechanicalCurrent c={2,(uint32_t)(time_s*20000+.5)+20,now-20,now,id,iq,
            u[7]!=0?MEC_SATURATED:0};
        MechanicalDobMonitor_Observe(&monitor,now+20,now-(uint32_t)u[8],1000,
            speed_lpf*(2*pi/60),result.speed.saturated,&c,(uint8_t)(u[6]!=0));
    }else{DobFeedback_Clear(&feedback);integral=0;comp=0;}
    double out[DOB_NY]={ref,speed_lpf,trajectory.acceleration_rpm_s,
        result.speed.iq_pi_a,result.speed.iq_ff_a,result.iq_fric_a,
        result.speed.iq_raw_a,result.speed.iq_ref_a,integral,comp,
        monitor.current.disturbance_a,monitor.current.valid,monitor.current.status,
        monitor.abs_id_lpf,dob_current_admission.lpf_before,dob_current_admission.filter_updated,
        dob_current_admission.quality_reason,dob_current_admission.decision,
        resets,epoch_resets,reset_reason,monitor.observer.elapsed_s,
        dob_current_admission.id_bad_us,now-monitor.current.sample_us,
        monitor.current.sample_us,feedback.state,monitor.current.adc_seq,id,iq,
        fault,travel,monitor.current.omega_rad_s,monitor.current.iq_matched_a};
    memcpy(cached,out,sizeof out);memcpy(y,out,sizeof out);last_time=time_s;
}

/* Estimator-only epoch replay: observed_us,encoder_us,dt_us,omega_rad_s,
 * Id,Iq,seq,source_us,published_us,current_valid,iq_saturated,flags,running,fault.
 * No reconstruction of omitted current/encoder epochs or source metadata. */
void dob_host_observe(const double *u,double *y){
    epoch_resets=0;reset_reason=0;
    MechanicalDobMonitor_Lifecycle(&monitor,(uint8_t)u[12],(uint8_t)u[13]);
    MechanicalCurrent c={2,(uint32_t)u[6],(uint32_t)u[7],(uint32_t)u[8],
        (float)u[4],(float)u[5],(uint32_t)u[11]};
    MechanicalDobMonitor_Observe(&monitor,(uint32_t)u[0],(uint32_t)u[1],(uint32_t)u[2],
        (float)u[3],(uint8_t)u[10],&c,(uint8_t)u[9]);
    memset(y,0,DOB_NY*sizeof(double));
    y[10]=monitor.current.disturbance_a;y[11]=monitor.current.valid;y[12]=monitor.current.status;
    y[13]=monitor.abs_id_lpf;y[14]=dob_current_admission.lpf_before;
    y[15]=dob_current_admission.filter_updated;y[16]=dob_current_admission.quality_reason;
    y[17]=dob_current_admission.decision;y[18]=resets;y[19]=epoch_resets;y[20]=reset_reason;
    y[21]=monitor.observer.elapsed_s;y[22]=dob_current_admission.id_bad_us;
    y[23]=(uint32_t)u[0]-monitor.current.sample_us;y[24]=monitor.current.sample_us;
    y[26]=monitor.current.adc_seq;y[27]=u[4];y[28]=u[5];
    y[31]=monitor.current.omega_rad_s;y[32]=monitor.current.iq_matched_a;
}

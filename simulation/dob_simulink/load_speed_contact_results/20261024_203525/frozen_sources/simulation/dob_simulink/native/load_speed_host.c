/* Offline wrapper: reuse the reviewed controller, actual classifier and FSM.
 * New policy only selects an FSM target before the ORIGINAL S-curve. */
#define dob_host_reset base_host_reset
#define dob_host_step base_host_step
#define dob_host_state_size base_host_state_size
#define dob_host_save base_host_save
#define dob_host_restore base_host_restore
#define dob_host_observe base_host_observe
#define dob_host_configure base_host_configure
#include "dob_host.c"
#undef dob_host_reset
#undef dob_host_step
#undef dob_host_state_size
#undef dob_host_save
#undef dob_host_restore
#undef dob_host_observe
#undef dob_host_configure
#include "dob_trend_shadow.h"
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
#include "load_speed_contact_hold.h"
#define LOAD_SPEED_NY 66
static uint32_t contact_held,reacquire_us;
#else
#include "load_speed_scheduler.h"
#define LOAD_SPEED_NY 64
#endif
static TighteningFsm process;
static DobTrendClassifier classification;
static LoadSpeedScheduler scheduling;
static uint32_t wrapper_started;
static double wrapper_time=-1,wrapper_cache[LOAD_SPEED_NY];
typedef struct {
    OfflineSnapshot controller;
    TighteningFsm process;
    DobTrendClassifier classification;
    LoadSpeedScheduler scheduling;
    uint32_t started;
    double time,cache[LOAD_SPEED_NY];
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    uint32_t contact_held,reacquire_us;
#endif
} LoadSpeedSnapshot;
DOB_EXPORT unsigned dob_host_state_size(void){return sizeof(LoadSpeedSnapshot);}
DOB_EXPORT void dob_host_save(void *out){
    LoadSpeedSnapshot s={0};base_host_save(&s.controller);s.process=process;s.classification=classification;
    s.scheduling=scheduling;s.started=wrapper_started;s.time=wrapper_time;
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    s.contact_held=contact_held;s.reacquire_us=reacquire_us;
#endif
    memcpy(s.cache,wrapper_cache,sizeof wrapper_cache);memcpy(out,&s,sizeof s);
}
DOB_EXPORT void dob_host_restore(const void *in){
    LoadSpeedSnapshot s;memcpy(&s,in,sizeof s);base_host_restore(&s.controller);process=s.process;
    classification=s.classification;scheduling=s.scheduling;wrapper_started=s.started;wrapper_time=s.time;
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    contact_held=s.contact_held;reacquire_us=s.reacquire_us;
#endif
    memcpy(wrapper_cache,s.cache,sizeof wrapper_cache);
}
DOB_EXPORT void dob_host_configure(const double *c){base_host_configure(c);}
DOB_EXPORT void dob_host_reset(const double *c){
    base_host_reset(c);classification=(DobTrendClassifier){0};scheduling=(LoadSpeedScheduler){0};
    process=(TighteningFsm){0};wrapper_started=0;wrapper_time=-1;memset(wrapper_cache,0,sizeof wrapper_cache);
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    contact_held=reacquire_us=0;
#endif
}
DOB_EXPORT void dob_host_observe(const double *u,double *y){base_host_observe(u,y);}
DOB_EXPORT void dob_host_step(double t,const double *u,double *y){
    if(wrapper_time>=0&&fabs(t-wrapper_time)<1e-10){memcpy(y,wrapper_cache,sizeof wrapper_cache);return;}
    uint32_t ms=(uint32_t)(t*1000+.5),now=(uint32_t)(t*1e6+.5)+100000U;
    float rpm=(float)(u[1]*60/(2*3.14159265358979323846)+u[3]);
    if(!wrapper_started){
        TighteningFsmConfig cfg={.recipe=TIGHTEN_PARAMS_DEFAULT_INITIALIZER,.direction=u[12]<0?-1:1,
            .speed_iq_limit_a=.5f,.direct_iq_limit_a=.5f,.hard_speed_limit_rpm=500.f,
            .stop_max_rpm=2,.stop_confirm_ms=150,.stop_timeout_ms=2000,.session_timeout_ms=12000};
        cfg.recipe.contact_rpm=20;TighteningFsm_Init(&process,cfg,ms);wrapper_started=1;
    }
    TighteningFsmReason protection=fault||u[15]!=0?TF_REASON_FAULT:TF_REASON_NONE;
    if(fabsf(rpm)>=500.f)protection=TF_REASON_OVERSPEED;
    TighteningFsmInput in={.now_ms=ms,.position_deg=(float)u[11],
        .speed_ctrl_rpm=have_speed?speed_lpf:rpm,.speed_detect_rpm=rpm,.iq_demand_a=(float)wrapper_cache[7],
        .start=(uint8_t)(u[0]!=0&&process.state==TF_IDLE&&process.outcome!=TF_OUT_STOPPED),
        .stop=(uint8_t)(u[14]!=0||u[9]==0),.precheck_ready=1,.encoder_valid=1,.protection_fault=protection};
    TighteningFsm_Step(&process,in);
    ControlIntent intent=process.intent;
    /* Previous completed classifier is consumed exactly once before this
     * epoch's controller/DOB update. Ground-truth fixture flag is NOT used. */
    LoadSpeedEvidence load_evidence={now,process.state,(uint32_t)(u[10]!=0),
        classification.valid,classification.state,classification.trend_valid,classification.trend_state,
        intent.speed_target_rpm,(float)process.cfg.recipe.contact_rpm,classification.mean};
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    float target=LoadSpeedContact_Step(&scheduling,&contact_held,&reacquire_us,load_evidence);
#else
    float target=LoadSpeed_Step(&scheduling,load_evidence);
#endif
    double v[10];memcpy(v,u,sizeof v);v[0]=target;v[9]=intent.control_mode==CONTROL_SPEED&&u[9]!=0;
    if(intent.reset_speed_integrator)integral=0;
    double out[LOAD_SPEED_NY]={0};base_host_step(t,v,out);
    if(intent.control_mode!=CONTROL_SPEED){
        out[7]=intent.control_mode==CONTROL_IQ?DobFb_Clamp(intent.iq_target_a,intent.iq_limit_a):0;
        out[6]=out[7];out[0]=out[2]=out[3]=out[4]=out[5]=out[8]=out[9]=0;
    }
    DobTrendInput evidence={.encoder_us=now,.observed_us=now+20,.source_us=monitor.current.adc_source_us,
        .disturbance_a=monitor.current.disturbance_a,.direction=process.cfg.direction<0?-1:1,
        .running=(uint8_t)(intent.control_mode==CONTROL_SPEED),.fault=(uint8_t)(fault||protection!=TF_REASON_NONE),
        .valid=(uint8_t)monitor.current.valid,.filter_updated=(uint8_t)dob_current_admission.filter_updated};
    /* Output scheduler evidence is the frame it actually consumed, rather
     * than a newly computed/future classification. */
    double extra[]={intent.speed_target_rpm,target,scheduling.slow,scheduling.reason,scheduling.transitions,
        scheduling.high_us,scheduling.release_us,classification.state,classification.valid,
        classification.mean,classification.trend_state,classification.trend_valid,classification.trend_filtered,
        process.state,process.fault_reason,process.contact_pending,process.contact_confirmed,process.outcome,
        process.rundown_armed,process.rundown_peak_speed_rpm,process.contact_pending_ms,intent.control_mode,
        intent.iq_limit_a,DOB_FB_GAIN,u[10],scheduling.last_good_us,intent.reset_speed_integrator,
        process.cfg.recipe.contact_rpm,process.cfg.recipe.contact_iq_mA,process.cfg.recipe.contact_ms,process.transition_count};
    memcpy(out+33,extra,sizeof extra);
#if defined(DOB_LOAD_SPEED_CONTACT_HOLD)
    out[64]=contact_held;out[65]=reacquire_us;
#endif
    DobTrendClassifier_Step(&classification,evidence);
    memcpy(wrapper_cache,out,sizeof wrapper_cache);memcpy(y,out,sizeof wrapper_cache);wrapper_time=t;
}

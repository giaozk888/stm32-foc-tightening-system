/* Standalone estimator-only DLL. Reuses real monitor and bounded feedback.
 * Physical speed/current/load are independent recorded inputs. No actuator. */
#include "dob_host.h"
#include "offline_low_recovery.h"
#include "dob_feedback_candidate.h"
#include <string.h>
typedef struct {
    MechanicalDobMonitor m;
    DobCurrentAdmission admission;
    DobFeedbackCandidate feedback;
    OfflineLowRecovery recovery;
    uint32_t resets;
} LowHost;
static LowHost state;
void DobIdTrace_ResetEvent(uint32_t reason){(void)reason;++state.resets;}
void dob_host_configure(const double *c){state.feedback.enabled=(uint32_t)(c[0]!=0);}
void dob_host_reset(const double *c){
    memset(&state,0,sizeof state);memset(&dob_current_admission,0,sizeof dob_current_admission);
    memset(&dob_saturation_audit,0,sizeof dob_saturation_audit);dob_host_configure(c);
}
unsigned dob_host_state_size(void){return sizeof state;}
void dob_host_save(void *p){state.admission=dob_current_admission;memcpy(p,&state,sizeof state);}
void dob_host_restore(const void *p){memcpy(&state,p,sizeof state);dob_current_admission=state.admission;}
void dob_host_step(double t,const double *u,double *y){(void)t;dob_host_observe(u,y);}
void dob_host_observe(const double *u,double *y){
    uint32_t now=(uint32_t)u[0],enc=(uint32_t)u[1],dt=(uint32_t)u[2];
    uint8_t run=(uint8_t)u[12],fault=(uint8_t)u[13];
    MechanicalDobMonitor_Lifecycle(&state.m,run,fault);
    MechanicalCurrent c={2,(uint32_t)u[6],(uint32_t)u[7],(uint32_t)u[8],(float)u[4],(float)u[5],(uint32_t)u[11]};
    OfflineLow_Observe(&state.recovery,&state.m,now,enc,dt,(float)u[3],(uint8_t)u[10],&c,(uint8_t)u[9],LOW_RECOVERY_ENABLED);
    float comp=DobFeedback_Update(&state.feedback,now,dt,state.m.current.sample_us,state.m.current.disturbance_a,
        (uint8_t)(state.m.current.valid&&!(state.m.current.status&DOB_MONITOR_SATURATED)&&
        DobObserve10_FeedbackSpeedQualified(state.m.current.omega_rad_s)),(uint8_t)(run&&!fault),.5f);
    double out[DOB_NY]={state.m.current.disturbance_a,state.m.current.valid,state.m.current.status,
        state.m.observer.elapsed_s,comp,state.feedback.state,state.resets,state.recovery.mode,
        state.recovery.reason,state.recovery.fast,state.recovery.cold,state.recovery.held_epochs,
        state.recovery.confirm_epochs,state.recovery.quiet_n,state.m.abs_id_lpf,
        dob_current_admission.filter_updated,state.m.observer.omega_lpf,state.m.observer.drive_lpf,
        state.m.observer.initialized,state.m.running,state.m.frozen,state.feedback.valid_updates,
        state.m.current.iq_a,state.m.current.id_a,state.recovery.low_max_us,
        state.m.observations,state.m.valid_samples,state.m.rejected_samples,
        state.recovery.quiet_start,state.recovery.return_start,state.recovery.low_start,0,0};
    memcpy(y,out,sizeof out);
}

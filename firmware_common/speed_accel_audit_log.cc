#define PW_LOG_MODULE_NAME "ACCEL_AUDIT"
#include "speed_accel_audit.h"
#include "pw_log/log.h"
extern "C" void SpeedAccelAudit_Log(const SpeedAccelAuditFrame *f)
{
    /* MonitorTask only. Four independently <=32 B tokens, same seq. */
    PW_LOG_INFO("AAC R seq=%u ms=%u traj=%u phase=%u flags=%u",
        unsigned(f->seq),unsigned(f->ms),unsigned(f->trajectory_update),
        unsigned(f->trajectory_phase),unsigned(f->flags));
    PW_LOG_INFO("AAC T seq=%u ref=%.4f meas=%.4f err=%.4f accel=%.4f dt=%.6f",
        unsigned(f->seq),f->speed_ref,f->speed_meas,f->speed_error,f->accel_ref,f->dt_s);
    PW_LOG_INFO("AAC C seq=%u pi=%.7f ff=%.7f fric=%.7f raw=%.7f cmd=%.7f",
        unsigned(f->seq),f->iq_pi,f->iq_acc_ff,f->iq_fric,f->iq_raw,f->iq_cmd);
    PW_LOG_INFO("AAC I seq=%u integral=%.7f",unsigned(f->seq),f->integrator);
}

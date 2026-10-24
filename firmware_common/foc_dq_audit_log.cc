#define PW_LOG_MODULE_NAME "DQ_AUDIT"
#include "foc_dq_audit.h"
#include "pw_log/log.h"
extern "C" void FocDqAudit_LogFrame(const FocDqAuditFrame *f)
{
    /* R/S/I/V share seq. <=3 ints+2 floats or 1 int+4 floats per token. */
    PW_LOG_INFO("DQA R seq=%u us=%u flags=%u mech_rpm=%.6f we_rad_s=%.6f",
        unsigned(f->seq),unsigned(f->us),unsigned(f->flags),f->mech_rpm,f->we_rad_s);
    PW_LOG_INFO("DQA S seq=%u speed_ref=%.6f speed_meas=%.6f elapsed_us=%u",
        unsigned(f->seq),f->speed_ref,f->speed_meas,unsigned(f->elapsed_us));
    PW_LOG_INFO("DQA I seq=%u id=%.9f iq=%.9f vd_pi=%.9f vq_pi=%.9f",
        unsigned(f->seq),f->id,f->iq,f->vd_pi,f->vq_pi);
    PW_LOG_INFO("DQA V seq=%u vd_dec=%.9f vq_dec=%.9f vd_cmd=%.9f vq_cmd=%.9f",
        unsigned(f->seq),f->vd_dec,f->vq_dec,f->vd_cmd,f->vq_cmd);
}
extern "C" void FocDqAudit_LogStats(const FocDqAuditStats *s)
{
    PW_LOG_INFO("DQA Z n=%u vd_abs_max=%.9f vq_abs_max=%.9f",unsigned(s->zero_n),s->zero_d_max,s->zero_q_max);
    PW_LOG_INFO("DQA B n=%u vd_abs_max=%.9f vq_abs_max=%.9f",unsigned(s->start_n),s->start_d_max,s->start_q_max);
    float d=s->cruise_n ? s->cruise_d_sum/float(s->cruise_n) : 0.0f;
    float q=s->cruise_n ? s->cruise_q_sum/float(s->cruise_n) : 0.0f;
    PW_LOG_INFO("DQA C n=%u vd_mean=%.9f vq_mean=%.9f",unsigned(s->cruise_n),d,q);
    PW_LOG_INFO("DQA K run_n=%u sat_n=%u first_sat_us=%u config_bad=%u",
        unsigned(s->run_n),unsigned(s->sat_n),unsigned(s->first_sat_us),unsigned(s->config_bad));
    PW_LOG_INFO("DQA W we_abs_max=%.6f chain_error_max=%.6f nominal_d_bad=%u nominal_q_bad=%u invalid=%u",
        s->we_abs_max,s->we_chain_error_max,unsigned(s->nominal_d_bad),unsigned(s->nominal_q_bad),unsigned(s->invalid_n));
}

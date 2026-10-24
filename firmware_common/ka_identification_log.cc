#define PW_LOG_MODULE_NAME "KA_IDENT"
#include "ka_identification.h"
#include "pw_log/log.h"
extern "C" void KaIdent_Log(const KaIdentFrame *f)
{
    /* MonitorTask only. Same-seq compressed binary packets, <=32 bytes each. */
    PW_LOG_INFO("KAI T seq=%u start_us=%u end_us=%u flags=%u",
        unsigned(f->seq),unsigned(f->start_us),unsigned(f->end_us),unsigned(f->flags));
    PW_LOG_INFO("KAI S seq=%u speed_start=%.6f speed_end=%.6f ref=%.6f meas=%.6f",
        unsigned(f->seq),f->speed_start_rpm,f->speed_end_rpm,f->mean_speed_ref_rpm,f->mean_speed_meas_rpm);
    PW_LOG_INFO("KAI I seq=%u iq_mean=%.7f fric_mean=%.7f",
        unsigned(f->seq),f->mean_iq_a,f->mean_friction_a);
}

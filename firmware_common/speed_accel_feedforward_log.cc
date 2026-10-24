#define PW_LOG_MODULE_NAME "ACCEL_FF"
#include "speed_accel_feedforward.h"
#include "pw_log/log.h"

extern "C" void SpeedAccelFf_Log(const SpeedAccelFfFrame *f)
{
    /* MonitorTask only, two <=32-byte token payloads even at uint32 max.
     * Correlate R/C by seq. No UART or formatting in the 1kHz owner/20kHz ISR. */
    PW_LOG_INFO("AFF R seq=%u ms=%u on=%u speed_ref=%.3f speed_meas=%.3f accel_ref=%.3f command=%.3f",
        unsigned(f->seq),unsigned(f->ms),unsigned(f->enabled),
        f->speed_ref_rpm,f->speed_meas_rpm,f->accel_ref_rpm_s,f->command_rpm);
    PW_LOG_INFO("AFF C seq=%u sat=%u iq_pi=%.6f iq_ff=%.6f iq_raw=%.6f iq_ref=%.6f speed_integrator=%.6f",
        unsigned(f->seq),unsigned(f->saturated),f->iq_pi_a,f->iq_ff_a,
        f->iq_raw_a,f->iq_ref_a,f->speed_integrator_a);
}

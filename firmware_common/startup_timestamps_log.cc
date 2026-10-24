#include "startup_timestamps.h"
#define PW_LOG_MODULE_NAME "STM"
#include "pw_log/log.h"
extern "C" void StartupTimes_Log(const StartupTimestamps *s)
{
    /* Each packet <=4 uint32 arguments; comfortably within 32-byte encoder.
     * Join by observations, not adjacent UART receive times. */
    PW_LOG_INFO("STT A seq=%lu valid=%lu t0_us=%lu tiq_us=%lu",
        (unsigned long)s->observations,(unsigned long)s->valid,
        (unsigned long)s->t0_us,(unsigned long)s->t_iq_us);
    PW_LOG_INFO("STT B seq=%lu tmotion_us=%lu tspeed_us=%lu tstable_us=%lu",
        (unsigned long)s->observations,(unsigned long)s->t_motion_us,
        (unsigned long)s->t_speed_us,(unsigned long)s->t_stable_us);
    PW_LOG_INFO("STT C seq=%lu motion_begin_us=%lu iq_at_event_a=%.6f",
        (unsigned long)s->observations,(unsigned long)s->motion_begin_us,(double)s->iq_at_event_a);
    PW_LOG_INFO("STT D seq=%lu motion_dir=%ld speed_at_event_rpm=%.6f",
        (unsigned long)s->observations,(long)s->motion_direction,(double)s->speed_at_event_rpm);
}

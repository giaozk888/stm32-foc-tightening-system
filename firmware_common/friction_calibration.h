#ifndef FRICTION_CALIBRATION_H
#define FRICTION_CALIBRATION_H
#include <stdint.h>
#include <math.h>
#include <string.h>

/* Measurement criteria only, not controller or protection thresholds. One
 * point per protected boot; never clears/re-arms a session or raises current. */
#define FCAL_DRIVE_MS 5000U
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
/* Existing 200rpm/s / 1000rpm/s^2 trajectory needs 4.2s to stop from 800rpm.
 * Keep the independent 12s lease; this earlier task closure includes margin. */
#if !defined(FOC_MECHANICAL_MOTION_DIAG)
#error High-speed grid requires explicit mechanical commands
#endif
#define FCAL_STOP_MS 10500U
#else
#define FCAL_STOP_MS 7000U
#endif
#define FCAL_STABLE_S 0.50f
#define FCAL_MIN_VALID_S 2.0f
#define FCAL_SPEED_TOL_FRACTION 0.05f
#define FCAL_SPEED_TOL_MIN_RPM 2.0f
#define FCAL_MAX_REJECT_FRACTION 0.05f
typedef struct {
    uint32_t valid, reject, seen;
    float valid_s, stable_s, iq_sum, iq_ref_sum, id_sum, abs_id_sum;
    float iq_sq_sum, speed_sum, speed_error_sum, start_angle, last_angle;
    float net_travel, abs_travel;
    int32_t rpm;
    uint8_t used,queued,prepared,admitting,active,finished,passed,angle_initialized;
    uint32_t encoder_before, stop_good_ms;
} FrictionCalibration;

static inline int Fcal_Parse(const char *s,int32_t *rpm)
{
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#if defined(FOC_MECHANICAL_DOB_SHADOW)
    static const int32_t points[]={600,-600};
    static const char *const commands[]={"MOTOR TEST MECH RUN POS 600","MOTOR TEST MECH RUN NEG 600"};
#elif defined(FOC_MECHANICAL_REVERSE_IDENT_DIAG)
    static const int32_t points[]={-600,-700,-800};
    static const char *const commands[]={
        "MOTOR TEST MECH RUN NEG 600","MOTOR TEST MECH RUN NEG 700",
        "MOTOR TEST MECH RUN NEG 800"};
#else
    static const int32_t points[]={500,600,700,800};
    static const char *const commands[]={
        "MOTOR TEST MECH RUN POS 500","MOTOR TEST MECH RUN POS 600",
        "MOTOR TEST MECH RUN POS 700","MOTOR TEST MECH RUN POS 800"};
#endif
#elif defined(FOC_MECHANICAL_MOTION_DIAG)
    static const int32_t points[]={100,-100,200,-200,240,-240};
    static const char *const commands[]={
        "MOTOR TEST MECH RUN POS 100","MOTOR TEST MECH RUN NEG 100",
        "MOTOR TEST MECH RUN POS 200","MOTOR TEST MECH RUN NEG 200",
        "MOTOR TEST MECH RUN POS 240","MOTOR TEST MECH RUN NEG 240"};
#elif defined(FOC_FRICTION_HIGH_SPEED_GRID)
    static const int32_t points[]={200,240,260,280,-200,-240,-260,-280};
    static const char *const commands[]={
        "MOTOR TEST FCAL RUN POS 200","MOTOR TEST FCAL RUN POS 240",
        "MOTOR TEST FCAL RUN POS 260","MOTOR TEST FCAL RUN POS 280",
        "MOTOR TEST FCAL RUN NEG 200","MOTOR TEST FCAL RUN NEG 240",
        "MOTOR TEST FCAL RUN NEG 260","MOTOR TEST FCAL RUN NEG 280"};
#else
    static const int32_t points[]={40,80,120,240,-40,-80,-120,-240};
    static const char *const commands[]={
        "MOTOR TEST FCAL RUN POS 40","MOTOR TEST FCAL RUN POS 80",
        "MOTOR TEST FCAL RUN POS 120","MOTOR TEST FCAL RUN POS 240",
        "MOTOR TEST FCAL RUN NEG 40","MOTOR TEST FCAL RUN NEG 80",
        "MOTOR TEST FCAL RUN NEG 120","MOTOR TEST FCAL RUN NEG 240"};
#endif
    for (unsigned i=0;i<sizeof(points)/sizeof(points[0]);++i)
        if (!strcmp(s,commands[i])) { *rpm=points[i];return 1; }
    return 0;
}
static inline void Fcal_Observe(FrictionCalibration *s,float reference,float speed,
    float accel,float iq,float iq_ref,float id,float angle,float dt,uint8_t healthy)
{
    if (!s->active || s->finished) return;
    ++s->seen;
    if (!isfinite(dt) || dt<=0 || dt>.01f || !isfinite(speed) ||
        !isfinite(reference) || !isfinite(accel) || !isfinite(iq) ||
        !isfinite(iq_ref) || !isfinite(id) || !isfinite(angle)) {
        ++s->reject;s->stable_s=0;return;
    }
    if (!s->angle_initialized) {
        s->start_angle=s->last_angle=angle;s->angle_initialized=1U;
    }
    s->abs_travel+=fabsf(angle-s->last_angle);s->last_angle=angle;
    s->net_travel=angle-s->start_angle;
    float tolerance=fmaxf(FCAL_SPEED_TOL_MIN_RPM,FCAL_SPEED_TOL_FRACTION*fabsf((float)s->rpm));
    uint8_t plateau=fabsf(reference-(float)s->rpm)<=.001f && fabsf(accel)<=.001f;
    if (!plateau) { s->stable_s=0;return; } /* Never fit acceleration torque. */
    if (fabsf(speed-(float)s->rpm)>tolerance) {
        ++s->reject;s->stable_s=0;return;
    }
    s->stable_s+=dt;
    if (s->stable_s<FCAL_STABLE_S) return;
    if (!healthy) { ++s->reject;return; }
    ++s->valid;s->valid_s+=dt;
    /* Time weighted physical feedback, not peaks or DC supply current. */
    s->iq_sum+=iq*dt;s->iq_sq_sum+=iq*iq*dt;s->iq_ref_sum+=iq_ref*dt;
    s->id_sum+=id*dt;s->abs_id_sum+=fabsf(id)*dt;
    s->speed_sum+=speed*dt;s->speed_error_sum+=fabsf(speed-(float)s->rpm)*dt;
}
static inline void Fcal_Finish(FrictionCalibration *s,uint8_t no_fault)
{
    s->finished=1U;
    s->passed=(uint8_t)(no_fault && s->valid_s>=FCAL_MIN_VALID_S &&
        s->valid && s->reject<=FCAL_MAX_REJECT_FRACTION*(float)(s->valid+s->reject) &&
        (float)s->rpm*s->net_travel>0);
}
#endif

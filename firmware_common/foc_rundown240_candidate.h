#ifndef FOC_RUNDOWN240_CANDIDATE_H
#define FOC_RUNDOWN240_CANDIDATE_H

/* Explicit application-A experiment, not production defaults. Only requested
 * command/trip limits live here; no PI, ramp or safety-chain implementation. */
#if defined(FOC_RUNDOWN240_CANDIDATE)
#if FOC_RUNDOWN240_CANDIDATE != 1 || !defined(FOC_INTENT_FSM_CANDIDATE) || \
    !defined(FOC_PWM_COMMON_MODE_ENABLE) || !defined(FOC_LOADED_FSM_TRIAL) || \
    !defined(FOC_PWM_PIPELINE_CLOSED_LOOP) || defined(FOC_TORQUE_CHAIN_DIAG) || \
    defined(FOC_SPEED_DYNAMIC_DIAG) || defined(FOC_TORQUE450_150RPM) || \
    defined(TIGHTEN_SPEED_X2_OFFLINE)
#error 240rpm candidate requires the exclusive protected common-mode intent FSM
#endif
#define FOC_RUNDOWN240_TARGET_RPM 240U
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#if FOC_MECHANICAL_HIGH_SPEED_DIAG != 1 || !defined(FOC_MECHANICAL_MOTION_DIAG) || \
    !defined(FOC_MECHANICAL_IDENT_DIAG) || !defined(FOC_FRICTION_CALIBRATION_DIAG) || \
    !defined(FOC_RUNDOWN240_TRAVEL20000) || defined(FOC_PSI_IDENT_DIAG)
#error High-speed mechanical limits require the exclusive manual A diagnostic
#endif
#define FOC_RUNDOWN240_TRIP_RPM 1000U
#define FOC_RUNDOWN240_TRIP_TEXT "1000"
#elif defined(FOC_PSI_IDENT_TRIP500)
#if FOC_PSI_IDENT_TRIP500 != 1 || !defined(FOC_PSI_IDENT_DIAG)
#error 500rpm trip requires the exclusive manual PSI diagnostic
#endif
#define FOC_RUNDOWN240_TRIP_RPM 500U
#define FOC_RUNDOWN240_TRIP_TEXT "500"
#else
#define FOC_RUNDOWN240_TRIP_RPM 300U
#define FOC_RUNDOWN240_TRIP_TEXT "300"
#endif
#define FOC_RUNDOWN240_IQ_LIMIT_A 0.50f
#define FOC_RUNDOWN240_TARGET_TEXT "240"
#endif

#if defined(FOC_PSI_IDENT_TRIP500) && !defined(FOC_RUNDOWN240_CANDIDATE)
#error 500rpm trip requires the protected rundown candidate
#endif

#if defined(FOC_RUNDOWN240_TRAVEL20000)
#if FOC_RUNDOWN240_TRAVEL20000 != 1 || !defined(FOC_RUNDOWN240_CANDIDATE)
#error 20000deg travel requires the separate protected 240rpm candidate
#endif
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#define FOC_RUNDOWN240_MAX_TRAVEL_DEG 30000U
#else
#define FOC_RUNDOWN240_MAX_TRAVEL_DEG 20000U
#endif
#endif

#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG) && !defined(FOC_RUNDOWN240_CANDIDATE)
#error High-speed mechanical diagnostic requires the protected rundown candidate
#endif

#endif

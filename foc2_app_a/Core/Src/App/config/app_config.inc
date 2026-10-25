/* App A config/app_config.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define ROUTER_LOCAL_NODE_ID 1U

#define PI_F 3.14159265358979323846f
#define TWO_PI_F 6.28318530717958647692f

#define ADC_VREF_MV 3300U
#define ADC_FULL_SCALE 4095U
#define CURRENT_GAIN_MV_PER_A 120U
#define ADC_MEDIAN_SAMPLES 5U
#define ADC_ZERO_CAL_SAMPLES 500U
#define ANALOG_LIVE_PERIOD_MS 100U
#define ANALOG_LIVE_FRESH_MS 500U
#define ANALOG_VDDA_MIN_MV 2400U
#define ANALOG_VDDA_MAX_MV 3600U
#define ANALOG_VBUS_DIVIDER 25U
#define ANALOG_SAFE_MAX_RPM 2.0f
#define ANALOG_TRIPLE_DISAGREE_COUNTS 60U
/* Stage 7.12 experiment: PC4/PC5 only; B remains the 47.5-cycle control. */
#define ANALOG_GPIO_SAMPLE_TIME ADC_SAMPLETIME_247CYCLES_5

/*
 * PWM-ON dynamic zero calibration:
 * - bridge enabled
 * - U/V/W duty all fixed at 50%
 * - modulation = 0
 * - injected ADC still triggered by TIM1 at 20kHz
 */
#define RUN_ZERO_SETTLE_MS 100U
#define RUN_ZERO_CAL_SAMPLES 4000U
#define RUN_ZERO_TIMEOUT_MS 1500U
#define RUN_ZERO_MAX_DELTA_COUNTS 100

/*
 * Dual-ADC runtime plausibility filter.
 *
 * ADC1 and ADC2 now sample IU and IV simultaneously. IW is reconstructed:
 *     IW = -(IU + IV)
 *
 * Because the reconstructed three-phase sum is identically zero, the old
 * KCL sum filter is no longer useful. For this bring-up test we reject only
 * an implausibly large one-sample jump on IU or IV.
 *
 * 60 ADC counts is about 0.40 A with the present current-sense scaling.
 * At the present very slow open-loop test this is far above the legitimate
 * 50 us current-to-current change, but still catches isolated ADC spikes.
 */
#define CURRENT_STEP_REJECT_COUNTS 60
#define CURRENT_REJECT_STREAK_LIMIT 20U

#define PWM_ARR 4249U
#define PWM_HALF 2125U
#define ADC_TRIGGER_CCR4 3500U
#if defined(FOC_ADC_WINDOW)
_Static_assert(PWM_ARR == FOC_ADC_TIMER_ARR, "Review ADC timing after PWM clock/ARR changes");
#endif

/*
 * First closed-loop FOC current-control bring-up.
 *
 * Current loop executes from the 20 kHz ADC1 injected-complete interrupt.
 * Encoder is refreshed by SPI every 1 ms in the foreground. This is intended
 * only for the present low-speed bring-up; a production high-speed design
 * should use a faster/pipelined rotor-angle path.
 */
#define FOC_TS_S                    0.00005f   /* 20 kHz */
#define FOC_CURRENT_KP_V_PER_A      0.080f
#define FOC_CURRENT_KI_V_PER_AS     188.0f
#include "current_pi_identified_candidate.h"

#define FOC_ID_REF_A                0.0f

/*
 * CURRENT RTOS ARCHITECTURE
 *
 *   ADC ISR @20kHz:
 *       current sample -> Clarke/Park -> Id/Iq PI -> inverse Park -> SVPWM
 *
 *   MotorControlTask @1kHz:
 *       encoder/speed estimation + generic POSITION/SPEED/IQ outer control
 *
 *   TighteningTask @100Hz:
 *       application-layer command/state machine
 *
 *   MonitorTask:
 *       low-priority UART logging
 *
 * Historical bare-metal position-sequence code after scheduler failure was
 * removed during modularization. The original is preserved in
 * refactor_backups/20261002_cpp_params/main_a.c. Runtime motion belongs
 * exclusively to the RTOS task/control paths above.
 */

/*
 * Cascaded POSITION -> SPEED -> CURRENT FOC sequence test.
 *
 * Mechanical position is unwrapped and referenced to the rotor position
 * at FOC enable.
 *
 * Sequence progression is settle-qualified instead of using a fixed 4 s
 * duration for every move:
 *
 *   STG0: startup zero hold for 1 s
 *   STG1: command +90 deg; advance after |PERR|<=1.30 deg and |SPD|<=2 rpm
 *         continuously for 500 ms
 *   STG2: command   0 deg; same completion rule
 *   STG3: command -90 deg; same completion rule
 *   STG4: command   0 deg; same completion rule
 *   STG5: hold      0 deg forever
 *
 * Every moving stage must first observe PDB=0 once after its new target is
 * applied.  This proves the new target has propagated through the outer loop
 * and prevents the previous stage's PDB=1 state from being counted by mistake.
 */
#define SPEED_REF_RPM               0.0f

#define POSITION_INITIAL_HOLD_MS    1000U
#define POSITION_SETTLE_HOLD_MS      500U

/*
 * Position-sequence completion window.
 *
 * This is deliberately separate from PDB hysteresis:
 *   PDB controls whether the outer position loop is active.
 *   These limits decide whether a move is stable enough to advance.
 */
#define POSITION_STAGE_SETTLE_ERR_DEG 1.30f
#define POSITION_STAGE_SETTLE_SPD_RPM 2.00f

/*
 * FINAL STG5 HYBRID ACTIVE HOLD
 *
 * STG0..STG4 keep the already-validated three-loop cascade:
 *
 *     Position P -> speed ramp -> speed PI -> Iq -> current PI
 *
 * STG5 uses hysteretic mode switching:
 *
 *   |PERR| <= 2.0 deg : ACTIVE HOLD
 *       Iq_hold = Kp_hold * PERR - Kd_hold * SPD
 *
 *   |PERR| >= 3.0 deg : CASCADE RETURN
 *       Position P -> speed ramp -> speed PI -> Iq
 *       STG5-only limits: +/-10 rpm and +/-0.30 A
 *
 *   2.0 < |PERR| < 3.0 deg : keep the current mode
 *
 * The 1 deg / 1.3 deg PDB remains useful for the normal cascade and UART
 * diagnostics, but it does NOT zero torque while ACTIVE HOLD is selected.
 */
#define ACTIVE_HOLD_ENTER_DEG          2.00f
#define ACTIVE_HOLD_EXIT_DEG           3.00f
#define ACTIVE_HOLD_KP_A_PER_DEG       0.100f
#define ACTIVE_HOLD_KD_A_PER_RPM       0.004f
#define ACTIVE_HOLD_IQ_LIMIT_A         0.300f

/*
 * STG5 cascade-return limits.
 *
 * When a hand disturbance pushes the rotor outside ACTIVE_HOLD_EXIT_DEG,
 * STG5 temporarily returns to the normal Position -> Speed -> Iq cascade.
 * Use gentler limits than the automatic STG0..STG4 positioning sequence so
 * the rotor does not snap back aggressively after a large manual deflection.
 */
#define STG5_RETURN_SPEED_LIMIT_RPM     8.0f
#define STG5_RETURN_IQ_LIMIT_A          0.40f
#define STG5_RETURN_STALL_IQ_MIN_A      0.38f

#define POSITION_TARGET_0_DEG       0.0f
#define POSITION_TARGET_P90_DEG     90.0f
#define POSITION_TARGET_M90_DEG    -90.0f

#define POSITION_KP_RPM_PER_DEG     1.00f
#define POSITION_SPEED_LIMIT_RPM    10.0f

/*
 * Position deadband hysteresis:
 *
 *   enter settled state when |PERR| <= 1.00 deg
 *   leave settled state only when |PERR| >= 1.30 deg
 *
 * This prevents the controller from repeatedly toggling around the exact
 * +/-1.00 deg boundary because of encoder quantization/noise.
 */
#define POSITION_DEADBAND_ENTER_DEG 1.00f
#define POSITION_DEADBAND_EXIT_DEG  1.30f

/*
 * Speed-PI integrator cleanup after the position target is reached.
 *
 * When the position is inside the deadband and both REF/SPD are near zero,
 * bleed the stored speed integrator smoothly toward 0 instead of leaving a
 * residual Iq indefinitely.
 *
 * 0.50 A/s means a residual 0.20 A integral takes about 0.4 s to decay.
 */
#define SPEED_INT_BLEED_A_PER_S      0.50f
#define SPEED_INT_BLEED_REF_MAX_RPM  1.00f
#define SPEED_INT_BLEED_SPD_MAX_RPM  2.00f

/*
 * Dynamic overspeed integrator release.
 *
 * If the rotor is already moving faster than the reference so that the
 * proportional term is braking, but the stored speed integral still pushes
 * in the rotor's present direction, bleed that stale integral rapidly.
 *
 * This acts BEFORE the position target is crossed, unlike RCLR.
 */
#define SPEED_OVERSPEED_I_BLEED_A_PER_S   5.00f
#define SPEED_OVERSPEED_BLEED_ERR_RPM     5.00f
#define SPEED_OVERSPEED_BLEED_MIN_SPD_RPM 5.00f

/*
 * Speed-command slew-rate limiter between the position controller and speed PI.
 * Keep the proven symmetric +/-200 rpm/s setting for this first position test.
 */
#define SPEED_RAMP_UP_RPM_PER_S     200.0f
#define SPEED_RAMP_DOWN_RPM_PER_S   200.0f

#define SPEED_KP_A_PER_RPM          0.0030f
#define SPEED_KI_A_PER_RPM_S        0.0200f
#define SPEED_IQ_LIMIT_A            0.40f
#define SPEED_INT_LIMIT_A           0.35f
#define SPEED_FILTER_TAU_S          0.020f
#if defined(FOC_PSI_IDENT_TRIP500) || defined(FOC_MECHANICAL_HIGH_SPEED_DIAG) || defined(FOC_NORMAL_RUN_TRIP500)
#define SPEED_OVERSPEED_RPM         ((float)FOC_RUNDOWN240_TRIP_RPM)
#else
#define SPEED_OVERSPEED_RPM         300.0f
#endif

/*
 * Dual mechanical-speed estimator.
 *
 * CONTROL SPEED:
 *   accepted 1 ms AS5047P delta
 *      -> instantaneous rpm
 *      -> existing 20 ms first-order LPF
 *      -> encoder_speed_rpm
 *      -> Speed PI / overspeed / existing controller logic
 *
 * This restores the control estimator that previously gave the best
 * 100 rpm behavior.
 *
 * DETECTION SPEED:
 *   accepted encoder deltas are accumulated over 50 ms
 *      -> average mechanical rpm
 *      -> encoder_speed_detect_rpm
 *
 * The 50 ms value is NOT fed back into the speed PI.  It is intended for
 * future RUNDOWN / SEATING / load-detection logic, where a slower average
 * is preferable to reacting to individual cogging/stick-slip samples.
 */
#define SPEED_DETECT_WINDOW_S        0.050f
#define SPEED_DETECT_MIN_SAMPLES     20U

/*
 * Position/speed stall protection.
 *
 * If the ramped speed reference asks for meaningful motion but the measured
 * speed stays essentially zero for one continuous second, declare a stall.
 * This prevents an unresolved position error from holding current forever.
 */
#define STALL_REF_MIN_RPM            5.0f
#define STALL_SPEED_MAX_RPM          2.0f
#define STALL_IQ_MIN_A               0.38f
#define STALL_TIMEOUT_S              1.5f

/*
 * Generic motor-control API / first TighteningTask speed-mode test.
 *
 * This application-layer test validates controlled mode transitions needed
 * by the future tightening state machine:
 *
 *   SPEED(100 rpm) -> SPEED(20 rpm) -> IDLE -> IQ pulse -> IDLE
 *
 * The IQ pulse is deliberately only +0.05 A for 200 ms because direct-Iq
 * is torque mode and an unloaded motor can accelerate rapidly.
 *
 *   IDLE 2 s
 *   SPEED +100 rpm for 3 s
 *   SPEED +20 rpm for 3 s
 *   IDLE until stopped
 *   DIRECT-IQ +0.05 A for 200 ms
 *   IDLE forever
 *
 * The SPEED-mode torque authority now uses the same already validated
 * +/-0.40 A limit as the position loop.  This test uses +/-100 rpm so the
 * speed estimator and PI are validated away from the severe 5-rpm
 * stick-slip region.
 */
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#define MOTOR_SPEED_API_LIMIT_RPM      800.0f
#elif defined(FOC_PSI_IDENT_API400)
#if !defined(FOC_PSI_IDENT_DIAG) || !defined(FOC_PSI_IDENT_TRIP500)
#error 400rpm API requires the exclusive PSI diagnostic with 500rpm trip
#endif
#define MOTOR_SPEED_API_LIMIT_RPM      400.0f
#elif defined(FOC_FRICTION_HIGH_SPEED_GRID)
/* Explicit diagnostic command range only; independent 300rpm trip unchanged. */
#define MOTOR_SPEED_API_LIMIT_RPM      280.0f
#else
#define MOTOR_SPEED_API_LIMIT_RPM      250.0f
#endif
#define MOTOR_SPEED_TEST_RPM           100.0f
#if defined(FOC_RUNDOWN240_CANDIDATE)
#define MOTOR_SPEED_IQ_LIMIT_A           FOC_RUNDOWN240_IQ_LIMIT_A
#elif defined(FOC_SPEED_DYNAMIC_DIAG)
#define MOTOR_SPEED_IQ_LIMIT_A           0.50f
#else
#define MOTOR_SPEED_IQ_LIMIT_A           0.40f
#endif
#define MOTOR_SPEED_STALL_IQ_MIN_A       0.38f
#define MOTOR_SPEED_STALL_REF_MIN_RPM    20.0f
#define MOTOR_SPEED_STALL_TIMEOUT_S      2.0f

#ifndef MOTOR_DIRECT_IQ_LIMIT_A
#define MOTOR_DIRECT_IQ_LIMIT_A          0.20f
#endif
#if defined(FOC_TORQUE350_FIVE_SECOND)
_Static_assert((unsigned)(MOTOR_DIRECT_IQ_LIMIT_A*1000.0f+0.5f)==350U,"350mA command must not be silently clamped");
#endif
#if defined(FOC_TORQUE450_FIVE_SECOND)
_Static_assert((unsigned)(MOTOR_DIRECT_IQ_LIMIT_A*1000.0f+0.5f)==450U,"450mA command must not be silently clamped");
#endif

#define TIGHTEN_TEST_IDLE_1_MS             2000U

/*
 * First real tightening/contact-detection state machine.
 *
 * No screw is required for this validation. During RUNDOWN, use a light,
 * controlled friction load or soft brake fixture to imitate contact.
 *
 * CONTACT candidate:
 *   |DET| <= 10 rpm
 *   signed IqRef >= 0.30 A in tightening direction
 *   continuously for 250 ms
 *
 * These values are only initial detection thresholds. They are NOT a torque
 * calibration and they are not yet production tightening parameters.
 */
#define TIGHTEN_DIRECTION                    (+1.0f)
#define TIGHTEN_RUNDOWN_RPM                   ((float)TIGHTEN_RUNDOWN_DEFAULT_RPM)
#define TIGHTEN_CONTACT_DET_MAX_RPM           10.0f
#define TIGHTEN_CONTACT_IQREF_MIN_A            0.30f
#define TIGHTEN_CONTACT_CONFIRM_MS            250U
#include "tightening_rundown_guard.h"
static TightenRundownGuard tightening_rundown;

/*
 * Independent aborts for the manual-contact validation.
 */
#define TIGHTEN_RUNDOWN_TIMEOUT_MS           8000U
#define TIGHTEN_MAX_TRAVEL_DEG               3000.0f

/*
 * After contact is confirmed, command IDLE and wait for the rotor to settle
 * before entering the small direct-Iq seating/hold pulse.
 */
#define TIGHTEN_STOP_MAX_RPM                    2.0f
#define TIGHTEN_STOP_CONFIRM_MS                150U
#define TIGHTEN_STOP_TIMEOUT_MS               2000U

/*
 * First complete post-contact tightening sequence.
 *
 * These are q-axis CURRENT commands only.  They are NOT calibrated torque
 * values.  Actual N.m tightening requires torque calibration / Kt and
 * transmission validation.
 *
 * Sequence:
 *   SEATING      0.08 A / 300 ms
 *   TIGHTEN #1   0.10 A / 300 ms
 *   TIGHTEN #2   0.12 A / 300 ms
 *   TIGHTEN #3   0.15 A / 300 ms
 *   HOLD         0.15 A / 500 ms
 */
#define TIGHTEN_SEATING_IQ_A                    0.08f
#define TIGHTEN_STAGE_010_IQ_A                  0.10f
#define TIGHTEN_STAGE_012_IQ_A                  0.12f
#define TIGHTEN_STAGE_015_IQ_A                  0.15f

#define TIGHTEN_SEATING_MS                      300U
#define TIGHTEN_STAGE_010_MS                    300U
#define TIGHTEN_STAGE_012_MS                    300U
#define TIGHTEN_STAGE_015_MS                    300U
#define TIGHTEN_HOLD_MS                         500U

/*
 * Post-contact safety:
 * - if the load is released and the shaft accelerates, stop immediately
 * - if the shaft moves too far after contact, stop immediately
 */
#define TIGHTEN_TORQUE_SPEED_ABORT_RPM           30.0f
#define TIGHTEN_TORQUE_MAX_TRAVEL_DEG            90.0f

/* Five-cycle repeatability validation before torque calibration. */
#define TIGHTEN_REPEAT_CYCLES                     1U
#define TIGHTEN_CYCLE_PAUSE_MS                 3000U
#define TIGHTEN_REPEAT_RESTART_MAX_RPM            2.0f

/*
 * A single valid-parity AS5047P frame can still be electrically corrupted.
 * At 1 ms sampling, 600 rpm corresponds to about 164 raw counts/sample.
 * Reject isolated jumps above this value from the speed estimator.
 * Three consecutive implausible samples are treated as an encoder fault.
 */
#if defined(FOC_ENCODER_CONTROL_ADMISSION_FIX) && !defined(FOC_DOB_NORMAL_CONTROL)
#if !defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#error Encoder admission fix requires the reviewed high-speed mechanical A diagnostic
#endif
/* The manual 800rpm diagnostic cannot reject normal motion at the legacy
 * 600rpm ceiling. Use its ALREADY authorized 1000rpm envelope, not a second
 * unrelated magic threshold. Normal A/B and prior diagnostics stay at 600.
 * Filtered-speed overspeed, three bad samples, age and control watchdog remain. */
#define SPEED_INSTANT_PLAUSIBLE_RPM ((float)FOC_RUNDOWN240_TRIP_RPM)
#else
#define SPEED_INSTANT_PLAUSIBLE_RPM 600.0f
#endif
#define SPEED_GLITCH_STREAK_LIMIT   3U

#define FOC_DC_BUS_V                12.0f
#define FOC_VOLTAGE_LIMIT_V         0.80f
#define FOC_INTEGRATOR_LIMIT_V      0.75f
#if defined(FOC_VOLTAGE_X2_TRIAL)
#if !defined(FOC_SPEED_BUMPLESS) || !defined(FOC_LOADED_FSM_TRIAL) || !defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
#error Voltage X2 requires the complete protected SB2 one-shot trial
#endif
#undef FOC_VOLTAGE_LIMIT_V
#define FOC_VOLTAGE_LIMIT_V         1.60f
#endif
/* User-requested fault threshold; 4 A has NOT passed powered validation. */
#define FOC_CURRENT_TRIP_A          4.0f

#define ENCODER_UPDATE_PERIOD_MS    1U
#define PRINT_PERIOD_MS             137U

/* AS5047P encoder */
#define AS5047P_CPR 16384U
#define AS5047P_ANGLE_REG 0x3FFFU
#define POLE_PAIRS 10U
#define ENCODER_DIRECTION (-1)
#define ELECTRICAL_ZERO_RAW 10507U
#if defined(FOC_ANGLE_CHAIN_DIAG)
_Static_assert(POLE_PAIRS==10U && ENCODER_DIRECTION==-1 && ELECTRICAL_ZERO_RAW==10507U,
    "Angle diagnostic observer/report must match the existing mapping");
#endif

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */


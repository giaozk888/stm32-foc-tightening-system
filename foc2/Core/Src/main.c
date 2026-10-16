/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
/* UART_LAYER_1B: TX DMA ring + RX DMA circular + ProtocolTask */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include <ctype.h>
#include <stddef.h>
#include "FreeRTOS.h"
#include "task.h"
#include "uart_async.h"
#include "uart_rx_dma.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/*
 * Generic command interface used by the application layer.
 *
 * The application/TighteningTask never writes PWM directly.  It only selects
 * one of these motor modes and publishes a command.  MotorControlTask owns the
 * 1 kHz outer control; the ADC injected ISR continues to own the 20 kHz
 * current loop.
 */
typedef enum
{
    MOTOR_MODE_IDLE = 0,
    MOTOR_MODE_POSITION,
    MOTOR_MODE_SPEED,
    MOTOR_MODE_IQ
} MotorControlMode_t;

typedef enum
{
    TIGHTEN_STATE_IDLE_DELAY = 0,
    TIGHTEN_STATE_RUNDOWN,
    TIGHTEN_STATE_CONTACT_STOP,
    TIGHTEN_STATE_SEATING_IQ,
    TIGHTEN_STATE_TIGHTEN_010,
    TIGHTEN_STATE_TIGHTEN_012,
    TIGHTEN_STATE_TIGHTEN_015,
    TIGHTEN_STATE_HOLD,
    TIGHTEN_STATE_CYCLE_PAUSE,
    TIGHTEN_STATE_DONE,
    TIGHTEN_STATE_TIMEOUT,
    TIGHTEN_STATE_FAULT
} TighteningTestStage_t;

typedef enum
{
    TIGHTEN_OUTCOME_NONE = 0,
    TIGHTEN_OUTCOME_OK,
    TIGHTEN_OUTCOME_STOPPED,
    TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT,
    TIGHTEN_OUTCOME_STOP_TIMEOUT,
    TIGHTEN_OUTCOME_ABORT,
    TIGHTEN_OUTCOME_FAULT
} TighteningOutcome_t;

/*
 * ASCII Protocol V1 error codes.
 * Keep these numeric values stable once an external client depends on them.
 */
typedef enum
{
    PROTO_ERR_UNKNOWN_COMMAND = 100,
    PROTO_ERR_BUSY            = 101,
    PROTO_ERR_LINE_TOO_LONG   = 102,
    PROTO_ERR_BAD_ARGUMENT    = 103,
    PROTO_ERR_NOT_READY       = 104,
    PROTO_ERR_FAULT           = 105,
    PROTO_ERR_ROTOR_MOVING    = 106,
    PROTO_ERR_FLASH           = 107,
    PROTO_ERR_NO_VALID_PARAMS = 108
} ProtocolError_t;

typedef struct
{
    float command_A;
    float iq_sum_A;
    float iq_max_A;
    float ctrl_max_abs_rpm;
    float det_sum_abs_rpm;
    float start_position_deg;
    float end_position_deg;
    uint32_t sample_count;
} TighteningStageResult_t;

typedef struct
{
    uint8_t valid;
    float rundown_travel_deg;
    float post_travel_deg;

    float seating_iq_avg_A;
    float tighten1_iq_avg_A;
    float tighten2_iq_avg_A;
    float tighten3_iq_avg_A;
    float hold_iq_avg_A;

    float seating_iq_max_A;
    float tighten3_iq_max_A;
    float hold_iq_max_A;
} TighteningCycleSummary_t;

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define PI_F 3.14159265358979323846f
#define TWO_PI_F 6.28318530717958647692f

#define ADC_VREF_MV 3300U
#define ADC_FULL_SCALE 4095U
#define CURRENT_GAIN_MV_PER_A 120U
#define ADC_MEDIAN_SAMPLES 5U
#define ADC_ZERO_CAL_SAMPLES 500U

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
 * The legacy position-sequence constants below are intentionally retained
 * because the generated Cube main.c still contains unreachable historical
 * bring-up code after vTaskStartScheduler().  The running RTOS path no longer
 * uses that old demo state machine.
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
#define SPEED_OVERSPEED_RPM         300.0f

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
#define MOTOR_SPEED_API_LIMIT_RPM      250.0f
#define MOTOR_SPEED_TEST_RPM           100.0f
#define MOTOR_SPEED_IQ_LIMIT_A           0.40f
#define MOTOR_SPEED_STALL_IQ_MIN_A       0.38f
#define MOTOR_SPEED_STALL_REF_MIN_RPM    20.0f
#define MOTOR_SPEED_STALL_TIMEOUT_S      2.0f

#define MOTOR_DIRECT_IQ_LIMIT_A          0.15f

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
#define TIGHTEN_RUNDOWN_RPM                   80.0f
#define TIGHTEN_CONTACT_DET_MAX_RPM           10.0f
#define TIGHTEN_CONTACT_IQREF_MIN_A            0.30f
#define TIGHTEN_CONTACT_CONFIRM_MS            250U

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
#define SPEED_INSTANT_PLAUSIBLE_RPM 600.0f
#define SPEED_GLITCH_STREAK_LIMIT   3U

#define FOC_DC_BUS_V                12.0f
#define FOC_VOLTAGE_LIMIT_V         0.80f
#define FOC_INTEGRATOR_LIMIT_V      0.75f
#define FOC_CURRENT_TRIP_A          2.0f

#define ENCODER_UPDATE_PERIOD_MS    1U
#define PRINT_PERIOD_MS             137U

/* AS5047P encoder */
#define AS5047P_CPR 16384U
#define AS5047P_ANGLE_REG 0x3FFFU
#define POLE_PAIRS 10U
#define ENCODER_DIRECTION (-1)
#define ELECTRICAL_ZERO_RAW 10507U

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
ADC_HandleTypeDef hadc1;
ADC_HandleTypeDef hadc2;

UART_HandleTypeDef hlpuart1;

SPI_HandleTypeDef hspi1;

TIM_HandleTypeDef htim1;

/* USER CODE BEGIN PV */

/*
 * Temporary FreeRTOS bring-up flag.
 * SysTick forwards ticks to the kernel only after the first task starts.
 */
volatile uint8_t g_rtos_started = 0U;

static uint16_t iu_zero_raw = 0U;
static uint16_t iv_zero_raw = 0U;
static uint16_t iw_zero_raw = 0U;

static volatile uint16_t iu_inj_raw = 0U;
static volatile uint16_t iv_inj_raw = 0U;
static volatile uint16_t iw_inj_raw = 0U;
static volatile uint32_t injected_seq_count = 0U;
static volatile uint8_t adc_fault = 0U;

/* PWM-ON dynamic zero calibration state */
static volatile uint8_t run_zero_cal_active = 0U;
static volatile uint8_t run_zero_cal_done = 0U;

static volatile uint32_t run_zero_sum_u = 0U;
static volatile uint32_t run_zero_sum_v = 0U;
static volatile uint32_t run_zero_sum_w = 0U;

static volatile uint32_t run_zero_valid_count = 0U;
static volatile uint32_t run_zero_reject_count = 0U;

/* Runtime current-frame filter statistics/state */
static volatile uint8_t current_filter_enable = 0U;
static volatile uint32_t current_valid_count = 0U;
static volatile uint32_t current_reject_count = 0U;
static volatile uint32_t current_reject_streak = 0U;
static volatile int32_t current_last_rejected_sum_counts = 0;

/*
 * Previous PHYSICAL ADC sample, used only for one-sample jump detection.
 * Important: this is updated even when a frame is rejected, otherwise one
 * rejected sample can make the filter compare forever against stale data.
 */
static volatile uint16_t current_prev_raw_u = 0U;
static volatile uint16_t current_prev_raw_v = 0U;
static volatile uint8_t current_prev_raw_valid = 0U;

/*
 * 3-sample median post-filter.
 *
 * The proven raw-to-raw step reject remains the FIRST gate.  We do not use
 * a stale "last accepted" sample as a hard gate, because that can latch the
 * filter after one disturbance.  Median-of-3 only cleans the frames that
 * already passed the step gate.
 */
static uint16_t current_med_u[3] = {0U, 0U, 0U};
static uint16_t current_med_v[3] = {0U, 0U, 0U};
static uint8_t current_med_index = 0U;
static uint8_t current_med_count = 0U;

/* Encoder / position / speed-estimator state. */
static volatile uint16_t encoder_raw = 0U;
static volatile float encoder_theta_e = 0.0f;       /* latest measured electrical angle */
static volatile float encoder_theta_e_pred = 0.0f;  /* 20 kHz predicted electrical angle */
static volatile float encoder_speed_rpm = 0.0f;     /* mechanical speed; +RAW = positive */
static volatile float encoder_omega_e_rad_s = 0.0f;
static volatile uint8_t encoder_valid = 0U;
static volatile uint32_t encoder_error_count = 0U;
static uint16_t encoder_prev_raw = 0U;
static uint8_t encoder_prev_valid = 0U;
static float encoder_speed_dt_accum_s = 0.0f;
static volatile uint32_t encoder_speed_glitch_count = 0U;
static volatile uint32_t encoder_speed_glitch_streak = 0U;

/* 1 ms instantaneous speed diagnostic. */
static volatile float encoder_rpm_instant = 0.0f;

/*
 * 50 ms average speed for future seating/load detection.
 * This is deliberately independent of the Speed PI feedback path.
 */
static volatile float encoder_speed_detect_rpm = 0.0f;
static int32_t encoder_speed_detect_counts = 0;
static float encoder_speed_detect_dt_s = 0.0f;
static uint32_t encoder_speed_detect_samples = 0U;

/*
 * Unwrapped mechanical position, relative to the rotor position at FOC enable.
 * Positive position uses the same verified sign convention as positive speed:
 * ENCODER_DIRECTION=-1 means decreasing AS5047P RAW is positive motion.
 */
static volatile float encoder_position_deg = 0.0f;

/* Position outer-loop state. */
static volatile float position_target_deg = 0.0f;
static volatile float position_error_deg = 0.0f;
static volatile float position_speed_cmd_rpm = 0.0f;

/*
 * Position deadband hysteresis state.
 *
 * 1: currently considered settled/in deadband
 * 0: position loop is active
 */
static volatile uint8_t position_deadband_active = 1U;

/*
 * Final-stage hybrid active-hold state.
 *
 * STG0..STG4: active_hold_enable = 0 -> normal position/speed/current cascade.
 * STG5:
 *   active_hold_enable = 1 inside the <=2 deg hold region;
 *   active_hold_enable = 0 outside the >=3 deg exit boundary.
 *
 * Between 2 and 3 deg the current mode is retained (hysteresis).
 */
static volatile uint8_t active_hold_enable = 0U;
static volatile float active_hold_iq_cmd_A = 0.0f;

/*
 * Position-sequence stage must be file-scope because FOC_EncoderSpeedUpdate()
 * uses it to select the gentler STG5 cascade return limits.
 */
static uint32_t speed_profile_stage = 0U;

/*
 * Generic command mailbox.
 *
 * TighteningTask is the application-layer writer.
 * MotorControlTask / FOC_EncoderSpeedUpdate are the control-layer readers.
 *
 * 32-bit aligned enum/float accesses are atomic on Cortex-M4; the command
 * value is written before the mode so the mode acts as the commit point.
 */
static volatile MotorControlMode_t motor_control_mode = MOTOR_MODE_IDLE;
static volatile float motor_position_command_deg = 0.0f;
static volatile float motor_speed_command_rpm = 0.0f;
static volatile float motor_iq_command_A = 0.0f;
static volatile uint8_t motor_position_active_hold = 0U;

static volatile TighteningTestStage_t tightening_test_stage =
    TIGHTEN_STATE_IDLE_DELAY;
static volatile uint32_t tightening_test_elapsed_ms = 0U;

/* Tightening/contact-detection diagnostics. */
static volatile uint32_t tightening_contact_candidate_ms = 0U;
static volatile uint8_t tightening_contact_condition = 0U;
static volatile float tightening_start_position_deg = 0.0f;
static volatile float tightening_travel_deg = 0.0f;
static volatile float tightening_contact_position_deg = 0.0f;
static volatile float tightening_post_contact_travel_deg = 0.0f;
static volatile float tightening_drive_iqref_A = 0.0f;

/*
 * Set only after the 250 ms contact criterion is truly confirmed.
 * This prevents STOPPED/RUNDOWN_TIMEOUT results from printing a fake
 * "Contact angle".
 */
static volatile uint8_t tightening_contact_confirmed = 0U;


/*
 * PARAMETER SYSTEM V1
 *
 * Tightening recipe values are now runtime parameters stored in RAM.
 * This stage intentionally does NOT write Flash.
 *
 * Reset/power-cycle => safe defaults below.
 * SET is rejected while a tightening cycle is active.
 *
 * Integer units keep the ASCII protocol simple:
 *   speed   : rpm
 *   current : mA
 *   time    : ms
 *   travel  : mechanical deg
 */
typedef struct
{
    uint32_t rundown_rpm;
    uint32_t contact_rpm;
    uint32_t contact_iq_mA;
    uint32_t contact_ms;
    uint32_t rundown_timeout_ms;
    uint32_t max_travel_deg;

    uint32_t seating_iq_mA;
    uint32_t t1_iq_mA;
    uint32_t t2_iq_mA;
    uint32_t t3_iq_mA;
    uint32_t hold_iq_mA;

    uint32_t seating_ms;
    uint32_t t1_ms;
    uint32_t t2_ms;
    uint32_t t3_ms;
    uint32_t hold_ms;

    uint32_t torque_abort_rpm;
    uint32_t post_travel_max_deg;
} TightenParams_t;

#define PARAM_FLASH_ADDRESS       (0x0807F800UL)
#define PARAM_FLASH_BANK          FLASH_BANK_2
#define PARAM_FLASH_PAGE          (127U)
#define PARAM_FLASH_MAGIC         (0x5041524DUL)
#define PARAM_FLASH_VERSION       (1UL)

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t payload_size;
    uint32_t reserved0;
    TightenParams_t params;
    uint32_t crc32;
    uint32_t reserved1;
} TightenParamsFlashRecord_t;

typedef enum
{
    PARAM_FLASH_LOAD_OK = 0,
    PARAM_FLASH_LOAD_EMPTY,
    PARAM_FLASH_LOAD_INVALID,
    PARAM_FLASH_LOAD_HAL_ERROR
} TightenParamsFlashLoadStatus_t;

static const TightenParams_t tighten_params_defaults =
{
    .rundown_rpm         = 80U,
    .contact_rpm         = 10U,
    .contact_iq_mA       = 300U,
    .contact_ms          = 250U,
    .rundown_timeout_ms  = 8000U,
    .max_travel_deg      = 3000U,

    .seating_iq_mA       = 80U,
    .t1_iq_mA            = 100U,
    .t2_iq_mA            = 120U,
    .t3_iq_mA            = 150U,
    .hold_iq_mA          = 150U,

    .seating_ms          = 300U,
    .t1_ms               = 300U,
    .t2_ms               = 300U,
    .t3_ms               = 300U,
    .hold_ms             = 500U,

    .torque_abort_rpm    = 30U,
    .post_travel_max_deg = 90U
};

static TightenParams_t tighten_params =
{
    .rundown_rpm         = 80U,
    .contact_rpm         = 10U,
    .contact_iq_mA       = 300U,
    .contact_ms          = 250U,
    .rundown_timeout_ms  = 8000U,
    .max_travel_deg      = 3000U,

    .seating_iq_mA       = 80U,
    .t1_iq_mA            = 100U,
    .t2_iq_mA            = 120U,
    .t3_iq_mA            = 150U,
    .hold_iq_mA          = 150U,

    .seating_ms          = 300U,
    .t1_ms               = 300U,
    .t2_ms               = 300U,
    .t3_ms               = 300U,
    .hold_ms             = 500U,

    .torque_abort_rpm    = 30U,
    .post_travel_max_deg = 90U
};
static volatile uint8_t tighten_params_flash_valid = 0U;
static volatile uint8_t tighten_params_dirty = 0U;
static volatile uint32_t tighten_params_last_crc32 = 0U;


/*
 * Per-stage tightening result recorder.
 * TighteningTask samples at 100 Hz (10 ms/sample), independently of the
 * slower 500 ms MonitorTask UART snapshots.
 */
static TighteningStageResult_t tighten_result_seating;
static TighteningStageResult_t tighten_result_010;
static TighteningStageResult_t tighten_result_012;
static TighteningStageResult_t tighten_result_015;
static TighteningStageResult_t tighten_result_hold;
static volatile uint8_t tightening_result_printed = 0U;

static TighteningCycleSummary_t
    tightening_cycle_summary[TIGHTEN_REPEAT_CYCLES];

static volatile uint32_t tightening_cycle_number = 1U;
static volatile uint32_t tightening_cycle_ok_count = 0U;

/*
 * ProtocolTask -> TighteningTask command mailbox.
 * Only TighteningTask changes the application state machine.
 */
static volatile uint8_t tightening_start_request = 0U;
static volatile uint8_t tightening_stop_request = 0U;
static volatile uint8_t tightening_result_request = 0U;

/*
 * Protocol V2 correlation IDs.
 *
 * ProtocolTask writes the request ID before setting the corresponding
 * mailbox flag. TighteningTask consumes the flag + ID pair.
 *
 * cycle_request_id remains attached to the latest START cycle so later
 * RESULT queries can tell the host which START produced the stored result.
 */
static volatile uint32_t tightening_start_request_id = 0U;
static volatile uint32_t tightening_stop_request_id = 0U;
static volatile uint32_t tightening_result_request_id = 0U;
static volatile uint32_t tightening_cycle_request_id = 0U;

static volatile TighteningOutcome_t tightening_last_outcome =
    TIGHTEN_OUTCOME_NONE;

/*
 * Position-command direction reversal tracking.
 *
 * +1: target lies in positive direction
 * -1: target lies in negative direction
 *  0: no previous non-zero command direction recorded yet
 *
 * When the position error crosses through zero and emerges on the opposite
 * side of the deadband, the old speed-PI integral is cleared so a stale
 * positive torque cannot fight a new negative command (and vice versa).
 */
static volatile int8_t position_error_sign_prev = 0;
static volatile uint32_t position_direction_reset_count = 0U;

/* Speed PI state. */
static volatile float speed_target_rpm = SPEED_REF_RPM;
static volatile float speed_ref_rpm = SPEED_REF_RPM; /* ramped reference */
static volatile float speed_integrator_A = 0.0f;
static volatile uint8_t speed_integrator_bleed_active = 0U;
static volatile uint8_t speed_overspeed_bleed_active = 0U;

/* Speed-PI diagnostic values printed over UART. */
static volatile float speed_error_rpm = 0.0f;
static volatile float speed_p_term_A = 0.0f;

/*
 * Time-weighted speed diagnostics.
 *
 * We accumulate at every accepted encoder-speed update instead of observing
 * only one instantaneous sample every UART print.  This avoids the previous
 * 150 rpm / 200 ms phase-lock problem.
 */
static float speed_diag_time_s = 0.0f;
static float speed_diag_speed_integral = 0.0f; /* rpm*s */
static float speed_diag_error_integral = 0.0f; /* rpm*s */
static float speed_diag_min_rpm = 0.0f;
static float speed_diag_max_rpm = 0.0f;
static uint8_t speed_diag_valid = 0U;

/* FOC fault diagnostics. */
static volatile uint32_t foc_fault_reason = 0U;
/* reason: 1=current trip, 2=encoder, 3=overspeed, 4=position/speed stall */
static volatile int32_t foc_trip_iu_mA = 0;
static volatile int32_t foc_trip_iv_mA = 0;
static volatile int32_t foc_trip_iw_mA = 0;

/* Stall detector state / trip snapshot. */
static volatile float stall_timer_s = 0.0f;
static volatile float stall_trip_position_deg = 0.0f;
static volatile float stall_trip_target_deg = 0.0f;
static volatile float stall_trip_ref_rpm = 0.0f;
static volatile float stall_trip_speed_rpm = 0.0f;

/* First closed-loop FOC current controller state. */
static volatile uint8_t foc_enable = 0U;
static volatile uint8_t foc_fault = 0U;
static volatile uint32_t foc_control_count = 0U;

static volatile float foc_id_ref_A = FOC_ID_REF_A;
static volatile float foc_iq_ref_A = 0.0f;

static volatile float foc_id_A = 0.0f;
static volatile float foc_iq_A = 0.0f;
static volatile float foc_vd_V = 0.0f;
static volatile float foc_vq_V = 0.0f;

static volatile float foc_int_d_V = 0.0f;
static volatile float foc_int_q_V = 0.0f;

static volatile float foc_duty_u = 0.5f;
static volatile float foc_duty_v = 0.5f;
static volatile float foc_duty_w = 0.5f;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM1_Init(void);
static void MX_SPI1_Init(void);
static void MX_LPUART1_UART_Init(void);
static void MX_ADC1_Init(void);
static void MX_ADC2_Init(void);
/* USER CODE BEGIN PFP */

/* RTOS task dependencies / forward declarations. */
static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw);
static float Encoder_ElectricalAngleRad(uint16_t raw);
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s);
static void PowerStage_Disable(void);
static void PowerStage_Enable(void);
static void PWM_SetDuty(float du, float dv, float dw);
static void PWM_StopAll(void);
static float ClampFloat(float x, float lo, float hi);
static void FormatSignedX100(char *buf, size_t n, int32_t x100);
static void MotorControlTask(void *argument);
static void TighteningTask(void *argument);
static void ProtocolTask(void *argument);
static void MonitorTask(void *argument);
static uint8_t Tightening_IsBusy(void);
static const char *TighteningOutcome_Name(TighteningOutcome_t outcome);
static void Protocol_HandleLine(char *line);
static void Protocol_PrintStatus(uint32_t request_id);
static uint8_t TightenParams_Validate(const TightenParams_t *params);
static void TightenParams_RestoreDefaults(void);
static uint32_t TightenParams_Crc32(const uint8_t *data, size_t length);
static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void);
static uint8_t TightenParams_SaveToFlash(void);
static void TighteningResult_Reset(TighteningStageResult_t *r,
                                   float command_A);
static void TighteningResult_Sample(TighteningStageResult_t *r);
static void TighteningResult_PrintStage(const char *name,
                                        const TighteningStageResult_t *r);
static void TighteningResult_PrintSummary(const char *result_text);
static float TighteningResult_AvgIq(
    const TighteningStageResult_t *r);
static void TighteningRepeat_ResetCurrentCycle(void);
static void TighteningRepeat_StoreCurrentCycle(void);
static void TighteningRepeat_PrintAggregate(void);

static void MotorControl_SetIdle(void);
static void MotorControl_SetSpeed(float rpm);
static void MotorControl_SetPosition(float position_deg, uint8_t active_hold);
static void MotorControl_SetIq(float iq_A);
static const char *MotorControl_ModeName(MotorControlMode_t mode);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void UART_SendString(const char *str)
{
    size_t len;

    if (str == NULL)
    {
        return;
    }

    len = strlen(str);

    /*
     * Before the scheduler/async backend exists, keep the proven blocking
     * path for the two boot messages.
     *
     * Once StartupTask initializes UART_Async, all normal application logging
     * becomes enqueue-only and no longer waits for the physical UART.
     */
    if ((g_rtos_started != 0U) &&
        (UART_Async_IsReady() != 0U))
    {
        (void)UART_Async_Write((const uint8_t *)str, len);
        return;
    }

    HAL_UART_Transmit(&hlpuart1,
                      (uint8_t *)str,
                      (uint16_t)len,
                      HAL_MAX_DELAY);
}

/*
 * First real-time control task skeleton.
 *
 * This task runs at 1 kHz using vTaskDelayUntil(), which gives a fixed
 * absolute period suitable for later encoder/speed/position control.
 *
 * IMPORTANT FOR THIS STEP:
 * - The power stage remains disabled.
 * - The original 20 kHz current-loop FOC code is not moved yet.
 * - This task only proves stable 1 kHz periodic scheduling.
 */
static void MotorControl_SetIdle(void)
{
    motor_position_command_deg = encoder_position_deg;
    motor_speed_command_rpm = 0.0f;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = 0U;

    /*
     * Publish mode last.  At worst the 1 kHz reader sees the previous mode
     * for one additional cycle; it will never see a new mode with stale
     * command data.
     */
    motor_control_mode = MOTOR_MODE_IDLE;
}


static void MotorControl_SetSpeed(float rpm)
{
    rpm = ClampFloat(rpm,
                     -MOTOR_SPEED_API_LIMIT_RPM,
                      MOTOR_SPEED_API_LIMIT_RPM);

    motor_speed_command_rpm = rpm;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = 0U;
    motor_control_mode = MOTOR_MODE_SPEED;
}


static void MotorControl_SetPosition(float position_deg, uint8_t active_hold)
{
    motor_position_command_deg = position_deg;
    motor_speed_command_rpm = 0.0f;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = (active_hold != 0U) ? 1U : 0U;
    motor_control_mode = MOTOR_MODE_POSITION;
}


static void MotorControl_SetIq(float iq_A)
{
    iq_A = ClampFloat(iq_A,
                      -MOTOR_DIRECT_IQ_LIMIT_A,
                       MOTOR_DIRECT_IQ_LIMIT_A);

    motor_iq_command_A = iq_A;
    motor_speed_command_rpm = 0.0f;
    motor_position_active_hold = 0U;
    motor_control_mode = MOTOR_MODE_IQ;
}


static const char *MotorControl_ModeName(MotorControlMode_t mode)
{
    switch (mode)
    {
        case MOTOR_MODE_POSITION: return "POS";
        case MOTOR_MODE_SPEED:    return "SPD";
        case MOTOR_MODE_IQ:       return "IQ";
        case MOTOR_MODE_IDLE:
        default:                  return "IDLE";
    }
}


/*
 * High-priority deterministic 1 kHz motor-control task.
 *
 * This task no longer owns the old 0 -> +90 -> 0 -> -90 -> 0 demo state
 * machine.  It is now a reusable motor-control service.  The application layer
 * selects POSITION / SPEED / IQ / IDLE through the generic command mailbox.
 *
 * The 20 kHz current loop remains entirely inside the ADC injected ISR.
 */
static void MotorControlTask(void *argument)
{
    TickType_t last_wake_time;

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendString(
        "MotorControlTask started @ 1kHz\r\n"
        "Generic modes: IDLE / POSITION / SPEED / IQ\r\n"
        "20kHz current loop remains in ADC injected ISR\r\n");

    for (;;)
    {
        if ((adc_fault == 0U) && (foc_fault == 0U))
        {
            (void)FOC_EncoderSpeedUpdate(0.001f);
        }

        /*
         * Immediate safe-state reaction.  The lower-priority application task
         * cannot override a latched hardware/control fault.
         */
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            foc_enable = 0U;
            foc_iq_ref_A = 0.0f;

            motor_speed_command_rpm = 0.0f;
            motor_iq_command_A = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;
            speed_integrator_A = 0.0f;
            stall_timer_s = 0.0f;

            motor_control_mode = MOTOR_MODE_IDLE;

            PowerStage_Disable();
            PWM_SetDuty(0.5f, 0.5f, 0.5f);
        }

        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
    }
}


/*
 * First application-layer TighteningTask.
 *
 * This is NOT yet the final tightening algorithm.  Its purpose is to validate
 * the new separation between:
 *
 *   application command
 *        ->
 *   1 kHz motor-control service
 *        ->
 *   20 kHz current loop
 *
 * Tightening application:
 *   RUNDOWN -> CONTACT -> STOP -> SEATING -> TIGHTENING -> HOLD -> DONE
 *   Each post-contact IQ stage is sampled at 100 Hz for a final result report.
 */

static void TighteningResult_Reset(TighteningStageResult_t *r,
                                   float command_A)
{
    if (r == NULL)
    {
        return;
    }

    r->command_A = command_A;
    r->iq_sum_A = 0.0f;
    r->iq_max_A = 0.0f;
    r->ctrl_max_abs_rpm = 0.0f;
    r->det_sum_abs_rpm = 0.0f;
    r->start_position_deg = encoder_position_deg;
    r->end_position_deg = encoder_position_deg;
    r->sample_count = 0U;
}


static void TighteningResult_Sample(TighteningStageResult_t *r)
{
    float iq_drive_A;
    float ctrl_abs_rpm;
    float det_abs_rpm;

    if (r == NULL)
    {
        return;
    }

    iq_drive_A = TIGHTEN_DIRECTION * foc_iq_A;
    ctrl_abs_rpm = fabsf(encoder_speed_rpm);
    det_abs_rpm = fabsf(encoder_speed_detect_rpm);

    r->iq_sum_A += iq_drive_A;

    if ((r->sample_count == 0U) ||
        (iq_drive_A > r->iq_max_A))
    {
        r->iq_max_A = iq_drive_A;
    }

    if (ctrl_abs_rpm > r->ctrl_max_abs_rpm)
    {
        r->ctrl_max_abs_rpm = ctrl_abs_rpm;
    }

    r->det_sum_abs_rpm += det_abs_rpm;
    r->end_position_deg = encoder_position_deg;
    r->sample_count++;
}


static void TighteningResult_PrintStage(const char *name,
                                        const TighteningStageResult_t *r)
{
    char msg[256];
    float iq_avg_A = 0.0f;
    float det_avg_abs_rpm = 0.0f;
    float delta_deg = 0.0f;
    uint32_t duration_ms = 0U;

    int32_t cmd_mA;
    int32_t iq_avg_mA;
    int32_t iq_max_mA;
    int32_t ctrl_max_x10;
    int32_t det_avg_x10;
    int32_t delta_x100;

    if ((name == NULL) || (r == NULL))
    {
        return;
    }

    if (r->sample_count > 0U)
    {
        iq_avg_A =
            r->iq_sum_A / (float)r->sample_count;
        det_avg_abs_rpm =
            r->det_sum_abs_rpm / (float)r->sample_count;
        duration_ms = r->sample_count * 10U;
    }

    delta_deg =
        TIGHTEN_DIRECTION *
        (r->end_position_deg - r->start_position_deg);

    cmd_mA = (int32_t)(r->command_A * 1000.0f);
    iq_avg_mA = (int32_t)(iq_avg_A * 1000.0f);
    iq_max_mA = (int32_t)(r->iq_max_A * 1000.0f);
    ctrl_max_x10 = (int32_t)(r->ctrl_max_abs_rpm * 10.0f);
    det_avg_x10 = (int32_t)(det_avg_abs_rpm * 10.0f);
    delta_x100 = (int32_t)(delta_deg * 100.0f);

    snprintf(
        msg,
        sizeof(msg),
        "%-10s Cmd=%ldmA IqAvg=%ldmA IqMax=%ldmA "
        "CtrlMax=%ld.%01ldrpm DetAvg=%ld.%01ldrpm "
        "dAng=%ld.%02lddeg T=%lums N=%lu\r\n",
        name,
        (long)cmd_mA,
        (long)iq_avg_mA,
        (long)iq_max_mA,
        (long)(ctrl_max_x10 / 10),
        (long)labs(ctrl_max_x10 % 10),
        (long)(det_avg_x10 / 10),
        (long)labs(det_avg_x10 % 10),
        (long)(delta_x100 / 100),
        (long)labs(delta_x100 % 100),
        (unsigned long)duration_ms,
        (unsigned long)r->sample_count);

    UART_SendString(msg);
}


static void TighteningResult_PrintSummary(const char *result_text)
{
    char msg[256];

    UART_SendString(
        "\r\n"
        "========== TIGHTEN RESULT ==========\r\n");

    snprintf(
        msg,
        sizeof(msg),
        "Start request : %lu\r\n",
        (unsigned long)tightening_cycle_request_id);
    UART_SendString(msg);

    if (tightening_contact_confirmed != 0U)
    {
        int32_t contact_x100 =
            (int32_t)(tightening_contact_position_deg * 100.0f);
        int32_t post_x100 =
            (int32_t)(tightening_post_contact_travel_deg * 100.0f);

        snprintf(
            msg,
            sizeof(msg),
            "RESULT        : %s\r\n"
            "Contact angle : %ld.%02ld deg\r\n"
            "Post travel   : %ld.%02ld deg\r\n",
            (result_text != NULL) ? result_text : "UNKNOWN",
            (long)(contact_x100 / 100),
            (long)labs(contact_x100 % 100),
            (long)(post_x100 / 100),
            (long)labs(post_x100 % 100));
    }
    else
    {
        snprintf(
            msg,
            sizeof(msg),
            "RESULT        : %s\r\n"
            "Contact angle : N/A\r\n"
            "Post travel   : N/A\r\n",
            (result_text != NULL) ? result_text : "UNKNOWN");
    }

    UART_SendString(msg);

    TighteningResult_PrintStage("SEATING", &tighten_result_seating);
    TighteningResult_PrintStage("TIGHTEN#1", &tighten_result_010);
    TighteningResult_PrintStage("TIGHTEN#2", &tighten_result_012);
    TighteningResult_PrintStage("TIGHTEN#3", &tighten_result_015);
    TighteningResult_PrintStage("HOLD", &tighten_result_hold);

    UART_SendString(
        "NOTE: Iq values are electrical q-axis current, NOT calibrated N.m\r\n"
        "====================================\r\n\r\n");
}



static float TighteningResult_AvgIq(
    const TighteningStageResult_t *r)
{
    if ((r == NULL) || (r->sample_count == 0U))
    {
        return 0.0f;
    }

    return r->iq_sum_A / (float)r->sample_count;
}


static void TighteningRepeat_ResetCurrentCycle(void)
{
    tightening_contact_candidate_ms = 0U;
    tightening_contact_condition = 0U;
    tightening_contact_confirmed = 0U;
    tightening_test_elapsed_ms = 0U;

    tightening_start_position_deg = encoder_position_deg;
    tightening_travel_deg = 0.0f;

    tightening_contact_position_deg = encoder_position_deg;
    tightening_post_contact_travel_deg = 0.0f;

    tightening_drive_iqref_A = 0.0f;
    tightening_result_printed = 0U;

    TighteningResult_Reset(
        &tighten_result_seating,
        (float)tighten_params.seating_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_010,
        (float)tighten_params.t1_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_012,
        (float)tighten_params.t2_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_015,
        (float)tighten_params.t3_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_hold,
        (float)tighten_params.hold_iq_mA / 1000.0f);
}


static void TighteningRepeat_StoreCurrentCycle(void)
{
    TighteningCycleSummary_t *s;
    uint32_t index;

    if ((tightening_cycle_number == 0U) ||
        (tightening_cycle_number > TIGHTEN_REPEAT_CYCLES))
    {
        return;
    }

    index = tightening_cycle_number - 1U;
    s = &tightening_cycle_summary[index];

    memset(s, 0, sizeof(*s));

    s->valid = 1U;
    s->rundown_travel_deg = tightening_travel_deg;
    s->post_travel_deg = tightening_post_contact_travel_deg;

    s->seating_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_seating);
    s->tighten1_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_010);
    s->tighten2_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_012);
    s->tighten3_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_015);
    s->hold_iq_avg_A =
        TighteningResult_AvgIq(&tighten_result_hold);

    s->seating_iq_max_A = tighten_result_seating.iq_max_A;
    s->tighten3_iq_max_A = tighten_result_015.iq_max_A;
    s->hold_iq_max_A = tighten_result_hold.iq_max_A;

    tightening_cycle_ok_count++;
}


static void TighteningRepeat_PrintAggregate(void)
{
    char msg[320];
    uint32_t i;
    uint32_t n = 0U;

    float post_sum = 0.0f;
    float post_min = 1.0e9f;
    float post_max = -1.0e9f;

    float seat_sum = 0.0f;
    float t1_sum = 0.0f;
    float t2_sum = 0.0f;
    float t3_sum = 0.0f;
    float hold_sum = 0.0f;

    float hold_peak_max = 0.0f;

    UART_SendString(
        "\r\n"
        "========== 5-CYCLE REPEATABILITY ==========\r\n");

    for (i = 0U; i < TIGHTEN_REPEAT_CYCLES; i++)
    {
        const TighteningCycleSummary_t *s =
            &tightening_cycle_summary[i];

        int32_t post_x100;
        int32_t seat_mA;
        int32_t t1_mA;
        int32_t t2_mA;
        int32_t t3_mA;
        int32_t hold_mA;
        int32_t hold_peak_mA;

        if (s->valid == 0U)
        {
            continue;
        }

        n++;

        post_sum += s->post_travel_deg;
        if (s->post_travel_deg < post_min)
        {
            post_min = s->post_travel_deg;
        }
        if (s->post_travel_deg > post_max)
        {
            post_max = s->post_travel_deg;
        }

        seat_sum += s->seating_iq_avg_A;
        t1_sum += s->tighten1_iq_avg_A;
        t2_sum += s->tighten2_iq_avg_A;
        t3_sum += s->tighten3_iq_avg_A;
        hold_sum += s->hold_iq_avg_A;

        if (s->hold_iq_max_A > hold_peak_max)
        {
            hold_peak_max = s->hold_iq_max_A;
        }

        post_x100 =
            (int32_t)(s->post_travel_deg * 100.0f);
        seat_mA =
            (int32_t)(s->seating_iq_avg_A * 1000.0f);
        t1_mA =
            (int32_t)(s->tighten1_iq_avg_A * 1000.0f);
        t2_mA =
            (int32_t)(s->tighten2_iq_avg_A * 1000.0f);
        t3_mA =
            (int32_t)(s->tighten3_iq_avg_A * 1000.0f);
        hold_mA =
            (int32_t)(s->hold_iq_avg_A * 1000.0f);
        hold_peak_mA =
            (int32_t)(s->hold_iq_max_A * 1000.0f);

        snprintf(
            msg,
            sizeof(msg),
            "Cycle %lu: Post=%ld.%02lddeg "
            "IqAvg[%ld,%ld,%ld,%ld,%ld]mA "
            "HoldPeak=%ldmA\r\n",
            (unsigned long)(i + 1U),
            (long)(post_x100 / 100),
            (long)labs(post_x100 % 100),
            (long)seat_mA,
            (long)t1_mA,
            (long)t2_mA,
            (long)t3_mA,
            (long)hold_mA,
            (long)hold_peak_mA);

        UART_SendString(msg);
    }

    if (n > 0U)
    {
        int32_t post_avg_x100 =
            (int32_t)((post_sum / (float)n) * 100.0f);
        int32_t post_min_x100 =
            (int32_t)(post_min * 100.0f);
        int32_t post_max_x100 =
            (int32_t)(post_max * 100.0f);

        int32_t seat_avg_mA =
            (int32_t)((seat_sum / (float)n) * 1000.0f);
        int32_t t1_avg_mA =
            (int32_t)((t1_sum / (float)n) * 1000.0f);
        int32_t t2_avg_mA =
            (int32_t)((t2_sum / (float)n) * 1000.0f);
        int32_t t3_avg_mA =
            (int32_t)((t3_sum / (float)n) * 1000.0f);
        int32_t hold_avg_mA =
            (int32_t)((hold_sum / (float)n) * 1000.0f);
        int32_t hold_peak_mA =
            (int32_t)(hold_peak_max * 1000.0f);

        snprintf(
            msg,
            sizeof(msg),
            "SUCCESS       : %lu/%u cycles\r\n"
            "PostTravel    : avg=%ld.%02lddeg "
            "min=%ld.%02lddeg max=%ld.%02lddeg\r\n"
            "IqAvg mean mA : SEAT=%ld T1=%ld T2=%ld T3=%ld HOLD=%ld\r\n"
            "Worst HoldPeak: %ldmA\r\n",
            (unsigned long)n,
            (unsigned int)TIGHTEN_REPEAT_CYCLES,
            (long)(post_avg_x100 / 100),
            (long)labs(post_avg_x100 % 100),
            (long)(post_min_x100 / 100),
            (long)labs(post_min_x100 % 100),
            (long)(post_max_x100 / 100),
            (long)labs(post_max_x100 % 100),
            (long)seat_avg_mA,
            (long)t1_avg_mA,
            (long)t2_avg_mA,
            (long)t3_avg_mA,
            (long)hold_avg_mA,
            (long)hold_peak_mA);

        UART_SendString(msg);
    }

    UART_SendString(
        "NOTE: repeatability includes manual-load variation.\r\n"
        "Iq is electrical q-axis current, NOT calibrated N.m\r\n"
        "=============================================\r\n\r\n");
}



static uint8_t Tightening_IsBusy(void)
{
    switch (tightening_test_stage)
    {
        case TIGHTEN_STATE_RUNDOWN:
        case TIGHTEN_STATE_CONTACT_STOP:
        case TIGHTEN_STATE_SEATING_IQ:
        case TIGHTEN_STATE_TIGHTEN_010:
        case TIGHTEN_STATE_TIGHTEN_012:
        case TIGHTEN_STATE_TIGHTEN_015:
        case TIGHTEN_STATE_HOLD:
            return 1U;

        default:
            return 0U;
    }
}


static const char *TighteningOutcome_Name(TighteningOutcome_t outcome)
{
    switch (outcome)
    {
        case TIGHTEN_OUTCOME_OK:
            return "OK";
        case TIGHTEN_OUTCOME_STOPPED:
            return "STOPPED";
        case TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT:
            return "RUNDOWN_TIMEOUT";
        case TIGHTEN_OUTCOME_STOP_TIMEOUT:
            return "STOP_TIMEOUT";
        case TIGHTEN_OUTCOME_ABORT:
            return "ABORT";
        case TIGHTEN_OUTCOME_FAULT:
            return "FAULT";
        case TIGHTEN_OUTCOME_NONE:
        default:
            return "NONE";
    }
}


static void Protocol_SendTaggedLine(
    uint32_t request_id,
    const char *payload)
{
    char msg[192];

    snprintf(
        msg,
        sizeof(msg),
        "%lu %s\r\n",
        (unsigned long)request_id,
        (payload != NULL) ? payload : "");

    UART_SendString(msg);
}


static void Protocol_SendError(
    uint32_t request_id,
    ProtocolError_t code,
    const char *name)
{
    char msg[128];

    snprintf(
        msg,
        sizeof(msg),
        "%lu ERR %u %s\r\n",
        (unsigned long)request_id,
        (unsigned int)code,
        (name != NULL) ? name : "UNKNOWN");

    UART_SendString(msg);
}


static void Protocol_SendCycleEvent(
    const char *event_name,
    const char *result_name)
{
    char msg[160];

    if (result_name != NULL)
    {
        snprintf(
            msg,
            sizeof(msg),
            "EVT REQ=%lu %s RESULT=%s\r\n",
            (unsigned long)tightening_cycle_request_id,
            (event_name != NULL) ? event_name : "EVENT",
            result_name);
    }
    else
    {
        snprintf(
            msg,
            sizeof(msg),
            "EVT REQ=%lu %s\r\n",
            (unsigned long)tightening_cycle_request_id,
            (event_name != NULL) ? event_name : "EVENT");
    }

    UART_SendString(msg);
}


static void Protocol_PrintStatus(uint32_t request_id)
{
    char msg[384];
    int32_t pos_x100 =
        (int32_t)(encoder_position_deg * 100.0f);
    int32_t ctrl_x10 =
        (int32_t)(encoder_speed_rpm * 10.0f);
    int32_t det_x10 =
        (int32_t)(encoder_speed_detect_rpm * 10.0f);
    int32_t iqref_mA =
        (int32_t)(foc_iq_ref_A * 1000.0f);

    snprintf(
        msg,
        sizeof(msg),
        "%lu OK STATUS STAGE=%u BUSY=%u MODE=%s OUTCOME=%s CONTACT=%u "
        "START_REQ=%lu FLT=%u REASON=%lu "
        "POS=%ld.%02lddeg CTRL=%ld.%01ldrpm DET=%ld.%01ldrpm "
        "IqRef=%ldmA "
        "UTXQ=%lu UDROP=%lu UERR=%lu "
        "RXQ=%lu RXDROP=%lu RXBYTES=%lu\r\n",
        (unsigned long)request_id,
        (unsigned int)tightening_test_stage,
        (unsigned int)Tightening_IsBusy(),
        MotorControl_ModeName(motor_control_mode),
        TighteningOutcome_Name(tightening_last_outcome),
        (unsigned int)tightening_contact_confirmed,
        (unsigned long)tightening_cycle_request_id,
        (unsigned int)foc_fault,
        (unsigned long)foc_fault_reason,
        (long)(pos_x100 / 100),
        (long)labs(pos_x100 % 100),
        (long)(ctrl_x10 / 10),
        (long)labs(ctrl_x10 % 10),
        (long)(det_x10 / 10),
        (long)labs(det_x10 % 10),
        (long)iqref_mA,
        (unsigned long)UART_Async_GetQueuedBytes(),
        (unsigned long)UART_Async_GetDroppedBytes(),
        (unsigned long)UART_Async_GetDmaErrorCount(),
        (unsigned long)UART_RxDma_GetQueuedBytes(),
        (unsigned long)UART_RxDma_GetDroppedBytes(),
        (unsigned long)UART_RxDma_GetTotalBytes());

    UART_SendString(msg);
}


static uint8_t TightenParams_Validate(const TightenParams_t *p)
{
    if (p == NULL) return 0U;

    if ((p->rundown_rpm < 20U) || (p->rundown_rpm > 120U)) return 0U;
    if ((p->contact_rpm < 1U) || (p->contact_rpm > 20U)) return 0U;
    if ((p->contact_iq_mA < 100U) || (p->contact_iq_mA > 400U)) return 0U;
    if ((p->contact_ms < 50U) || (p->contact_ms > 1000U)) return 0U;
    if ((p->rundown_timeout_ms < 1000U) || (p->rundown_timeout_ms > 20000U)) return 0U;
    if ((p->max_travel_deg < 100U) || (p->max_travel_deg > 10000U)) return 0U;

    if ((p->seating_iq_mA < 20U) || (p->seating_iq_mA > 150U)) return 0U;
    if ((p->t1_iq_mA < 20U) || (p->t1_iq_mA > 150U)) return 0U;
    if ((p->t2_iq_mA < 20U) || (p->t2_iq_mA > 150U)) return 0U;
    if ((p->t3_iq_mA < 20U) || (p->t3_iq_mA > 150U)) return 0U;
    if ((p->hold_iq_mA < 20U) || (p->hold_iq_mA > 150U)) return 0U;

    if ((p->seating_ms < 50U) || (p->seating_ms > 2000U)) return 0U;
    if ((p->t1_ms < 50U) || (p->t1_ms > 2000U)) return 0U;
    if ((p->t2_ms < 50U) || (p->t2_ms > 2000U)) return 0U;
    if ((p->t3_ms < 50U) || (p->t3_ms > 2000U)) return 0U;
    if ((p->hold_ms < 50U) || (p->hold_ms > 3000U)) return 0U;

    if ((p->torque_abort_rpm < 5U) || (p->torque_abort_rpm > 100U)) return 0U;
    if ((p->post_travel_max_deg < 5U) || (p->post_travel_max_deg > 360U)) return 0U;
    return 1U;
}

static void TightenParams_RestoreDefaults(void)
{
    tighten_params = tighten_params_defaults;
    tighten_params_dirty = 1U;
}

static uint32_t TightenParams_Crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xFFFFFFFFUL;
    size_t i;
    uint32_t bit;

    for (i = 0U; i < length; i++)
    {
        crc ^= (uint32_t)data[i];
        for (bit = 0U; bit < 8U; bit++)
        {
            if ((crc & 1UL) != 0UL)
                crc = (crc >> 1U) ^ 0xEDB88320UL;
            else
                crc >>= 1U;
        }
    }
    return ~crc;
}

static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void)
{
    TightenParamsFlashRecord_t record;
    const TightenParamsFlashRecord_t *flash_record =
        (const TightenParamsFlashRecord_t *)PARAM_FLASH_ADDRESS;
    uint32_t crc;

    memcpy(&record, flash_record, sizeof(record));

    if ((record.magic == 0xFFFFFFFFUL) &&
        (record.version == 0xFFFFFFFFUL))
    {
        tighten_params_flash_valid = 0U;
        tighten_params_last_crc32 = 0U;
        return PARAM_FLASH_LOAD_EMPTY;
    }

    if ((record.magic != PARAM_FLASH_MAGIC) ||
        (record.version != PARAM_FLASH_VERSION) ||
        (record.payload_size != sizeof(TightenParams_t)))
    {
        tighten_params_flash_valid = 0U;
        return PARAM_FLASH_LOAD_INVALID;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(TightenParamsFlashRecord_t, crc32));

    if (crc != record.crc32)
    {
        tighten_params_flash_valid = 0U;
        return PARAM_FLASH_LOAD_INVALID;
    }

    if (TightenParams_Validate(&record.params) == 0U)
    {
        tighten_params_flash_valid = 0U;
        return PARAM_FLASH_LOAD_INVALID;
    }

    tighten_params = record.params;
    tighten_params_flash_valid = 1U;
    tighten_params_dirty = 0U;
    tighten_params_last_crc32 = crc;
    return PARAM_FLASH_LOAD_OK;
}

static uint8_t TightenParams_SaveToFlash(void)
{
    TightenParamsFlashRecord_t record;
    FLASH_EraseInitTypeDef erase_init;
    uint32_t page_error = 0U;
    uint32_t offset;
    HAL_StatusTypeDef status;

    if (TightenParams_Validate(&tighten_params) == 0U)
        return 0U;

    memset(&record, 0xFF, sizeof(record));
    record.magic = PARAM_FLASH_MAGIC;
    record.version = PARAM_FLASH_VERSION;
    record.payload_size = sizeof(TightenParams_t);
    record.reserved0 = 0U;
    record.params = tighten_params;
    record.crc32 = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(TightenParamsFlashRecord_t, crc32));

    if (HAL_FLASH_Unlock() != HAL_OK)
        return 0U;

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = PARAM_FLASH_BANK;
    erase_init.Page = PARAM_FLASH_PAGE;
    erase_init.NbPages = 1U;

    status = HAL_FLASHEx_Erase(&erase_init, &page_error);

    if (status == HAL_OK)
    {
        for (offset = 0U; offset < sizeof(record); offset += 8U)
        {
            uint64_t data64;
            memcpy(&data64,
                   ((const uint8_t *)&record) + offset,
                   sizeof(data64));

            status = HAL_FLASH_Program(
                FLASH_TYPEPROGRAM_DOUBLEWORD,
                PARAM_FLASH_ADDRESS + offset,
                data64);

            if (status != HAL_OK)
                break;
        }
    }

    (void)HAL_FLASH_Lock();

    if (status != HAL_OK)
    {
        tighten_params_flash_valid = 0U;
        return 0U;
    }

    if (TightenParams_LoadFromFlash() != PARAM_FLASH_LOAD_OK)
    {
        tighten_params_flash_valid = 0U;
        return 0U;
    }
    return 1U;
}


static void TightenParams_SendValue(
    uint32_t request_id,
    const char *name,
    uint32_t value)
{
    char msg[128];

    snprintf(
        msg,
        sizeof(msg),
        "%lu PARAM %s=%lu\r\n",
        (unsigned long)request_id,
        (name != NULL) ? name : "UNKNOWN",
        (unsigned long)value);

    UART_SendString(msg);
}


static void TightenParams_PrintAll(uint32_t request_id)
{
    char msg[96];

    snprintf(
        msg,
        sizeof(msg),
        "%lu OK PARAMS FLASH_VALID=%u DIRTY=%u CRC32=0x%08lX\r\n",
        (unsigned long)request_id,
        (unsigned int)tighten_params_flash_valid,
        (unsigned int)tighten_params_dirty,
        (unsigned long)tighten_params_last_crc32);
    UART_SendString(msg);

    TightenParams_SendValue(
        request_id, "RUNDOWN_RPM",
        tighten_params.rundown_rpm);
    TightenParams_SendValue(
        request_id, "CONTACT_RPM",
        tighten_params.contact_rpm);
    TightenParams_SendValue(
        request_id, "CONTACT_IQ_MA",
        tighten_params.contact_iq_mA);
    TightenParams_SendValue(
        request_id, "CONTACT_MS",
        tighten_params.contact_ms);
    TightenParams_SendValue(
        request_id, "RUNDOWN_TIMEOUT_MS",
        tighten_params.rundown_timeout_ms);
    TightenParams_SendValue(
        request_id, "MAX_TRAVEL_DEG",
        tighten_params.max_travel_deg);

    TightenParams_SendValue(
        request_id, "SEATING_IQ_MA",
        tighten_params.seating_iq_mA);
    TightenParams_SendValue(
        request_id, "T1_IQ_MA",
        tighten_params.t1_iq_mA);
    TightenParams_SendValue(
        request_id, "T2_IQ_MA",
        tighten_params.t2_iq_mA);
    TightenParams_SendValue(
        request_id, "T3_IQ_MA",
        tighten_params.t3_iq_mA);
    TightenParams_SendValue(
        request_id, "HOLD_IQ_MA",
        tighten_params.hold_iq_mA);

    TightenParams_SendValue(
        request_id, "SEATING_MS",
        tighten_params.seating_ms);
    TightenParams_SendValue(
        request_id, "T1_MS",
        tighten_params.t1_ms);
    TightenParams_SendValue(
        request_id, "T2_MS",
        tighten_params.t2_ms);
    TightenParams_SendValue(
        request_id, "T3_MS",
        tighten_params.t3_ms);
    TightenParams_SendValue(
        request_id, "HOLD_MS",
        tighten_params.hold_ms);

    TightenParams_SendValue(
        request_id, "TORQUE_ABORT_RPM",
        tighten_params.torque_abort_rpm);
    TightenParams_SendValue(
        request_id, "POST_TRAVEL_MAX_DEG",
        tighten_params.post_travel_max_deg);

    snprintf(
        msg,
        sizeof(msg),
        "%lu END PARAMS\r\n",
        (unsigned long)request_id);
    UART_SendString(msg);
}


static uint8_t TightenParams_GetOne(
    uint32_t request_id,
    const char *name)
{
    char msg[128];
    uint32_t value = 0U;
    uint8_t found = 1U;

    if (strcmp(name, "RUNDOWN_RPM") == 0)
        value = tighten_params.rundown_rpm;
    else if (strcmp(name, "CONTACT_RPM") == 0)
        value = tighten_params.contact_rpm;
    else if (strcmp(name, "CONTACT_IQ_MA") == 0)
        value = tighten_params.contact_iq_mA;
    else if (strcmp(name, "CONTACT_MS") == 0)
        value = tighten_params.contact_ms;
    else if (strcmp(name, "RUNDOWN_TIMEOUT_MS") == 0)
        value = tighten_params.rundown_timeout_ms;
    else if (strcmp(name, "MAX_TRAVEL_DEG") == 0)
        value = tighten_params.max_travel_deg;
    else if (strcmp(name, "SEATING_IQ_MA") == 0)
        value = tighten_params.seating_iq_mA;
    else if (strcmp(name, "T1_IQ_MA") == 0)
        value = tighten_params.t1_iq_mA;
    else if (strcmp(name, "T2_IQ_MA") == 0)
        value = tighten_params.t2_iq_mA;
    else if (strcmp(name, "T3_IQ_MA") == 0)
        value = tighten_params.t3_iq_mA;
    else if (strcmp(name, "HOLD_IQ_MA") == 0)
        value = tighten_params.hold_iq_mA;
    else if (strcmp(name, "SEATING_MS") == 0)
        value = tighten_params.seating_ms;
    else if (strcmp(name, "T1_MS") == 0)
        value = tighten_params.t1_ms;
    else if (strcmp(name, "T2_MS") == 0)
        value = tighten_params.t2_ms;
    else if (strcmp(name, "T3_MS") == 0)
        value = tighten_params.t3_ms;
    else if (strcmp(name, "HOLD_MS") == 0)
        value = tighten_params.hold_ms;
    else if (strcmp(name, "TORQUE_ABORT_RPM") == 0)
        value = tighten_params.torque_abort_rpm;
    else if (strcmp(name, "POST_TRAVEL_MAX_DEG") == 0)
        value = tighten_params.post_travel_max_deg;
    else
        found = 0U;

    if (found == 0U)
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BAD_ARGUMENT,
            "UNKNOWN_PARAM");
        return 0U;
    }

    snprintf(
        msg,
        sizeof(msg),
        "%lu OK GET %s=%lu\r\n",
        (unsigned long)request_id,
        name,
        (unsigned long)value);
    UART_SendString(msg);

    return 1U;
}


static uint8_t TightenParams_SetOne(
    uint32_t request_id,
    const char *name,
    uint32_t value)
{
    char msg[144];
    uint8_t valid = 1U;

    if ((Tightening_IsBusy() != 0U) ||
        (tightening_start_request != 0U))
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BUSY,
            "BUSY");
        return 0U;
    }

#define PARAM_SET_RANGE(field_, low_, high_)                   \
    do                                                         \
    {                                                          \
        if ((value < (uint32_t)(low_)) ||                     \
            (value > (uint32_t)(high_)))                      \
        {                                                      \
            valid = 0U;                                        \
        }                                                      \
        else                                                   \
        {                                                      \
            tighten_params.field_ = value;                     \
            tighten_params_dirty = 1U;                            \
        }                                                      \
    } while (0)

    if (strcmp(name, "RUNDOWN_RPM") == 0)
        PARAM_SET_RANGE(rundown_rpm, 20U, 120U);
    else if (strcmp(name, "CONTACT_RPM") == 0)
        PARAM_SET_RANGE(contact_rpm, 1U, 20U);
    else if (strcmp(name, "CONTACT_IQ_MA") == 0)
        PARAM_SET_RANGE(contact_iq_mA, 100U, 400U);
    else if (strcmp(name, "CONTACT_MS") == 0)
        PARAM_SET_RANGE(contact_ms, 50U, 1000U);
    else if (strcmp(name, "RUNDOWN_TIMEOUT_MS") == 0)
        PARAM_SET_RANGE(rundown_timeout_ms, 1000U, 20000U);
    else if (strcmp(name, "MAX_TRAVEL_DEG") == 0)
        PARAM_SET_RANGE(max_travel_deg, 100U, 10000U);

    else if (strcmp(name, "SEATING_IQ_MA") == 0)
        PARAM_SET_RANGE(seating_iq_mA, 20U, 150U);
    else if (strcmp(name, "T1_IQ_MA") == 0)
        PARAM_SET_RANGE(t1_iq_mA, 20U, 150U);
    else if (strcmp(name, "T2_IQ_MA") == 0)
        PARAM_SET_RANGE(t2_iq_mA, 20U, 150U);
    else if (strcmp(name, "T3_IQ_MA") == 0)
        PARAM_SET_RANGE(t3_iq_mA, 20U, 150U);
    else if (strcmp(name, "HOLD_IQ_MA") == 0)
        PARAM_SET_RANGE(hold_iq_mA, 20U, 150U);

    else if (strcmp(name, "SEATING_MS") == 0)
        PARAM_SET_RANGE(seating_ms, 50U, 2000U);
    else if (strcmp(name, "T1_MS") == 0)
        PARAM_SET_RANGE(t1_ms, 50U, 2000U);
    else if (strcmp(name, "T2_MS") == 0)
        PARAM_SET_RANGE(t2_ms, 50U, 2000U);
    else if (strcmp(name, "T3_MS") == 0)
        PARAM_SET_RANGE(t3_ms, 50U, 2000U);
    else if (strcmp(name, "HOLD_MS") == 0)
        PARAM_SET_RANGE(hold_ms, 50U, 3000U);

    else if (strcmp(name, "TORQUE_ABORT_RPM") == 0)
        PARAM_SET_RANGE(torque_abort_rpm, 5U, 100U);
    else if (strcmp(name, "POST_TRAVEL_MAX_DEG") == 0)
        PARAM_SET_RANGE(post_travel_max_deg, 5U, 360U);
    else
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BAD_ARGUMENT,
            "UNKNOWN_PARAM");
        return 0U;
    }

#undef PARAM_SET_RANGE

    if (valid == 0U)
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BAD_ARGUMENT,
            "VALUE_OUT_OF_RANGE");
        return 0U;
    }

    snprintf(
        msg,
        sizeof(msg),
        "%lu OK SET %s=%lu DIRTY=1\r\n",
        (unsigned long)request_id,
        name,
        (unsigned long)value);
    UART_SendString(msg);

    return 1U;
}


static void Protocol_HandleLine(char *line)
{
    char *p;
    char *endptr;
    char *cmd;
    unsigned long request_ul;
    uint32_t request_id;
    size_t len;
    size_t i;
    char msg[192];
    char *arg;
    char *value_text;
    char *value_end;
    unsigned long value_ul;

    if (line == NULL)
    {
        return;
    }

    /*
     * Protocol V2 frame:
     *
     *     <REQ_ID> <COMMAND>\r\n
     *
     * Examples:
     *
     *     17 PING
     *     18 STATUS
     *     19 START
     *
     * REQ_ID=0 is reserved for parser/framing errors where the original
     * request cannot be reliably correlated.
     */

    p = line;
    while ((*p == ' ') || (*p == '\t'))
    {
        p++;
    }

    if (p != line)
    {
        memmove(line, p, strlen(p) + 1U);
    }

    len = strlen(line);
    while ((len > 0U) &&
           ((line[len - 1U] == ' ') ||
            (line[len - 1U] == '\t')))
    {
        line[len - 1U] = '\0';
        len--;
    }

    if (line[0] == '\0')
    {
        return;
    }

    request_ul = strtoul(line, &endptr, 10);

    if ((endptr == line) ||
        (request_ul == 0UL) ||
        (request_ul > 0xFFFFFFFFUL))
    {
        Protocol_SendError(
            0U,
            PROTO_ERR_BAD_ARGUMENT,
            "BAD_REQUEST_ID");
        return;
    }

    if ((*endptr != ' ') && (*endptr != '\t'))
    {
        Protocol_SendError(
            (uint32_t)request_ul,
            PROTO_ERR_BAD_ARGUMENT,
            "MISSING_COMMAND_SEPARATOR");
        return;
    }

    request_id = (uint32_t)request_ul;

    cmd = endptr;
    while ((*cmd == ' ') || (*cmd == '\t'))
    {
        cmd++;
    }

    if (*cmd == '\0')
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BAD_ARGUMENT,
            "MISSING_COMMAND");
        return;
    }

    /*
     * Commands are case-insensitive; the request ID is already parsed.
     */
    for (i = 0U; cmd[i] != '\0'; i++)
    {
        cmd[i] = (char)toupper((unsigned char)cmd[i]);
    }

    if (strcmp(cmd, "PING") == 0)
    {
        snprintf(
            msg,
            sizeof(msg),
            "%lu OK PING PONG\r\n",
            (unsigned long)request_id);
        UART_SendString(msg);
    }
    else if (strcmp(cmd, "HELP") == 0)
    {
        Protocol_SendTaggedLine(
            request_id,
            "OK HELP VERSION=2 PARAMS=1");
        Protocol_SendTaggedLine(request_id, "FORMAT <REQ_ID> <COMMAND>");
        Protocol_SendTaggedLine(request_id, "CMD PING");
        Protocol_SendTaggedLine(request_id, "CMD STATUS");
        Protocol_SendTaggedLine(request_id, "CMD START");
        Protocol_SendTaggedLine(request_id, "CMD STOP");
        Protocol_SendTaggedLine(request_id, "CMD RESULT");
        Protocol_SendTaggedLine(request_id, "CMD GET PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD GET <PARAM>");
        Protocol_SendTaggedLine(request_id, "CMD SET <PARAM> <VALUE>");
        Protocol_SendTaggedLine(request_id, "CMD SAVE PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD LOAD PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD DEFAULT PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD HELP");
        Protocol_SendTaggedLine(request_id, "ERR 100 UNKNOWN_COMMAND");
        Protocol_SendTaggedLine(request_id, "ERR 101 BUSY");
        Protocol_SendTaggedLine(request_id, "ERR 102 LINE_TOO_LONG");
        Protocol_SendTaggedLine(request_id, "ERR 103 BAD_ARGUMENT");
        Protocol_SendTaggedLine(request_id, "ERR 104 NOT_READY");
        Protocol_SendTaggedLine(request_id, "ERR 105 FAULT");
        Protocol_SendTaggedLine(request_id, "ERR 106 ROTOR_MOVING");
        Protocol_SendTaggedLine(request_id, "ERR 107 FLASH_ERROR");
        Protocol_SendTaggedLine(request_id, "ERR 108 NO_VALID_PARAMS");
        Protocol_SendTaggedLine(request_id, "END HELP");
    }
    else if (strcmp(cmd, "STATUS") == 0)
    {
        Protocol_PrintStatus(request_id);
    }
    else if (strcmp(cmd, "SAVE PARAMS") == 0)
    {
        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U) ||
            (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING, "ROTOR_MOVING");
        }
        else if (TightenParams_SaveToFlash() == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FLASH, "FLASH_ERROR");
        }
        else
        {
            snprintf(msg, sizeof(msg),
                     "%lu OK SAVE PARAMS CRC32=0x%08lX\r\n",
                     (unsigned long)request_id,
                     (unsigned long)tighten_params_last_crc32);
            UART_SendString(msg);
        }
    }
    else if (strcmp(cmd, "LOAD PARAMS") == 0)
    {
        TightenParamsFlashLoadStatus_t load_status;

        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else
        {
            load_status = TightenParams_LoadFromFlash();

            if (load_status == PARAM_FLASH_LOAD_OK)
            {
                snprintf(msg, sizeof(msg),
                         "%lu OK LOAD PARAMS CRC32=0x%08lX\r\n",
                         (unsigned long)request_id,
                         (unsigned long)tighten_params_last_crc32);
                UART_SendString(msg);
            }
            else
            {
                Protocol_SendError(request_id,
                                   PROTO_ERR_NO_VALID_PARAMS,
                                   "NO_VALID_PARAMS");
            }
        }
    }
    else if (strcmp(cmd, "DEFAULT PARAMS") == 0)
    {
        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else
        {
            TightenParams_RestoreDefaults();
            snprintf(msg, sizeof(msg),
                     "%lu OK DEFAULT PARAMS DIRTY=1\r\n",
                     (unsigned long)request_id);
            UART_SendString(msg);
        }
    }
    else if (strcmp(cmd, "GET PARAMS") == 0)
    {
        TightenParams_PrintAll(request_id);
    }
    else if (strncmp(cmd, "GET ", 4U) == 0)
    {
        arg = cmd + 4U;
        while ((*arg == ' ') || (*arg == '\t'))
        {
            arg++;
        }

        if (*arg == '\0')
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "MISSING_PARAM");
        }
        else
        {
            (void)TightenParams_GetOne(
                request_id,
                arg);
        }
    }
    else if (strncmp(cmd, "SET ", 4U) == 0)
    {
        arg = cmd + 4U;
        while ((*arg == ' ') || (*arg == '\t'))
        {
            arg++;
        }

        value_text = arg;
        while ((*value_text != '\0') &&
               (*value_text != ' ') &&
               (*value_text != '\t'))
        {
            value_text++;
        }

        if (*value_text == '\0')
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "MISSING_VALUE");
        }
        else
        {
            *value_text = '\0';
            value_text++;

            while ((*value_text == ' ') ||
                   (*value_text == '\t'))
            {
                value_text++;
            }

            value_ul = strtoul(
                value_text,
                &value_end,
                10);

            while ((*value_end == ' ') ||
                   (*value_end == '\t'))
            {
                value_end++;
            }

            if ((*value_text == '\0') ||
                (value_end == value_text) ||
                (*value_end != '\0') ||
                (value_ul > 0xFFFFFFFFUL))
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "BAD_VALUE");
            }
            else
            {
                (void)TightenParams_SetOne(
                    request_id,
                    arg,
                    (uint32_t)value_ul);
            }
        }
    }
    else if (strcmp(cmd, "START") == 0)
    {
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FAULT,
                "FAULT");
        }
        else if ((Tightening_IsBusy() != 0U) ||
                 (tightening_start_request != 0U))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BUSY,
                "BUSY");
        }
        else
        {
            /*
             * Publish ID first, then flag. On Cortex-M4 an aligned 32-bit
             * store is atomic, and the volatile mailbox preserves the
             * producer/consumer ordering used by this small design.
             */
            tightening_start_request_id = request_id;
            tightening_start_request = 1U;

            snprintf(
                msg,
                sizeof(msg),
                "%lu OK START QUEUED\r\n",
                (unsigned long)request_id);
            UART_SendString(msg);
        }
    }
    else if (strcmp(cmd, "STOP") == 0)
    {
        tightening_stop_request_id = request_id;
        tightening_stop_request = 1U;

        snprintf(
            msg,
            sizeof(msg),
            "%lu OK STOP QUEUED\r\n",
            (unsigned long)request_id);
        UART_SendString(msg);
    }
    else if (strcmp(cmd, "RESULT") == 0)
    {
        if (Tightening_IsBusy() != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BUSY,
                "BUSY");
        }
        else
        {
            tightening_result_request_id = request_id;
            tightening_result_request = 1U;

            snprintf(
                msg,
                sizeof(msg),
                "%lu OK RESULT QUEUED\r\n",
                (unsigned long)request_id);
            UART_SendString(msg);
        }
    }
    else
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_UNKNOWN_COMMAND,
            "UNKNOWN_COMMAND");
    }
}

static void ProtocolTask(void *argument)
{
    TickType_t last_wake_time;
    uint8_t rx_buf[64];
    char line[96];
    size_t line_len = 0U;

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendString(
        "\r\n"
        "ProtocolTask started @ 5ms\r\n"
        "UART RX: DMA1_CH2 circular -> RX ring -> line parser\r\n"
        "Protocol V2 framing: <REQ_ID> <COMMAND> + CR/LF\r\n"
        "Type HELP then press Enter\r\n"
        "Device is IDLE until START is received\r\n\r\n");

    for (;;)
    {
        size_t n;
        size_t i;

        UART_RxDma_Poll();
        n = UART_RxDma_Read(rx_buf, sizeof(rx_buf));

        for (i = 0U; i < n; i++)
        {
            uint8_t ch = rx_buf[i];

            if ((ch == '\r') || (ch == '\n'))
            {
                if (line_len > 0U)
                {
                    line[line_len] = '\0';
                    Protocol_HandleLine(line);
                    line_len = 0U;
                }
            }
            else if ((ch == 0x08U) || (ch == 0x7FU))
            {
                if (line_len > 0U)
                {
                    line_len--;
                }
            }
            else if ((ch >= 0x20U) && (ch <= 0x7EU))
            {
                if (line_len < (sizeof(line) - 1U))
                {
                    line[line_len++] = (char)ch;
                }
                else
                {
                    line_len = 0U;
                    Protocol_SendError(0U, PROTO_ERR_LINE_TOO_LONG, "LINE_TOO_LONG");
                }
            }
        }

        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(5U));
    }
}


static void TighteningTask(void *argument)
{
    TickType_t last_wake_time;
    TickType_t stage_start;
    uint32_t stop_confirm_ms = 0U;

    (void)argument;

    last_wake_time = xTaskGetTickCount();
    stage_start = last_wake_time;

    memset(tightening_cycle_summary,
           0,
           sizeof(tightening_cycle_summary));

    tightening_cycle_number = 1U;
    tightening_cycle_ok_count = 0U;
    tightening_start_request = 0U;
    tightening_stop_request = 0U;
    tightening_result_request = 0U;
    tightening_start_request_id = 0U;
    tightening_stop_request_id = 0U;
    tightening_result_request_id = 0U;
    tightening_cycle_request_id = 0U;
    tightening_last_outcome = TIGHTEN_OUTCOME_NONE;

    /*
     * Enum value 0 is kept for compatibility, but now means WAIT_COMMAND.
     * There is no automatic 2-second startup rundown.
     */
    tightening_test_stage = TIGHTEN_STATE_IDLE_DELAY;
    TighteningRepeat_ResetCurrentCycle();

    MotorControl_SetIdle();

    UART_SendString(
        "\r\n"
        "TighteningTask started\r\n"
        "COMMAND-DRIVEN SINGLE-CYCLE MODE\r\n"
        "Device remains IDLE until UART command START\r\n"
        "\r\n"
        "State flow after START:\r\n"
        "  WAIT_COMMAND\r\n"
        "  -> RUNDOWN (runtime rpm)\r\n"
        "  -> CONTACT (runtime thresholds)\r\n"
        "  -> IDLE / wait until stopped\r\n"
        "  -> SEATING      (runtime current/time)\r\n"
        "  -> TIGHTEN #1   (runtime current/time)\r\n"
        "  -> TIGHTEN #2   (runtime current/time)\r\n"
        "  -> TIGHTEN #3   (runtime current/time)\r\n"
        "  -> HOLD         (runtime current/time)\r\n"
        "  -> COMPLETE / IDLE\r\n"
        "\r\n"
        "STOP is accepted at any time\r\n"
        "RESULT reprints the latest terminal result\r\n"
        "Important: Iq is NOT calibrated torque/N.m\r\n"
        "Post-contact abort: runtime speed/travel limits\r\n"
        "RUNDOWN abort: runtime timeout/travel limits\r\n"
        "Result recorder: 100Hz per-stage statistics\r\n"
        "PARAMS: use <REQ_ID> GET PARAMS / SET <PARAM> <VALUE>\r\n"
        "\r\n");

    for (;;)
    {
        TickType_t now = xTaskGetTickCount();
        uint32_t elapsed_ms =
            (uint32_t)((now - stage_start) * portTICK_PERIOD_MS);

        float det_rpm = encoder_speed_detect_rpm;
        float drive_iqref =
            TIGHTEN_DIRECTION * foc_iq_ref_A;
        float travel =
            fabsf(encoder_position_deg - tightening_start_position_deg);
        float post_contact_travel =
            fabsf(encoder_position_deg - tightening_contact_position_deg);

        tightening_test_elapsed_ms = elapsed_ms;
        tightening_drive_iqref_A = drive_iqref;
        tightening_travel_deg = travel;
        tightening_post_contact_travel_deg = post_contact_travel;

        /*
         * STOP is consumed by the application owner. The lower-level motor
         * service still owns the actual transition to IDLE.
         */
        if (tightening_stop_request != 0U)
        {
            uint8_t was_busy = Tightening_IsBusy();
            uint32_t stop_request_id = tightening_stop_request_id;
            char proto_msg[160];

            tightening_stop_request = 0U;
            tightening_stop_request_id = 0U;
            MotorControl_SetIdle();

            tightening_contact_candidate_ms = 0U;
            tightening_contact_condition = 0U;
            tightening_drive_iqref_A = 0.0f;
            stop_confirm_ms = 0U;

            if (was_busy != 0U)
            {
                tightening_last_outcome = TIGHTEN_OUTCOME_STOPPED;
                tightening_test_stage = TIGHTEN_STATE_DONE;
                stage_start = now;
                tightening_test_elapsed_ms = 0U;

                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STOPPED START_REQ=%lu\r\n",
                    (unsigned long)stop_request_id,
                    (unsigned long)tightening_cycle_request_id);
                UART_SendString(proto_msg);

                Protocol_SendCycleEvent("COMPLETE", "STOPPED");

                UART_SendString(
                    "TIGHTEN: STOP command -> IDLE\r\n");

                if (tightening_result_printed == 0U)
                {
                    tightening_result_printed = 1U;
                    TighteningResult_PrintSummary("STOPPED");
                }
            }
            else
            {
                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu ALREADY_IDLE\r\n",
                    (unsigned long)stop_request_id);
                UART_SendString(proto_msg);

                UART_SendString(
                    "TIGHTEN: STOP command -> already IDLE\r\n");
            }
        }

        if (tightening_start_request != 0U)
        {
            uint32_t start_request_id =
                tightening_start_request_id;
            char proto_msg[160];

            tightening_start_request = 0U;
            tightening_start_request_id = 0U;

            if ((adc_fault != 0U) || (foc_fault != 0U))
            {
                Protocol_SendError(start_request_id, PROTO_ERR_FAULT, "FAULT");
            }
            else if (Tightening_IsBusy() != 0U)
            {
                Protocol_SendError(start_request_id, PROTO_ERR_BUSY, "BUSY");
            }
            else if (fabsf(encoder_speed_rpm) >
                     TIGHTEN_REPEAT_RESTART_MAX_RPM)
            {
                Protocol_SendError(start_request_id, PROTO_ERR_ROTOR_MOVING, "ROTOR_MOVING");
            }
            else
            {
                memset(tightening_cycle_summary,
                       0,
                       sizeof(tightening_cycle_summary));

                tightening_cycle_number = 1U;
                tightening_cycle_ok_count = 0U;
                tightening_last_outcome = TIGHTEN_OUTCOME_NONE;
                tightening_cycle_request_id = start_request_id;

                TighteningRepeat_ResetCurrentCycle();

                tightening_start_position_deg =
                    encoder_position_deg;
                tightening_travel_deg = 0.0f;
                stop_confirm_ms = 0U;

                MotorControl_SetSpeed(
                    TIGHTEN_DIRECTION *
                    (float)tighten_params.rundown_rpm);

                tightening_test_stage =
                    TIGHTEN_STATE_RUNDOWN;
                stage_start = now;
                tightening_test_elapsed_ms = 0U;
                tightening_travel_deg = 0.0f;
                tightening_post_contact_travel_deg = 0.0f;

                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STARTED MODE=RUNDOWN TARGET=%lurpm\r\n",
                    (unsigned long)tightening_cycle_request_id,
                    (unsigned long)tighten_params.rundown_rpm);
                UART_SendString(proto_msg);

                UART_SendString(
                    "TIGHTEN: START -> RUNDOWN\r\n");

                /*
                 * IMPORTANT:
                 * elapsed_ms / travel / post_contact_travel were calculated
                 * at the top of this loop while we were still in WAIT_COMMAND.
                 * If the board had been idle for >8 s, using those stale
                 * values in the RUNDOWN switch below would immediately trigger
                 * RUNDOWN_TIMEOUT in the very same 10 ms iteration, before
                 * MotorControlTask could act on MOTOR_MODE_SPEED.
                 *
                 * End this application iteration here.  The next 100 Hz tick
                 * recomputes all state-derived values from the new RUNDOWN
                 * baseline.
                 */
                vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
                continue;
            }
        }

        if (tightening_result_request != 0U)
        {
            uint32_t result_request_id =
                tightening_result_request_id;
            char proto_msg[192];

            tightening_result_request = 0U;
            tightening_result_request_id = 0U;

            if (Tightening_IsBusy() != 0U)
            {
                Protocol_SendError(
                    result_request_id,
                    PROTO_ERR_BUSY,
                    "BUSY");
            }
            else if (tightening_last_outcome ==
                     TIGHTEN_OUTCOME_NONE)
            {
                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT NONE START_REQ=0\r\n",
                    (unsigned long)result_request_id);
                UART_SendString(proto_msg);
            }
            else
            {
                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT DATA START_REQ=%lu OUTCOME=%s CONTACT=%u\r\n",
                    (unsigned long)result_request_id,
                    (unsigned long)tightening_cycle_request_id,
                    TighteningOutcome_Name(tightening_last_outcome),
                    (unsigned int)tightening_contact_confirmed);
                UART_SendString(proto_msg);

                TighteningResult_PrintSummary(
                    TighteningOutcome_Name(
                        tightening_last_outcome));

                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu END RESULT\r\n",
                    (unsigned long)result_request_id);
                UART_SendString(proto_msg);
            }
        }

        /*
         * Latched lower-level faults always win.
         * There is no automatic restart from FAULT.
         */
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            if (tightening_test_stage != TIGHTEN_STATE_FAULT)
            {
                MotorControl_SetIdle();

                tightening_test_stage = TIGHTEN_STATE_FAULT;
                tightening_last_outcome = TIGHTEN_OUTCOME_FAULT;
                tightening_contact_candidate_ms = 0U;
                tightening_contact_condition = 0U;
                tightening_drive_iqref_A = 0.0f;

                Protocol_SendCycleEvent("COMPLETE", "FAULT");

                UART_SendString(
                    "TIGHTEN: FAULT -> IDLE, no automatic restart\r\n");
            }

            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
            continue;
        }

        switch (tightening_test_stage)
        {
            case TIGHTEN_STATE_IDLE_DELAY:
                /* WAIT_COMMAND: START handling above is the only entry path. */
                tightening_contact_candidate_ms = 0U;
                tightening_contact_condition = 0U;
                tightening_drive_iqref_A = 0.0f;
                tightening_post_contact_travel_deg = 0.0f;
                break;

            case TIGHTEN_STATE_RUNDOWN:
            {
                uint8_t contact_now = 0U;

                /*
                 * A contact candidate must satisfy BOTH:
                 *   1) low 50 ms average mechanical speed
                 *   2) substantial q-axis current demand
                 *
                 * and remain true continuously for 250 ms.
                 */
                if ((fabsf(det_rpm) <=
                     (float)tighten_params.contact_rpm) &&
                    (drive_iqref >=
                     ((float)tighten_params.contact_iq_mA / 1000.0f)))
                {
                    contact_now = 1U;
                }

                tightening_contact_condition = contact_now;

                if (contact_now != 0U)
                {
                    if (tightening_contact_candidate_ms <
                        tighten_params.contact_ms)
                    {
                        tightening_contact_candidate_ms += 10U;
                    }
                }
                else
                {
                    tightening_contact_candidate_ms = 0U;
                }

                if (tightening_contact_candidate_ms >=
                    tighten_params.contact_ms)
                {
                    /*
                     * Latch contact position BEFORE removing the speed command.
                     * All later torque-mode travel is measured from here.
                     */
                    tightening_contact_position_deg =
                        encoder_position_deg;
                    tightening_post_contact_travel_deg = 0.0f;
                    tightening_contact_confirmed = 1U;

                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_CONTACT_STOP;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    stop_confirm_ms = 0U;

                    /*
                     * Clear candidate/log values on the state transition so
                     * the monitor does not keep showing CT=250 ms forever.
                     */
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    UART_SendString(
                        "TIGHTEN: CONTACT CONFIRMED -> IDLE stop\r\n");
                }
                else if ((elapsed_ms >=
                          tighten_params.rundown_timeout_ms) ||
                         (travel >=
                          (float)tighten_params.max_travel_deg))
                {
                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "RUNDOWN_TIMEOUT");

                    UART_SendString(
                        "TIGHTEN: RUNDOWN timeout/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary(
                            "RUNDOWN_TIMEOUT");
                    }
                }
                break;
            }

            case TIGHTEN_STATE_CONTACT_STOP:
                tightening_contact_condition = 0U;
                tightening_contact_candidate_ms = 0U;

                if (fabsf(encoder_speed_rpm) <=
                    TIGHTEN_STOP_MAX_RPM)
                {
                    if (stop_confirm_ms <
                        TIGHTEN_STOP_CONFIRM_MS)
                    {
                        stop_confirm_ms += 10U;
                    }
                }
                else
                {
                    stop_confirm_ms = 0U;
                }

                if (stop_confirm_ms >=
                    TIGHTEN_STOP_CONFIRM_MS)
                {
                    TighteningResult_Reset(
                        &tighten_result_seating,
                        ((float)tighten_params.seating_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)tighten_params.seating_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_SEATING_IQ;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;

                    UART_SendString(
                        "TIGHTEN: SEATING started\r\n");
                }
                else if (elapsed_ms >=
                         TIGHTEN_STOP_TIMEOUT_MS)
                {
                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_STOP_TIMEOUT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "STOP_TIMEOUT");

                    UART_SendString(
                        "TIGHTEN: stop timeout -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("STOP_TIMEOUT");
                    }
                }
                break;

            case TIGHTEN_STATE_SEATING_IQ:
                TighteningResult_Sample(&tighten_result_seating);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)tighten_params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)tighten_params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendString(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         tighten_params.seating_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_010,
                        ((float)tighten_params.t1_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)tighten_params.t1_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_010;
                    stage_start = now;

                    UART_SendString(
                        "TIGHTEN: TIGHTEN #1\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_010:
                TighteningResult_Sample(&tighten_result_010);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)tighten_params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)tighten_params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendString(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         tighten_params.t1_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_012,
                        ((float)tighten_params.t2_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)tighten_params.t2_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_012;
                    stage_start = now;

                    UART_SendString(
                        "TIGHTEN: TIGHTEN #2\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_012:
                TighteningResult_Sample(&tighten_result_012);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)tighten_params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)tighten_params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendString(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         tighten_params.t2_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_015,
                        ((float)tighten_params.t3_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)tighten_params.t3_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_015;
                    stage_start = now;

                    UART_SendString(
                        "TIGHTEN: TIGHTEN #3\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_015:
                TighteningResult_Sample(&tighten_result_015);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)tighten_params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)tighten_params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendString(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         tighten_params.t3_ms)
                {
                    /*
                     * HOLD keeps the same +0.15 A command; only the state/time
                     * changes so the log clearly separates final hold.
                     */
                    TighteningResult_Reset(
                        &tighten_result_hold,
                        ((float)tighten_params.hold_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)tighten_params.hold_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_HOLD;
                    stage_start = now;

                    UART_SendString(
                        "TIGHTEN: HOLD started\r\n");
                }
                break;

            case TIGHTEN_STATE_HOLD:
                TighteningResult_Sample(&tighten_result_hold);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)tighten_params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)tighten_params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendString(
                        "TIGHTEN: HOLD speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         tighten_params.hold_ms)
                {
                    MotorControl_SetIdle();

                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_OK;
                    tightening_test_stage =
                        TIGHTEN_STATE_DONE;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "OK");

                    UART_SendString(
                        "TIGHTEN: COMPLETE -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("OK");
                        TighteningRepeat_StoreCurrentCycle();
                    }

                    UART_SendString(
                        "TIGHTEN: cycle finished; send START for another cycle\r\n");
                }
                break;

            case TIGHTEN_STATE_CYCLE_PAUSE:
                /* Legacy enum; Layer 1B does not auto-restart. */
                MotorControl_SetIdle();
                tightening_test_stage = TIGHTEN_STATE_DONE;
                break;

            case TIGHTEN_STATE_DONE:
            case TIGHTEN_STATE_TIMEOUT:
            case TIGHTEN_STATE_FAULT:
            default:
                /*
                 * IDLE already published on entry.
                 * Do not continuously re-latch PTGT and do not auto-restart.
                 */
                tightening_contact_condition = 0U;
                tightening_contact_candidate_ms = 0U;
                break;
        }

        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
    }
}


static void MonitorTask(void *argument)
{
    TickType_t last_sample_tick;
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    last_sample_tick = xTaskGetTickCount();
    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;

    for (;;)
    {
        uint32_t adc_now;
        uint32_t foc_now;
        uint32_t adc_delta;
        uint32_t foc_delta;
        uint32_t adc_rate_hz;
        uint32_t foc_rate_hz;
        uint32_t monitor_period_ms;
        uint32_t sample_elapsed_ms;
        TickType_t now_tick;
        MotorControlMode_t mode;
        TighteningTestStage_t test_stage;
        uint32_t test_ms;
        uint32_t contact_ms;
        uint8_t contact_cond;
        uint32_t cycle_no;
        uint32_t uart_tx_queued;
        uint32_t uart_tx_dropped;
        uint32_t uart_dma_errors;
        uint32_t uart_rx_queued;
        uint32_t uart_rx_dropped;
        uint32_t fault_reason;
        uint8_t foc_en;
        uint8_t foc_flt;

        float pos;
        float ptgt;
        float perr;
        float spd;
        float spd_raw;
        float spd_det;
        float vcmd;
        float sref;
        float iqref;
        float id;
        float iq;
        float speed_cmd;
        float iq_cmd;
        float travel_deg;
        float post_contact_travel_deg;
        float drive_iqref_A;

        int32_t pos_x100;
        int32_t ptgt_x100;
        int32_t perr_x100;
        int32_t spd_x10;
        int32_t spd_raw_x10;
        int32_t spd_det_x10;
        int32_t vcmd_x10;
        int32_t sref_x10;
        int32_t speed_cmd_x10;
        int32_t iq_cmd_mA;
        int32_t iqref_mA;
        int32_t drive_iqref_mA;
        int32_t travel_x10;
        int32_t post_travel_x10;
        int32_t id_mA;
        int32_t iq_mA;

        char pos_buf[20];
        char ptgt_buf[20];
        char perr_buf[20];
        char msg[768];

        /*
         * Human-readable monitor rate:
         *   - IDLE / terminal state: one line every 3 seconds
         *   - active tightening:     one line every 1 second
         *
         * Protocol replies (PING/STATUS/START/STOP/RESULT) are event-driven
         * and are not delayed by this monitor period.
         */
        monitor_period_ms =
            (Tightening_IsBusy() != 0U) ? 1000U : 3000U;

        vTaskDelay(pdMS_TO_TICKS(monitor_period_ms));

        now_tick = xTaskGetTickCount();

        sample_elapsed_ms =
            (uint32_t)((now_tick - last_sample_tick) *
                       portTICK_PERIOD_MS);

        if (sample_elapsed_ms == 0U)
        {
            sample_elapsed_ms = monitor_period_ms;
        }

        adc_now = injected_seq_count;
        foc_now = foc_control_count;

        adc_delta = adc_now - last_adc_count;
        foc_delta = foc_now - last_foc_count;

        adc_rate_hz =
            (uint32_t)(((uint64_t)adc_delta * 1000ULL) /
                       (uint64_t)sample_elapsed_ms);

        foc_rate_hz =
            (uint32_t)(((uint64_t)foc_delta * 1000ULL) /
                       (uint64_t)sample_elapsed_ms);

        last_sample_tick = now_tick;
        last_adc_count = adc_now;
        last_foc_count = foc_now;

        mode = motor_control_mode;
        test_stage = tightening_test_stage;
        test_ms = tightening_test_elapsed_ms;
        contact_ms = tightening_contact_candidate_ms;
        contact_cond = tightening_contact_condition;
        cycle_no = tightening_cycle_number;

        uart_tx_queued =
            (uint32_t)UART_Async_GetQueuedBytes();
        uart_tx_dropped =
            UART_Async_GetDroppedBytes();
        uart_dma_errors =
            UART_Async_GetDmaErrorCount();
        uart_rx_queued =
            (uint32_t)UART_RxDma_GetQueuedBytes();
        uart_rx_dropped =
            UART_RxDma_GetDroppedBytes();

        fault_reason = foc_fault_reason;
        foc_en = foc_enable;
        foc_flt = foc_fault;

        pos = encoder_position_deg;
        ptgt = position_target_deg;
        perr = position_error_deg;
        spd = encoder_speed_rpm;
        spd_raw = encoder_rpm_instant;
        spd_det = encoder_speed_detect_rpm;
        vcmd = speed_target_rpm;
        sref = speed_ref_rpm;
        speed_cmd = motor_speed_command_rpm;
        iq_cmd = motor_iq_command_A;
        travel_deg = tightening_travel_deg;
        post_contact_travel_deg =
            tightening_post_contact_travel_deg;
        drive_iqref_A = tightening_drive_iqref_A;
        iqref = foc_iq_ref_A;
        id = foc_id_A;
        iq = foc_iq_A;

        pos_x100 = (int32_t)(pos * 100.0f);
        ptgt_x100 = (int32_t)(ptgt * 100.0f);
        perr_x100 = (int32_t)(perr * 100.0f);

        spd_x10 = (int32_t)(spd * 10.0f);
        spd_raw_x10 = (int32_t)(spd_raw * 10.0f);
        spd_det_x10 = (int32_t)(spd_det * 10.0f);
        vcmd_x10 = (int32_t)(vcmd * 10.0f);
        sref_x10 = (int32_t)(sref * 10.0f);
        speed_cmd_x10 = (int32_t)(speed_cmd * 10.0f);

        iq_cmd_mA = (int32_t)(iq_cmd * 1000.0f);
        iqref_mA = (int32_t)(iqref * 1000.0f);
        drive_iqref_mA = (int32_t)(drive_iqref_A * 1000.0f);
        travel_x10 = (int32_t)(travel_deg * 10.0f);
        post_travel_x10 =
            (int32_t)(post_contact_travel_deg * 10.0f);
        id_mA = (int32_t)(id * 1000.0f);
        iq_mA = (int32_t)(iq * 1000.0f);

        FormatSignedX100(pos_buf, sizeof(pos_buf), pos_x100);
        FormatSignedX100(ptgt_buf, sizeof(ptgt_buf), ptgt_x100);
        FormatSignedX100(perr_buf, sizeof(perr_buf), perr_x100);

        snprintf(
            msg,
            sizeof(msg),
            "RTOS-FOC CYCLE=%lu/%u MODE=%s TST=%u t=%lums | "
            "ADC/s=%lu FOC/s=%lu EN=%u FLT=%u R=%lu | "
            "POS=%s PTGT=%s PERR=%s deg | "
            "CTRL=%ld.%01ld DET=%ld.%01ld RAW=%ld.%01ld | "
            "CMD=%ld.%01ld VCMD=%ld.%01ld REF=%ld.%01ld rpm | "
            "IqCmd=%ldmA IqRef=%ldmA DriveIq=%ldmA | "
            "TRV=%ld.%01lddeg PTRV=%ld.%01lddeg C=%u CT=%lums | "
            "Id=%ldmA Iq=%ldmA | PDB=%u AHLD=%u G=%lu | "
            "UTXQ=%lu UDROP=%lu UERR=%lu RXQ=%lu RXDROP=%lu\r\n",
            (unsigned long)cycle_no,
            (unsigned int)TIGHTEN_REPEAT_CYCLES,
            MotorControl_ModeName(mode),
            (unsigned int)test_stage,
            (unsigned long)test_ms,
            (unsigned long)adc_rate_hz,
            (unsigned long)foc_rate_hz,
            (unsigned int)foc_en,
            (unsigned int)foc_flt,
            (unsigned long)fault_reason,
            pos_buf,
            ptgt_buf,
            perr_buf,
            (long)(spd_x10 / 10),
            (long)labs(spd_x10 % 10),
            (long)(spd_det_x10 / 10),
            (long)labs(spd_det_x10 % 10),
            (long)(spd_raw_x10 / 10),
            (long)labs(spd_raw_x10 % 10),
            (long)(speed_cmd_x10 / 10),
            (long)labs(speed_cmd_x10 % 10),
            (long)(vcmd_x10 / 10),
            (long)labs(vcmd_x10 % 10),
            (long)(sref_x10 / 10),
            (long)labs(sref_x10 % 10),
            (long)iq_cmd_mA,
            (long)iqref_mA,
            (long)drive_iqref_mA,
            (long)(travel_x10 / 10),
            (long)labs(travel_x10 % 10),
            (long)(post_travel_x10 / 10),
            (long)labs(post_travel_x10 % 10),
            (unsigned int)contact_cond,
            (unsigned long)contact_ms,
            (long)id_mA,
            (long)iq_mA,
            (unsigned int)position_deadband_active,
            (unsigned int)active_hold_enable,
            (unsigned long)encoder_speed_glitch_count,
            (unsigned long)uart_tx_queued,
            (unsigned long)uart_tx_dropped,
            (unsigned long)uart_dma_errors,
            (unsigned long)uart_rx_queued,
            (unsigned long)uart_rx_dropped);

        UART_SendString(msg);
    }
}


static uint8_t AS5047P_ParityIsOdd(uint16_t x)
{
    /* XOR-reduce all 16 bits: 1 means odd number of set bits. */
    x ^= (uint16_t)(x >> 8);
    x ^= (uint16_t)(x >> 4);
    x ^= (uint16_t)(x >> 2);
    x ^= (uint16_t)(x >> 1);
    return (uint8_t)(x & 1U);
}

/*
 * AS5047P SPI command helpers.
 *
 * Command frame:
 *   bit15    = even parity over bits 14..0
 *   bit14    = R/W (1 = read)
 *   bits13:0 = register address
 *
 * Important correction:
 *   A READ of NOP (0x0000) is NOT the raw frame 0x0000.
 *   The correct read-NOP frame is 0xC000 after adding R/W + parity.
 */
#define AS5047P_REG_NOP       0x0000U
#define AS5047P_REG_ERRFL     0x0001U
#define AS5047P_REG_ANGLECOM  0x3FFFU

#define AS5047P_ERRFL_FRERR    (1U << 0)
#define AS5047P_ERRFL_INVCOMM  (1U << 1)
#define AS5047P_ERRFL_PARERR   (1U << 2)

/*
 * The datasheet requires >=350 ns from CSn falling edge to the first clock,
 * and >=350 ns CSn high time between frames.
 *
 * At 170 MHz, 128 explicit NOPs are comfortably longer than 350 ns.
 * The loop overhead only makes this more conservative.
 */
#define AS5047P_CS_GUARD_NOPS  128U

static volatile uint8_t as5047p_diag_verbose = 0U;
static volatile uint16_t as5047p_last_errfl = 0U;


static void AS5047P_CsGuardDelay(void)
{
    for (uint32_t i = 0U; i < AS5047P_CS_GUARD_NOPS; i++)
    {
        __NOP();
    }
}


static uint16_t AS5047P_MakeReadCommand(uint16_t reg)
{
    uint16_t cmd;

    cmd = (uint16_t)((reg & 0x3FFFU) | 0x4000U);

    /*
     * AS5047P_ParityIsOdd(cmd) checks bits 0..15. At this point bit15 is 0,
     * so if the lower 15 bits contain an odd number of ones, set bit15.
     */
    if (AS5047P_ParityIsOdd(cmd) != 0U)
    {
        cmd |= 0x8000U;
    }

    return cmd;
}


static HAL_StatusTypeDef AS5047P_Transfer16(uint16_t tx, uint16_t *rx)
{
    HAL_StatusTypeDef st;
    uint16_t r = 0U;

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_RESET);

    AS5047P_CsGuardDelay();

    st = HAL_SPI_TransmitReceive(&hspi1,
                                 (uint8_t *)&tx,
                                 (uint8_t *)&r,
                                 1U,
                                 10U);

    /*
     * Keep CS low long enough after the last clock before releasing it.
     * This delay is intentionally conservative.
     */
    AS5047P_CsGuardDelay();

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_SET);

    /*
     * Guarantee the inter-frame CS-high time before another transaction.
     */
    AS5047P_CsGuardDelay();

    if (rx != NULL)
    {
        *rx = r;
    }

    return st;
}


/*
 * Generic two-frame AS5047P register read.
 *
 * Frame 1: READ requested register.
 * Frame 2: READ NOP; MISO returns data requested by frame 1.
 *
 * The second command is the properly formed READ-NOP command (0xC000),
 * not the old raw 0x0000 frame.
 */
static HAL_StatusTypeDef AS5047P_ReadRegisterFrame(uint16_t reg,
                                                   uint16_t *response)
{
    HAL_StatusTypeDef st1;
    HAL_StatusTypeDef st2;
    uint16_t dummy = 0U;
    uint16_t rsp = 0U;
    uint16_t cmd = AS5047P_MakeReadCommand(reg);
    uint16_t nop_cmd = AS5047P_MakeReadCommand(AS5047P_REG_NOP);

    st1 = AS5047P_Transfer16(cmd, &dummy);

    if (st1 != HAL_OK)
    {
        if (as5047p_diag_verbose != 0U)
        {
            char msg[200];

            snprintf(msg,
                     sizeof(msg),
                     "ENC FAIL: FRAME1 REG=0x%04X CMD=0x%04X "
                     "HAL=%d SPI_STATE=%d SPI_ERR=0x%08lX RX=0x%04X\r\n",
                     (unsigned int)reg,
                     (unsigned int)cmd,
                     (int)st1,
                     (int)HAL_SPI_GetState(&hspi1),
                     (unsigned long)HAL_SPI_GetError(&hspi1),
                     (unsigned int)dummy);

            UART_SendString(msg);
        }

        return st1;
    }

    st2 = AS5047P_Transfer16(nop_cmd, &rsp);

    if (st2 != HAL_OK)
    {
        if (as5047p_diag_verbose != 0U)
        {
            char msg[220];

            snprintf(msg,
                     sizeof(msg),
                     "ENC FAIL: FRAME2 REG=0x%04X NOP=0x%04X "
                     "HAL=%d SPI_STATE=%d SPI_ERR=0x%08lX "
                     "DUMMY=0x%04X RX=0x%04X\r\n",
                     (unsigned int)reg,
                     (unsigned int)nop_cmd,
                     (int)st2,
                     (int)HAL_SPI_GetState(&hspi1),
                     (unsigned long)HAL_SPI_GetError(&hspi1),
                     (unsigned int)dummy,
                     (unsigned int)rsp);

            UART_SendString(msg);
        }

        return st2;
    }

    if (AS5047P_ParityIsOdd(rsp) != 0U)
    {
        if (as5047p_diag_verbose != 0U)
        {
            char msg[200];

            snprintf(msg,
                     sizeof(msg),
                     "ENC FAIL: DATA PARITY REG=0x%04X "
                     "RX=0x%04X PAR=1 EF=%u\r\n",
                     (unsigned int)reg,
                     (unsigned int)rsp,
                     (unsigned int)((rsp & 0x4000U) != 0U));

            UART_SendString(msg);
        }

        return HAL_ERROR;
    }

    if (response != NULL)
    {
        *response = rsp;
    }

    return HAL_OK;
}


/*
 * Read ERRFL (0x0001).
 *
 * Reading ERRFL automatically clears the AS5047P communication-error flags.
 * Bits:
 *   bit2 PARERR
 *   bit1 INVCOMM
 *   bit0 FRERR
 */
static HAL_StatusTypeDef AS5047P_ReadAndClearErrorFlags(uint16_t *flags)
{
    HAL_StatusTypeDef st;
    uint16_t rsp = 0U;
    uint16_t f;

    st = AS5047P_ReadRegisterFrame(AS5047P_REG_ERRFL, &rsp);

    if (st != HAL_OK)
    {
        return st;
    }

    f = (uint16_t)(rsp & 0x0007U);
    as5047p_last_errfl = f;

    if (flags != NULL)
    {
        *flags = f;
    }

    if (as5047p_diag_verbose != 0U)
    {
        char msg[220];

        snprintf(msg,
                 sizeof(msg),
                 "ENC ERRFL: RAW=0x%04X FLAGS=0x%X "
                 "PARERR=%u INVCOMM=%u FRERR=%u EF=%u\r\n",
                 (unsigned int)rsp,
                 (unsigned int)f,
                 (unsigned int)((f & AS5047P_ERRFL_PARERR) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_INVCOMM) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_FRERR) != 0U),
                 (unsigned int)((rsp & 0x4000U) != 0U));

        UART_SendString(msg);
    }

    return HAL_OK;
}


static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw)
{
    HAL_StatusTypeDef st;
    uint16_t response = 0U;
    uint16_t errfl = 0U;

    /*
     * First attempt with the corrected command sequence:
     *
     *   READ ANGLECOM (0xFFFF)
     *   READ NOP      (0xC000)
     */
    st = AS5047P_ReadRegisterFrame(AS5047P_REG_ANGLECOM,
                                   &response);

    if (st != HAL_OK)
    {
        return st;
    }

    /*
     * EF reports an error in the previous SPI command frame.
     * Read ERRFL to identify and clear the latched communication error,
     * then retry the angle once.
     */
    if ((response & 0x4000U) != 0U)
    {
        if (as5047p_diag_verbose != 0U)
        {
            char msg[180];

            snprintf(msg,
                     sizeof(msg),
                     "ENC EF: ANGLE_RX=0x%04X -> reading ERRFL\r\n",
                     (unsigned int)response);

            UART_SendString(msg);
        }

        if (AS5047P_ReadAndClearErrorFlags(&errfl) != HAL_OK)
        {
            return HAL_ERROR;
        }

        st = AS5047P_ReadRegisterFrame(AS5047P_REG_ANGLECOM,
                                       &response);

        if (st != HAL_OK)
        {
            return st;
        }

        if ((response & 0x4000U) != 0U)
        {
            if (as5047p_diag_verbose != 0U)
            {
                char msg[220];

                snprintf(msg,
                         sizeof(msg),
                         "ENC FAIL: EF STILL SET AFTER CLEAR "
                         "ANGLE_RX=0x%04X LAST_ERRFL=0x%X\r\n",
                         (unsigned int)response,
                         (unsigned int)errfl);

                UART_SendString(msg);
            }

            return HAL_ERROR;
        }

        if (as5047p_diag_verbose != 0U)
        {
            char msg[180];

            snprintf(msg,
                     sizeof(msg),
                     "ENC RECOVERED: ERRFL=0x%X ANGLE_RX=0x%04X\r\n",
                     (unsigned int)errfl,
                     (unsigned int)response);

            UART_SendString(msg);
        }
    }

    if (raw != NULL)
    {
        *raw = (uint16_t)(response & 0x3FFFU);
    }

    return HAL_OK;
}

static float Encoder_ElectricalAngleRad(uint16_t raw)
{
    int32_t d = (int32_t)raw - (int32_t)ELECTRICAL_ZERO_RAW;
    float theta;

    /* Shortest signed mechanical displacement in one 14-bit revolution. */
    if (d > 8191)
        d -= (int32_t)AS5047P_CPR;
    else if (d < -8192)
        d += (int32_t)AS5047P_CPR;

    theta = (float)ENCODER_DIRECTION *
            (float)d *
            TWO_PI_F *
            (float)POLE_PAIRS /
            (float)AS5047P_CPR;

    theta = fmodf(theta, TWO_PI_F);
    if (theta < 0.0f)
        theta += TWO_PI_F;

    return theta;
}

static HAL_StatusTypeDef AS5047P_StartupCheck(void)
{
    uint32_t ok = 0U;
    uint16_t raw = 0U;
    uint16_t startup_errfl = 0U;
    char msg[220];

    HAL_GPIO_WritePin(AS5047_CS_GPIO_Port,
                      AS5047_CS_Pin,
                      GPIO_PIN_SET);

    HAL_Delay(5U);

    /*
     * Startup-only verbose diagnostics.
     *
     * First read ERRFL once. This both tells us whether a stale communication
     * error was latched and clears the ERRFL register before the 20-read test.
     */
    as5047p_diag_verbose = 1U;

    if (AS5047P_ReadAndClearErrorFlags(&startup_errfl) == HAL_OK)
    {
        snprintf(msg,
                 sizeof(msg),
                 "AS5047P PRE-CLEAR ERRFL=0x%X "
                 "PARERR=%u INVCOMM=%u FRERR=%u\r\n",
                 (unsigned int)startup_errfl,
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_PARERR) != 0U),
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_INVCOMM) != 0U),
                 (unsigned int)((startup_errfl &
                                 AS5047P_ERRFL_FRERR) != 0U));

        UART_SendString(msg);
    }
    else
    {
        UART_SendString(
            "AS5047P PRE-CLEAR ERRFL read failed\r\n");
    }

    HAL_Delay(1U);

    /*
     * Perform 20 corrected ANGLECOM reads.
     *
     * Each read now uses:
     *   frame 1 = READ ANGLECOM = 0xFFFF
     *   frame 2 = READ NOP      = 0xC000
     */
    for (uint32_t i = 0U; i < 20U; i++)
    {
        if (AS5047P_ReadAngle(&raw) == HAL_OK)
        {
            ok++;
            encoder_raw = raw;
            encoder_theta_e = Encoder_ElectricalAngleRad(raw);
            encoder_valid = 1U;
        }
        else
        {
            encoder_error_count++;
        }

        HAL_Delay(1U);
    }

    as5047p_diag_verbose = 0U;

    snprintf(msg,
             sizeof(msg),
             "AS5047P startup: OK=%lu/20 RAW=%u ELEC=%ludeg "
             "ERR=%lu LAST_ERRFL=0x%X\r\n",
             (unsigned long)ok,
             (unsigned int)encoder_raw,
             (unsigned long)(encoder_theta_e * 180.0f / PI_F),
             (unsigned long)encoder_error_count,
             (unsigned int)as5047p_last_errfl);

    UART_SendString(msg);

    return (ok >= 15U) ? HAL_OK : HAL_ERROR;
}


static uint16_t Median3_U16(uint16_t a, uint16_t b, uint16_t c)
{
    uint16_t t;

    if (a > b)
    {
        t = a; a = b; b = t;
    }

    if (b > c)
    {
        t = b; b = c; c = t;
    }

    if (a > b)
    {
        t = a; a = b; b = t;
    }

    return b;
}

static void FormatSignedX10(char *buf, size_t n, int32_t x10)
{
    int32_t a = (x10 < 0) ? -x10 : x10;

    snprintf(buf, n,
             "%s%ld.%01ld",
             (x10 < 0) ? "-" : "",
             (long)(a / 10),
             (long)(a % 10));
}

static void FormatSignedX100(char *buf, size_t n, int32_t x100)
{
    int32_t a = (x100 < 0) ? -x100 : x100;

    snprintf(buf, n,
             "%s%ld.%02ld",
             (x100 < 0) ? "-" : "",
             (long)(a / 100),
             (long)(a % 100));
}

static void PowerStage_Disable(void)
{
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
}

static void PowerStage_Enable(void)
{
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_SET);
}

static void PWM_SetDuty(float du, float dv, float dw)
{
    uint32_t u, v, w;

    if (du < 0.02f) du = 0.02f;
    if (du > 0.98f) du = 0.98f;
    if (dv < 0.02f) dv = 0.02f;
    if (dv > 0.98f) dv = 0.98f;
    if (dw < 0.02f) dw = 0.02f;
    if (dw > 0.98f) dw = 0.98f;

    u = (uint32_t)(du * (float)(PWM_ARR + 1U));
    v = (uint32_t)(dv * (float)(PWM_ARR + 1U));
    w = (uint32_t)(dw * (float)(PWM_ARR + 1U));

    if (u > PWM_ARR) u = PWM_ARR;
    if (v > PWM_ARR) v = PWM_ARR;
    if (w > PWM_ARR) w = PWM_ARR;

    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, u);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_2, v);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_3, w);
}

static float ClampFloat(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

static void FOC_ResetController(void)
{
    foc_id_ref_A = FOC_ID_REF_A;
    foc_iq_ref_A = 0.0f;

    encoder_position_deg = 0.0f;
    position_target_deg = 0.0f;
    position_error_deg = 0.0f;
    position_speed_cmd_rpm = 0.0f;
    position_deadband_active = 1U;
    active_hold_enable = 0U;
    active_hold_iq_cmd_A = 0.0f;
    position_error_sign_prev = 0;
    position_direction_reset_count = 0U;

    speed_target_rpm = SPEED_REF_RPM;
    speed_ref_rpm = SPEED_REF_RPM;
    speed_integrator_A = 0.0f;
    speed_integrator_bleed_active = 0U;
    speed_overspeed_bleed_active = 0U;
    speed_error_rpm = 0.0f;
    speed_p_term_A = 0.0f;

    speed_diag_time_s = 0.0f;
    speed_diag_speed_integral = 0.0f;
    speed_diag_error_integral = 0.0f;
    speed_diag_min_rpm = 0.0f;
    speed_diag_max_rpm = 0.0f;
    speed_diag_valid = 0U;

    stall_timer_s = 0.0f;
    stall_trip_position_deg = 0.0f;
    stall_trip_target_deg = 0.0f;
    stall_trip_ref_rpm = 0.0f;
    stall_trip_speed_rpm = 0.0f;

    encoder_speed_rpm = 0.0f;
    encoder_omega_e_rad_s = 0.0f;

    encoder_rpm_instant = 0.0f;
    encoder_speed_detect_rpm = 0.0f;

    encoder_speed_dt_accum_s = 0.0f;
    encoder_speed_glitch_count = 0U;
    encoder_speed_glitch_streak = 0U;

    encoder_speed_detect_counts = 0;
    encoder_speed_detect_dt_s = 0.0f;
    encoder_speed_detect_samples = 0U;

    foc_id_A = 0.0f;
    foc_iq_A = 0.0f;
    foc_vd_V = 0.0f;
    foc_vq_V = 0.0f;

    foc_int_d_V = 0.0f;
    foc_int_q_V = 0.0f;

    foc_duty_u = 0.5f;
    foc_duty_v = 0.5f;
    foc_duty_w = 0.5f;

    PWM_SetDuty(0.5f, 0.5f, 0.5f);
}

/*
 * 20 kHz current-loop step.
 *
 * Coordinate convention:
 *   Clarke:
 *     Ialpha = IU
 *     Ibeta  = (IU + 2*IV)/sqrt(3)
 *
 *   Park:
 *     Id =  Ialpha*cos(theta_e) + Ibeta*sin(theta_e)
 *     Iq = -Ialpha*sin(theta_e) + Ibeta*cos(theta_e)
 *
 *   Inverse Park:
 *     Valpha = Vd*cos(theta_e) - Vq*sin(theta_e)
 *     Vbeta  = Vd*sin(theta_e) + Vq*cos(theta_e)
 *
 * Current polarity has already been verified in the previous test:
 *     positive current = ZERO_RAW - RAW
 */
static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw)
{
    const float count_to_A =
        ((float)ADC_VREF_MV) /
        ((float)ADC_FULL_SCALE * (float)CURRENT_GAIN_MV_PER_A);

    float iu_A;
    float iv_A;
    float iw_A;
    float i_alpha;
    float i_beta;
    float theta;
    float s;
    float c;
    float id_A;
    float iq_A;
    float err_d;
    float err_q;
    float vd;
    float vq;
    float mag2;
    float limit2;
    float v_alpha;
    float v_beta;
    float vu;
    float vv;
    float vw;
    float vmax;
    float vmin;
    float voffset;
    float du;
    float dv;
    float dw;

    if ((foc_enable == 0U) || (encoder_valid == 0U))
    {
        PWM_SetDuty(0.5f, 0.5f, 0.5f);
        return;
    }

    iu_A = ((float)((int32_t)iu_zero_raw - (int32_t)u_raw)) * count_to_A;
    iv_A = ((float)((int32_t)iv_zero_raw - (int32_t)v_raw)) * count_to_A;
    iw_A = -(iu_A + iv_A);

    /*
     * Independent software current trip. At this bring-up point the requested
     * torque current is only 0.20 A, so 2 A is intentionally conservative.
     */
    if ((fabsf(iu_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iv_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iw_A) > FOC_CURRENT_TRIP_A))
    {
        foc_trip_iu_mA = (int32_t)(iu_A * 1000.0f);
        foc_trip_iv_mA = (int32_t)(iv_A * 1000.0f);
        foc_trip_iw_mA = (int32_t)(iw_A * 1000.0f);
        foc_fault_reason = 1U;
        foc_fault = 1U;
        foc_enable = 0U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                          DRIVER_SD_Pin,
                          GPIO_PIN_RESET);
        PWM_SetDuty(0.5f, 0.5f, 0.5f);
        return;
    }

    i_alpha = iu_A;
    i_beta = (iu_A + 2.0f * iv_A) * 0.57735026919f;

    theta = encoder_theta_e_pred;
    s = sinf(theta);
    c = cosf(theta);

    id_A =  i_alpha * c + i_beta * s;
    iq_A = -i_alpha * s + i_beta * c;

    err_d = foc_id_ref_A - id_A;
    err_q = foc_iq_ref_A - iq_A;

    /*
     * PI controller:
     *   Kp ~= L*w_c = 0.08 V/A
     *   Ki ~= R*w_c = 188 V/(A*s)
     * for roughly 300 Hz initial current-loop bandwidth using the present
     * R ~= 0.10 ohm and L ~= 42.3 uH motor estimates.
     */
    foc_int_d_V += FOC_CURRENT_KI_V_PER_AS * err_d * FOC_TS_S;
    foc_int_q_V += FOC_CURRENT_KI_V_PER_AS * err_q * FOC_TS_S;

    foc_int_d_V = ClampFloat(foc_int_d_V,
                             -FOC_INTEGRATOR_LIMIT_V,
                              FOC_INTEGRATOR_LIMIT_V);
    foc_int_q_V = ClampFloat(foc_int_q_V,
                             -FOC_INTEGRATOR_LIMIT_V,
                              FOC_INTEGRATOR_LIMIT_V);

    vd = FOC_CURRENT_KP_V_PER_A * err_d + foc_int_d_V;
    vq = FOC_CURRENT_KP_V_PER_A * err_q + foc_int_q_V;

    /*
     * Vector-voltage limit. 0.8 V is intentionally small for the first
     * closed-loop test so the motor cannot run away to a high no-load speed.
     */
    mag2 = vd * vd + vq * vq;
    limit2 = FOC_VOLTAGE_LIMIT_V * FOC_VOLTAGE_LIMIT_V;

    if (mag2 > limit2)
    {
        float scale = FOC_VOLTAGE_LIMIT_V / sqrtf(mag2);

        vd *= scale;
        vq *= scale;

        /*
         * Simple tracking anti-windup: after vector saturation, move each
         * integrator to the value consistent with the saturated command.
         */
        foc_int_d_V = vd - FOC_CURRENT_KP_V_PER_A * err_d;
        foc_int_q_V = vq - FOC_CURRENT_KP_V_PER_A * err_q;

        foc_int_d_V = ClampFloat(foc_int_d_V,
                                 -FOC_INTEGRATOR_LIMIT_V,
                                  FOC_INTEGRATOR_LIMIT_V);
        foc_int_q_V = ClampFloat(foc_int_q_V,
                                 -FOC_INTEGRATOR_LIMIT_V,
                                  FOC_INTEGRATOR_LIMIT_V);
    }

    /* Inverse Park. */
    v_alpha = vd * c - vq * s;
    v_beta  = vd * s + vq * c;

    /*
     * alpha-beta -> three phase, then centered zero-sequence injection.
     * This is the usual min/max common-mode form of SVPWM.
     */
    vu = v_alpha;
    vv = -0.5f * v_alpha + 0.86602540378f * v_beta;
    vw = -0.5f * v_alpha - 0.86602540378f * v_beta;

    vmax = vu;
    if (vv > vmax) vmax = vv;
    if (vw > vmax) vmax = vw;

    vmin = vu;
    if (vv < vmin) vmin = vv;
    if (vw < vmin) vmin = vw;

    voffset = -0.5f * (vmax + vmin);

    vu += voffset;
    vv += voffset;
    vw += voffset;

    du = 0.5f + vu / FOC_DC_BUS_V;
    dv = 0.5f + vv / FOC_DC_BUS_V;
    dw = 0.5f + vw / FOC_DC_BUS_V;

    PWM_SetDuty(du, dv, dw);

    foc_id_A = id_A;
    foc_iq_A = iq_A;
    foc_vd_V = vd;
    foc_vq_V = vq;

    foc_duty_u = du;
    foc_duty_v = dv;
    foc_duty_w = dw;

    /* Predict electrical angle at the 20 kHz current-loop rate. */
    encoder_theta_e_pred += encoder_omega_e_rad_s * FOC_TS_S;
    while (encoder_theta_e_pred >= TWO_PI_F) encoder_theta_e_pred -= TWO_PI_F;
    while (encoder_theta_e_pred < 0.0f) encoder_theta_e_pred += TWO_PI_F;

    foc_control_count++;
}


/*
 * Update AS5047P, estimate mechanical speed, correct predicted electrical
 * angle, then run the outer 1 kHz-ish speed PI. dt_s is the ACTUAL elapsed
 * time; this is important because UART status output is blocking.
 */
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)
{
    uint16_t raw = 0U;
    float theta_e;
    static MotorControlMode_t previous_mode = MOTOR_MODE_IDLE;

    if ((dt_s <= 0.0f) || (dt_s > 0.100f))
        dt_s = 0.001f;

    encoder_speed_dt_accum_s += dt_s;

    if (AS5047P_ReadAngle(&raw) != HAL_OK)
    {
        encoder_error_count++;
        encoder_valid = 0U;
        foc_fault_reason = 2U;
        foc_fault = 1U;
        return HAL_ERROR;
    }

    theta_e = Encoder_ElectricalAngleRad(raw);

    if (encoder_prev_valid != 0U)
    {
        int32_t d_raw = (int32_t)raw - (int32_t)encoder_prev_raw;
        float dt_meas = encoder_speed_dt_accum_s;
        float rpm_inst;
        float alpha;
        float mech_rad_s;

        MotorControlMode_t mode = motor_control_mode;

        float speed_err = 0.0f;
        float p_term = 0.0f;
        float i_candidate = speed_integrator_A;
        float iq_unsat = 0.0f;
        float iq_cmd = 0.0f;

        float speed_iq_limit_A = SPEED_IQ_LIMIT_A;
        float stall_iq_min_A = STALL_IQ_MIN_A;
        float stall_ref_min_rpm = STALL_REF_MIN_RPM;
        float stall_timeout_s = STALL_TIMEOUT_S;

        uint8_t run_speed_pi = 0U;
        uint8_t allow_stall_check = 0U;

        if (d_raw > 8191)
            d_raw -= (int32_t)AS5047P_CPR;
        else if (d_raw < -8192)
            d_raw += (int32_t)AS5047P_CPR;

        if (dt_meas <= 0.0f)
            dt_meas = 0.001f;

        rpm_inst =
            ((float)ENCODER_DIRECTION * (float)d_raw * 60.0f) /
            ((float)AS5047P_CPR * dt_meas);

        encoder_rpm_instant = rpm_inst;

        /*
         * Reject one impossible encoder jump without publishing it into the
         * control angle or speed estimator.
         */
        if (fabsf(rpm_inst) > SPEED_INSTANT_PLAUSIBLE_RPM)
        {
            encoder_speed_glitch_count++;
            encoder_speed_glitch_streak++;

            if (encoder_speed_glitch_streak >= SPEED_GLITCH_STREAK_LIMIT)
            {
                foc_fault_reason = 2U;
                foc_fault = 1U;
                encoder_valid = 0U;
                return HAL_ERROR;
            }

            return HAL_OK;
        }

        encoder_speed_glitch_streak = 0U;

        encoder_position_deg +=
            (float)ENCODER_DIRECTION *
            (float)d_raw *
            360.0f /
            (float)AS5047P_CPR;

        /*
         * -------------------------------------------------------------
         * CONTROL SPEED
         * -------------------------------------------------------------
         *
         * Restore the previously proven controller feedback path:
         *
         *     1 ms instantaneous rpm -> 20 ms first-order LPF
         *
         * This filtered value is used by the Speed PI and existing protection
         * logic.  Do not put the 50 ms detector into this feedback path.
         */
        alpha = dt_meas / (SPEED_FILTER_TAU_S + dt_meas);
        alpha = ClampFloat(alpha, 0.0f, 1.0f);

        encoder_speed_rpm +=
            alpha * (rpm_inst - encoder_speed_rpm);

        /*
         * -------------------------------------------------------------
         * DETECTION SPEED
         * -------------------------------------------------------------
         *
         * Independently accumulate accepted mechanical angle for about 50 ms.
         * This gives a slower average speed for future seating/contact
         * detection and is intentionally NOT used by the Speed PI.
         */
        encoder_speed_detect_counts +=
            (int32_t)ENCODER_DIRECTION * d_raw;
        encoder_speed_detect_dt_s += dt_meas;
        encoder_speed_detect_samples++;

        if ((encoder_speed_detect_dt_s >= SPEED_DETECT_WINDOW_S) &&
            (encoder_speed_detect_samples >= SPEED_DETECT_MIN_SAMPLES))
        {
            encoder_speed_detect_rpm =
                ((float)encoder_speed_detect_counts * 60.0f) /
                ((float)AS5047P_CPR * encoder_speed_detect_dt_s);

            encoder_speed_detect_counts = 0;
            encoder_speed_detect_dt_s = 0.0f;
            encoder_speed_detect_samples = 0U;
        }

        mech_rad_s = encoder_speed_rpm * TWO_PI_F / 60.0f;

        /*
         * Electrical prediction uses the fast CONTROL speed, not the slow
         * detection speed.  Measured theta_e is still refreshed every 1 ms.
         */
        encoder_omega_e_rad_s =
            (float)POLE_PAIRS * mech_rad_s;

        if (fabsf(encoder_speed_rpm) > SPEED_OVERSPEED_RPM)
        {
            foc_fault_reason = 3U;
            foc_fault = 1U;
            foc_enable = 0U;
            PowerStage_Disable();
            PWM_SetDuty(0.5f, 0.5f, 0.5f);
            return HAL_ERROR;
        }

        /*
         * Every mode transition clears state that must never leak from one
         * controller into another.  This is the key boundary between the
         * application-level command API and the reusable 1 kHz control layer.
         */
        if (mode != previous_mode)
        {
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;
            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;
            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;

            stall_timer_s = 0.0f;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;

            position_error_sign_prev = 0;
            position_deadband_active = 1U;

            previous_mode = mode;
        }

        /*
         * Always keep position diagnostics meaningful, even when the active
         * controller is SPEED or IQ mode.
         */
        position_target_deg = motor_position_command_deg;
        position_error_deg =
            position_target_deg - encoder_position_deg;

        /*
         * -------------------------------------------------------------
         * MODE SELECTION
         * -------------------------------------------------------------
         */
        if (mode == MOTOR_MODE_IDLE)
        {
            position_speed_cmd_rpm = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;

            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;
            position_deadband_active = 1U;

            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;
            stall_timer_s = 0.0f;

            foc_iq_ref_A = 0.0f;
        }
        else if (mode == MOTOR_MODE_IQ)
        {
            /*
             * Direct torque/current command.
             *
             * This bypasses Position P and Speed PI, but still uses the proven
             * 20 kHz Id/Iq current controller.  The 2 A phase-current trip and
             * 300 rpm overspeed protection remain active.
             *
             * The position-test stall detector is intentionally disabled in
             * this mode because "speed near zero + current high" can be a
             * legitimate tightening condition.
             */
            position_speed_cmd_rpm = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;

            speed_integrator_A = 0.0f;
            speed_integrator_bleed_active = 0U;
            speed_overspeed_bleed_active = 0U;

            active_hold_enable = 0U;
            active_hold_iq_cmd_A = 0.0f;
            position_deadband_active = 0U;

            speed_error_rpm = 0.0f;
            speed_p_term_A = 0.0f;
            stall_timer_s = 0.0f;

            foc_iq_ref_A =
                ClampFloat(motor_iq_command_A,
                           -MOTOR_DIRECT_IQ_LIMIT_A,
                            MOTOR_DIRECT_IQ_LIMIT_A);
        }
        else
        {
            /*
             * POSITION and SPEED modes both feed the same proven speed PI.
             * Only the source of speed_target_rpm is different.
             */
            run_speed_pi = 1U;
            allow_stall_check = 1U;

            if (mode == MOTOR_MODE_SPEED)
            {
                active_hold_enable = 0U;
                active_hold_iq_cmd_A = 0.0f;
                position_deadband_active = 0U;
                position_speed_cmd_rpm = 0.0f;

                speed_target_rpm =
                    ClampFloat(motor_speed_command_rpm,
                               -MOTOR_SPEED_API_LIMIT_RPM,
                                MOTOR_SPEED_API_LIMIT_RPM);

                speed_iq_limit_A = MOTOR_SPEED_IQ_LIMIT_A;
                stall_iq_min_A = MOTOR_SPEED_STALL_IQ_MIN_A;
                stall_ref_min_rpm = MOTOR_SPEED_STALL_REF_MIN_RPM;
                stall_timeout_s = MOTOR_SPEED_STALL_TIMEOUT_S;
            }
            else
            {
                float position_speed_limit_rpm =
                    POSITION_SPEED_LIMIT_RPM;

                /*
                 * Optional hybrid active hold for a position command.
                 * This preserves the already validated STG5 behavior, but it
                 * is now a property of a POSITION command instead of being
                 * hard-coded to profile stage 5.
                 */
                if (motor_position_active_hold != 0U)
                {
                    float hold_abs_err = fabsf(position_error_deg);

                    if (active_hold_enable != 0U)
                    {
                        if (hold_abs_err >= ACTIVE_HOLD_EXIT_DEG)
                        {
                            active_hold_enable = 0U;
                            active_hold_iq_cmd_A = 0.0f;
                            speed_integrator_A = 0.0f;
                            speed_ref_rpm = 0.0f;
                            stall_timer_s = 0.0f;
                        }
                    }
                    else
                    {
                        if (hold_abs_err <= ACTIVE_HOLD_ENTER_DEG)
                        {
                            active_hold_enable = 1U;
                            active_hold_iq_cmd_A = 0.0f;
                            speed_integrator_A = 0.0f;
                            speed_ref_rpm = 0.0f;
                            stall_timer_s = 0.0f;
                        }
                    }
                }
                else
                {
                    active_hold_enable = 0U;
                    active_hold_iq_cmd_A = 0.0f;
                }

                /*
                 * Position deadband hysteresis.
                 */
                if (position_deadband_active != 0U)
                {
                    if (fabsf(position_error_deg) >=
                        POSITION_DEADBAND_EXIT_DEG)
                    {
                        position_deadband_active = 0U;
                    }
                }
                else
                {
                    if (fabsf(position_error_deg) <=
                        POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_deadband_active = 1U;
                    }
                }

                /*
                 * Position-error sign reversal -> remove stale speed-I history.
                 */
                {
                    int8_t position_sign_now = 0;

                    if (position_error_deg >
                        POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_sign_now = 1;
                    }
                    else if (position_error_deg <
                             -POSITION_DEADBAND_ENTER_DEG)
                    {
                        position_sign_now = -1;
                    }

                    if (position_sign_now != 0)
                    {
                        if ((position_error_sign_prev != 0) &&
                            (position_sign_now !=
                             position_error_sign_prev))
                        {
                            speed_integrator_A = 0.0f;
                            speed_integrator_bleed_active = 0U;
                            speed_overspeed_bleed_active = 0U;
                            stall_timer_s = 0.0f;
                            position_direction_reset_count++;
                        }

                        position_error_sign_prev =
                            position_sign_now;
                    }
                }

                if ((motor_position_active_hold != 0U) &&
                    (active_hold_enable == 0U))
                {
                    position_speed_limit_rpm =
                        STG5_RETURN_SPEED_LIMIT_RPM;

                    speed_iq_limit_A =
                        STG5_RETURN_IQ_LIMIT_A;

                    stall_iq_min_A =
                        STG5_RETURN_STALL_IQ_MIN_A;
                }

                if (active_hold_enable != 0U)
                {
                    position_speed_cmd_rpm = 0.0f;
                    speed_target_rpm = 0.0f;
                    speed_ref_rpm = 0.0f;
                }
                else if (position_deadband_active != 0U)
                {
                    position_speed_cmd_rpm = 0.0f;
                    speed_target_rpm = 0.0f;
                }
                else
                {
                    position_speed_cmd_rpm =
                        POSITION_KP_RPM_PER_DEG *
                        position_error_deg;

                    position_speed_cmd_rpm =
                        ClampFloat(position_speed_cmd_rpm,
                                   -position_speed_limit_rpm,
                                    position_speed_limit_rpm);

                    speed_target_rpm =
                        position_speed_cmd_rpm;
                }
            }
        }

        /*
         * -------------------------------------------------------------
         * Shared SPEED PI for POSITION and SPEED modes
         * -------------------------------------------------------------
         */
        if (run_speed_pi != 0U)
        {
            if (speed_ref_rpm < speed_target_rpm)
            {
                float step =
                    SPEED_RAMP_UP_RPM_PER_S * dt_meas;

                speed_ref_rpm += step;

                if (speed_ref_rpm > speed_target_rpm)
                    speed_ref_rpm = speed_target_rpm;
            }
            else if (speed_ref_rpm > speed_target_rpm)
            {
                float step =
                    SPEED_RAMP_DOWN_RPM_PER_S * dt_meas;

                speed_ref_rpm -= step;

                if (speed_ref_rpm < speed_target_rpm)
                    speed_ref_rpm = speed_target_rpm;
            }

            speed_err =
                speed_ref_rpm - encoder_speed_rpm;

            p_term =
                SPEED_KP_A_PER_RPM * speed_err;

            speed_error_rpm = speed_err;
            speed_p_term_A = p_term;

            speed_diag_time_s += dt_meas;
            speed_diag_speed_integral +=
                encoder_speed_rpm * dt_meas;
            speed_diag_error_integral +=
                speed_err * dt_meas;

            if (speed_diag_valid == 0U)
            {
                speed_diag_min_rpm = encoder_speed_rpm;
                speed_diag_max_rpm = encoder_speed_rpm;
                speed_diag_valid = 1U;
            }
            else
            {
                if (encoder_speed_rpm < speed_diag_min_rpm)
                    speed_diag_min_rpm = encoder_speed_rpm;

                if (encoder_speed_rpm > speed_diag_max_rpm)
                    speed_diag_max_rpm = encoder_speed_rpm;
            }

            /*
             * IBLD only belongs to position settling.  OBLD is useful in both
             * POSITION and SPEED modes.
             */
            if ((mode == MOTOR_MODE_POSITION) &&
                (position_deadband_active != 0U) &&
                (fabsf(speed_ref_rpm) <=
                 SPEED_INT_BLEED_REF_MAX_RPM) &&
                (fabsf(encoder_speed_rpm) <=
                 SPEED_INT_BLEED_SPD_MAX_RPM))
            {
                float bleed_step =
                    SPEED_INT_BLEED_A_PER_S * dt_meas;

                speed_integrator_bleed_active = 1U;
                speed_overspeed_bleed_active = 0U;

                if (speed_integrator_A > bleed_step)
                    speed_integrator_A -= bleed_step;
                else if (speed_integrator_A < -bleed_step)
                    speed_integrator_A += bleed_step;
                else
                    speed_integrator_A = 0.0f;

                i_candidate = speed_integrator_A;
            }
            else if ((fabsf(encoder_speed_rpm) >=
                      SPEED_OVERSPEED_BLEED_MIN_SPD_RPM) &&
                     (fabsf(speed_err) >=
                      SPEED_OVERSPEED_BLEED_ERR_RPM) &&
                     ((speed_err * encoder_speed_rpm) < 0.0f) &&
                     ((speed_integrator_A *
                       encoder_speed_rpm) > 0.0f))
            {
                float bleed_step =
                    SPEED_OVERSPEED_I_BLEED_A_PER_S *
                    dt_meas;

                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 1U;

                if (speed_integrator_A > bleed_step)
                    speed_integrator_A -= bleed_step;
                else if (speed_integrator_A < -bleed_step)
                    speed_integrator_A += bleed_step;
                else
                    speed_integrator_A = 0.0f;

                i_candidate = speed_integrator_A;
            }
            else
            {
                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 0U;

                i_candidate =
                    speed_integrator_A +
                    SPEED_KI_A_PER_RPM_S *
                    speed_err *
                    dt_meas;
            }

            i_candidate =
                ClampFloat(i_candidate,
                           -SPEED_INT_LIMIT_A,
                            SPEED_INT_LIMIT_A);

            iq_unsat = p_term + i_candidate;

            iq_cmd =
                ClampFloat(iq_unsat,
                           -speed_iq_limit_A,
                            speed_iq_limit_A);

            if ((speed_integrator_bleed_active != 0U) ||
                (speed_overspeed_bleed_active != 0U))
            {
                speed_integrator_A = i_candidate;
            }
            else if ((iq_unsat == iq_cmd) ||
                     ((iq_cmd >= speed_iq_limit_A) &&
                      (speed_err < 0.0f)) ||
                     ((iq_cmd <= -speed_iq_limit_A) &&
                      (speed_err > 0.0f)))
            {
                speed_integrator_A = i_candidate;
            }

            foc_iq_ref_A = iq_cmd;

            /*
             * POSITION active hold overrides the speed PI only inside the
             * small-error hold region.
             */
            if ((mode == MOTOR_MODE_POSITION) &&
                (active_hold_enable != 0U))
            {
                float hold_iq =
                    ACTIVE_HOLD_KP_A_PER_DEG *
                    position_error_deg -
                    ACTIVE_HOLD_KD_A_PER_RPM *
                    encoder_speed_rpm;

                hold_iq =
                    ClampFloat(hold_iq,
                               -ACTIVE_HOLD_IQ_LIMIT_A,
                                ACTIVE_HOLD_IQ_LIMIT_A);

                active_hold_iq_cmd_A = hold_iq;
                foc_iq_ref_A = hold_iq;

                speed_integrator_A = 0.0f;
                speed_integrator_bleed_active = 0U;
                speed_overspeed_bleed_active = 0U;
                stall_timer_s = 0.0f;
                allow_stall_check = 0U;
            }
            else
            {
                active_hold_iq_cmd_A = 0.0f;
            }

            /*
             * Mode-aware stall protection.
             *
             * SPEED mode uses a lower current threshold because its first
             * validation test is intentionally limited to +/-0.25 A.
             * IQ mode has no "requested speed", so this position-test stall
             * detector is not applicable there.
             */
            if ((allow_stall_check != 0U) &&
                (fabsf(speed_ref_rpm) > stall_ref_min_rpm) &&
                (fabsf(encoder_speed_rpm) <
                 STALL_SPEED_MAX_RPM) &&
                (fabsf(foc_iq_ref_A) >= stall_iq_min_A))
            {
                stall_timer_s += dt_meas;

                if (stall_timer_s >= stall_timeout_s)
                {
                    stall_trip_position_deg =
                        encoder_position_deg;
                    stall_trip_target_deg =
                        position_target_deg;
                    stall_trip_ref_rpm =
                        speed_ref_rpm;
                    stall_trip_speed_rpm =
                        encoder_speed_rpm;

                    foc_fault_reason = 4U;
                    foc_fault = 1U;
                    foc_enable = 0U;

                    foc_iq_ref_A = 0.0f;
                    speed_integrator_A = 0.0f;

                    PowerStage_Disable();
                    PWM_SetDuty(0.5f, 0.5f, 0.5f);
                    return HAL_ERROR;
                }
            }
            else
            {
                stall_timer_s = 0.0f;
            }
        }
    }

    /*
     * Publish only an ACCEPTED encoder sample.
     */
    encoder_prev_raw = raw;
    encoder_prev_valid = 1U;
    encoder_speed_dt_accum_s = 0.0f;

    encoder_raw = raw;
    encoder_theta_e = theta_e;
    encoder_theta_e_pred = theta_e;
    encoder_valid = 1U;

    return HAL_OK;
}


static void PWM_StartAll(void)
{
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_2, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_3, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_4, ADC_TRIGGER_CCR4);

    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4) != HAL_OK) Error_Handler();

    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2) != HAL_OK) Error_Handler();
    if (HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3) != HAL_OK) Error_Handler();

    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_1) != HAL_OK) Error_Handler();
    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_2) != HAL_OK) Error_Handler();
    if (HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_3) != HAL_OK) Error_Handler();
}

static void PWM_StopAll(void)
{
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIMEx_PWMN_Stop(&htim1, TIM_CHANNEL_3);

    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_2);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_3);
    HAL_TIM_PWM_Stop(&htim1, TIM_CHANNEL_4);
}

static HAL_StatusTypeDef ADC_ReadRegularMedian(ADC_HandleTypeDef *hadc,
                                               uint32_t channel,
                                               uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};
    uint16_t x[ADC_MEDIAN_SAMPLES];
    HAL_StatusTypeDef st;
    char dbg[180];
    const char *adc_name = (hadc->Instance == ADC1) ? "ADC1" :
                           (hadc->Instance == ADC2) ? "ADC2" : "ADC?";

    /*
     * Diagnostic version: print only when a HAL operation fails.
     */
    st = HAL_ADC_Stop(hadc);
    if ((st != HAL_OK) && (st != HAL_ERROR))
    {
        snprintf(dbg, sizeof(dbg),
                 "ZERO DBG %s: HAL_ADC_Stop st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
        UART_SendString(dbg);
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    cfg.SamplingTime = ADC_SAMPLETIME_47CYCLES_5;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0;

    st = HAL_ADC_ConfigChannel(hadc, &cfg);
    if (st != HAL_OK)
    {
        snprintf(dbg, sizeof(dbg),
                 "ZERO DBG %s: ConfigChannel FAIL st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
        UART_SendString(dbg);
        return HAL_ERROR;
    }

    for (uint32_t i = 0U; i < ADC_MEDIAN_SAMPLES; i++)
    {
        st = HAL_ADC_Start(hadc);
        if (st != HAL_OK)
        {
            snprintf(dbg, sizeof(dbg),
                     "ZERO DBG %s: Start FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
            UART_SendString(dbg);
            return HAL_ERROR;
        }

        st = HAL_ADC_PollForConversion(hadc, 10U);
        if (st != HAL_OK)
        {
            snprintf(dbg, sizeof(dbg),
                     "ZERO DBG %s: Poll FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX tick=%lu\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc),
                     (unsigned long)HAL_GetTick());
            UART_SendString(dbg);
            HAL_ADC_Stop(hadc);
            return HAL_ERROR;
        }

        x[i] = (uint16_t)HAL_ADC_GetValue(hadc);

        st = HAL_ADC_Stop(hadc);
        if ((st != HAL_OK) && (st != HAL_ERROR))
        {
            snprintf(dbg, sizeof(dbg),
                     "ZERO DBG %s: Stop-after-read st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
            UART_SendString(dbg);
        }
    }

    for (uint32_t i = 0U; i < ADC_MEDIAN_SAMPLES - 1U; i++)
    {
        for (uint32_t j = i + 1U; j < ADC_MEDIAN_SAMPLES; j++)
        {
            if (x[j] < x[i])
            {
                uint16_t t = x[i];
                x[i] = x[j];
                x[j] = t;
            }
        }
    }

    *raw = x[ADC_MEDIAN_SAMPLES / 2U];
    return HAL_OK;
}

static HAL_StatusTypeDef ADC_CurrentZeroCalibrate(void)
{
    uint32_t su = 0U;
    uint32_t sv = 0U;
    uint16_t u = 0U;
    uint16_t v = 0U;
    char msg[220];

    /*
     * PC3 / AMP_IW is intentionally NOT used.
     * Only PA0/ADC1=IU and PA1/ADC2=IV are calibrated.
     */
    PowerStage_Disable();
    PWM_StopAll();

    UART_SendString(
        "\r\nTWO-PHASE CURRENT ZERO CALIBRATION\r\n"
        "CTRL_SD=LOW, PWM=OFF, PD6010B 12V must be ON\r\n"
        "AMP_IU->PA0/ADC1, AMP_IV->PA1/ADC2, PC3 unused\r\n");

    UART_SendString("ZERO DBG: settling 1000 ms...\r\n");
    HAL_Delay(1000U);
    UART_SendString("ZERO DBG: settle complete, starting ADC reads\r\n");

    for (uint32_t i = 0U; i < ADC_ZERO_CAL_SAMPLES; i++)
    {
        if (ADC_ReadRegularMedian(&hadc1, ADC_CHANNEL_1, &u) != HAL_OK)
        {
            snprintf(msg, sizeof(msg),
                     "ZERO DBG: ADC1 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            UART_SendString(msg);
            return HAL_ERROR;
        }

        if (ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_2, &v) != HAL_OK)
        {
            snprintf(msg, sizeof(msg),
                     "ZERO DBG: ADC2 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            UART_SendString(msg);
            return HAL_ERROR;
        }

        su += u;
        sv += v;

        if ((i == 0U) || (i == 99U) || (i == 249U) || (i == 499U))
        {
            snprintf(msg, sizeof(msg),
                     "ZERO DBG sample=%lu U=%u V=%u tick=%lu\r\n",
                     (unsigned long)i,
                     (unsigned int)u,
                     (unsigned int)v,
                     (unsigned long)HAL_GetTick());
            UART_SendString(msg);
        }

        HAL_Delay(1U);
    }

    iu_zero_raw = (uint16_t)(su / ADC_ZERO_CAL_SAMPLES);
    iv_zero_raw = (uint16_t)(sv / ADC_ZERO_CAL_SAMPLES);

    snprintf(msg, sizeof(msg),
             "ZERO DBG AVG: U=%u V=%u valid-range=1000..2200\r\n",
             (unsigned int)iu_zero_raw,
             (unsigned int)iv_zero_raw);
    UART_SendString(msg);

    /*
     * W is reconstructed, so this is only a numerical center for pseudo-raw W.
     * It is NOT a measurement from PC3.
     */
    iw_zero_raw = 2048U;

    if ((iu_zero_raw < 1000U) || (iu_zero_raw > 2200U) ||
        (iv_zero_raw < 1000U) || (iv_zero_raw > 2200U))
    {
        UART_SendString(
            "ZERO DBG: average OUT OF RANGE. Check PD6010B 12V/current-sense outputs.\r\n");
        return HAL_ERROR;
    }

    snprintf(msg, sizeof(msg),
             "ZERO CAL DONE\r\n"
             "U_ZERO_RAW=%u\r\n"
             "V_ZERO_RAW=%u\r\n"
             "W is reconstructed; PC3/AMP_IW is not used\r\n",
             iu_zero_raw,
             iv_zero_raw);

    UART_SendString(msg);
    return HAL_OK;
}

static int32_t Current_FromRaw_mA(uint16_t raw, uint16_t zero_raw)
{
    /*
     * Current polarity used in this build:
     *     positive current = zero_raw - raw
     */
    int32_t d = (int32_t)zero_raw - (int32_t)raw;
    int64_t ma = (int64_t)d * ADC_VREF_MV * 1000LL;
    ma /= ((int64_t)ADC_FULL_SCALE * CURRENT_GAIN_MV_PER_A);
    return (int32_t)ma;
}

static void ADC_GetInjectedSnapshot(uint16_t *u,
                                    uint16_t *v,
                                    uint16_t *w,
                                    uint32_t *seq)
{
    uint32_t s1, s2;

    do
    {
        s1 = injected_seq_count;
        *u = iu_inj_raw;
        *v = iv_inj_raw;
        *w = iw_inj_raw;
        s2 = injected_seq_count;
    }
    while (s1 != s2);

    *seq = s2;
}


static HAL_StatusTypeDef ADC_ConfigIndependentSameTrigger(void)
{
    ADC_MultiModeTypeDef multimode = {0};
    ADC_InjectionConfTypeDef inj = {0};

    /*
     * Use ADC1 and ADC2 independently, but arm both from the SAME
     * TIM1 TRGO2 rising edge.
     *
     * Both ADCs use the same synchronous ADC clock and the same 12.5-cycle
     * sample time, so IU and IV are sampled concurrently without relying on
     * the ADC dual-mode master/slave state machine.
     */
    multimode.Mode = ADC_MODE_INDEPENDENT;
    multimode.DMAAccessMode = ADC_DMAACCESSMODE_DISABLED;
    multimode.TwoSamplingDelay = ADC_TWOSAMPLINGDELAY_1CYCLE;

    if (HAL_ADCEx_MultiModeConfigChannel(&hadc1, &multimode) != HAL_OK)
        return HAL_ERROR;

    /* ADC1 injected: IU on PA0 / IN1 */
    inj.InjectedChannel = ADC_CHANNEL_1;
    inj.InjectedRank = ADC_INJECTED_RANK_1;
    inj.InjectedSamplingTime = ADC_SAMPLETIME_12CYCLES_5;
    inj.InjectedSingleDiff = ADC_SINGLE_ENDED;
    inj.InjectedOffsetNumber = ADC_OFFSET_NONE;
    inj.InjectedOffset = 0;
    inj.InjectedNbrOfConversion = 1;
    inj.InjectedDiscontinuousConvMode = DISABLE;
    inj.AutoInjectedConv = DISABLE;
    inj.QueueInjectedContext = DISABLE;
    inj.ExternalTrigInjecConv = ADC_EXTERNALTRIGINJEC_T1_TRGO2;
    inj.ExternalTrigInjecConvEdge = ADC_EXTERNALTRIGINJECCONV_EDGE_RISING;
    inj.InjecOversamplingMode = DISABLE;

    if (HAL_ADCEx_InjectedConfigChannel(&hadc1, &inj) != HAL_OK)
        return HAL_ERROR;

    /* ADC2 injected: IV on PA1 / IN2, same trigger and same sample time */
    inj.InjectedChannel = ADC_CHANNEL_2;
    inj.InjectedRank = ADC_INJECTED_RANK_1;

    if (HAL_ADCEx_InjectedConfigChannel(&hadc2, &inj) != HAL_OK)
        return HAL_ERROR;

    return HAL_OK;
}


static HAL_StatusTypeDef ADC_RunZeroCalibrate(void)
{
    uint16_t static_u = iu_zero_raw;
    uint16_t static_v = iv_zero_raw;

    uint32_t start_tick;
    uint32_t valid;
    uint32_t rejected;
    uint32_t sum_u;
    uint32_t sum_v;

    char msg[320];

    PWM_SetDuty(0.5f, 0.5f, 0.5f);

    UART_SendString(
        "\r\n"
        "PWM-ON TWO-ADC RUN ZERO CALIBRATION\r\n"
        "ADC1=IU, ADC2=IV, same TIM1 TRGO2 trigger\r\n"
        "PWM=20kHz, U/V/W=50%, CTRL_SD=HIGH, MOD=0\r\n"
        "Settling...\r\n");

    HAL_Delay(RUN_ZERO_SETTLE_MS);

    {
        uint32_t primask = __get_PRIMASK();

        __disable_irq();

        run_zero_sum_u = 0U;
        run_zero_sum_v = 0U;
        run_zero_valid_count = 0U;
        run_zero_reject_count = 0U;

        run_zero_cal_done = 0U;
        run_zero_cal_active = 1U;

        if (primask == 0U)
            __enable_irq();
    }

    start_tick = HAL_GetTick();

    while (run_zero_cal_done == 0U)
    {
        if (adc_fault != 0U)
        {
            run_zero_cal_active = 0U;
            return HAL_ERROR;
        }

        if ((HAL_GetTick() - start_tick) > RUN_ZERO_TIMEOUT_MS)
        {
            run_zero_cal_active = 0U;
            UART_SendString("TWO ADC RUN ZERO CAL TIMEOUT\r\n");
            return HAL_TIMEOUT;
        }
    }

    valid = run_zero_valid_count;
    rejected = run_zero_reject_count;
    sum_u = run_zero_sum_u;
    sum_v = run_zero_sum_v;

    if (valid == 0U)
        return HAL_ERROR;

    iu_zero_raw = (uint16_t)(sum_u / valid);
    iv_zero_raw = (uint16_t)(sum_v / valid);

    if ((iu_zero_raw < 1000U) || (iu_zero_raw > 2200U) ||
        (iv_zero_raw < 1000U) || (iv_zero_raw > 2200U))
    {
        UART_SendString("TWO ADC RUN ZERO CAL INVALID\r\n");
        return HAL_ERROR;
    }

    snprintf(
        msg,
        sizeof(msg),
        "TWO ADC RUN ZERO CAL DONE\r\n"
        "STATIC ZERO : U=%u V=%u\r\n"
        "RUN ZERO    : U=%u V=%u\r\n"
        "SHIFT(count): U=%ld V=%ld\r\n"
        "VALID=%lu REJECTED=%lu\r\n"
        "IW is reconstructed from -(IU+IV)\r\n"
        "========================================\r\n",
        static_u,
        static_v,
        iu_zero_raw,
        iv_zero_raw,
        (long)((int32_t)iu_zero_raw - (int32_t)static_u),
        (long)((int32_t)iv_zero_raw - (int32_t)static_v),
        (unsigned long)valid,
        (unsigned long)rejected);

    UART_SendString(msg);

    /*
     * Seed the published frame with zero-current values. iw_zero_raw is only
     * used as a numerical center for the reconstructed pseudo-raw W value.
     */
    {
        uint32_t primask = __get_PRIMASK();

        __disable_irq();

        iu_inj_raw = iu_zero_raw;
        iv_inj_raw = iv_zero_raw;
        iw_inj_raw = iw_zero_raw;

        current_valid_count = 0U;
        current_reject_count = 0U;
        current_reject_streak = 0U;
        current_last_rejected_sum_counts = 0;

        current_prev_raw_u = iu_zero_raw;
        current_prev_raw_v = iv_zero_raw;
        current_prev_raw_valid = 0U;

        current_med_u[0] = iu_zero_raw;
        current_med_u[1] = iu_zero_raw;
        current_med_u[2] = iu_zero_raw;
        current_med_v[0] = iv_zero_raw;
        current_med_v[1] = iv_zero_raw;
        current_med_v[2] = iv_zero_raw;
        current_med_index = 0U;
        current_med_count = 0U;

        current_filter_enable = 1U;

        if (primask == 0U)
            __enable_irq();
    }

    UART_SendString(
        "Two-ADC step filter ON: |dIU| or |dIV| > about 0.40A => hold last valid frame\r\n");

    return HAL_OK;
}


void HAL_ADCEx_InjectedConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    /*
     * ADC1 owns the interrupt callback. ADC1 and ADC2 are independent ADCs,
     * but both are armed by the same TIM1 TRGO2 edge with identical sampling
     * time, so ADC2 JDR1 belongs to the same PWM sampling event.
     */
    if (hadc->Instance == ADC1)
    {
        uint16_t u = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc1, ADC_INJECTED_RANK_1);

        uint16_t v = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc2, ADC_INJECTED_RANK_1);

        /*
         * ADC2 is intentionally used without an ADC2 interrupt. Reading JDR1
         * consumes its JEOC result; clear JEOS as housekeeping after the read.
         */
        __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);

        injected_seq_count++;

        /*
         * PWM-on zero calibration uses only the two physically measured
         * simultaneous currents.
         */
        if (run_zero_cal_active != 0U)
        {
            int32_t du0 = (int32_t)u - (int32_t)iu_zero_raw;
            int32_t dv0 = (int32_t)v - (int32_t)iv_zero_raw;

            if ((du0 >= -RUN_ZERO_MAX_DELTA_COUNTS) &&
                (du0 <=  RUN_ZERO_MAX_DELTA_COUNTS) &&
                (dv0 >= -RUN_ZERO_MAX_DELTA_COUNTS) &&
                (dv0 <=  RUN_ZERO_MAX_DELTA_COUNTS))
            {
                run_zero_sum_u += u;
                run_zero_sum_v += v;
                run_zero_valid_count++;

                if (run_zero_valid_count >= RUN_ZERO_CAL_SAMPLES)
                {
                    run_zero_cal_active = 0U;
                    run_zero_cal_done = 1U;
                }
            }
            else
            {
                run_zero_reject_count++;
            }
        }

        /*
         * Reconstruct W in ADC-count units:
         *   dW = -(dU + dV)
         *
         * iw_zero_raw is retained only as the center of this pseudo-raw
         * representation so the existing mA conversion/printing path remains
         * unchanged.
         */
        {
            int32_t du = (int32_t)u - (int32_t)iu_zero_raw;
            int32_t dv = (int32_t)v - (int32_t)iv_zero_raw;
            int32_t w_recon = (int32_t)iw_zero_raw - du - dv;

            if (w_recon < 0)
                w_recon = 0;
            else if (w_recon > (int32_t)ADC_FULL_SCALE)
                w_recon = (int32_t)ADC_FULL_SCALE;

            if (current_filter_enable != 0U)
            {
                int32_t step_u = 0;
                int32_t step_v = 0;
                uint8_t frame_ok = 1U;

                if (current_prev_raw_valid != 0U)
                {
                    step_u = (int32_t)u - (int32_t)current_prev_raw_u;
                    step_v = (int32_t)v - (int32_t)current_prev_raw_v;

                    if ((step_u < -CURRENT_STEP_REJECT_COUNTS) ||
                        (step_u >  CURRENT_STEP_REJECT_COUNTS) ||
                        (step_v < -CURRENT_STEP_REJECT_COUNTS) ||
                        (step_v >  CURRENT_STEP_REJECT_COUNTS))
                    {
                        frame_ok = 0U;
                    }
                }

                /*
                 * ALWAYS advance the physical previous-sample reference.
                 * This prevents one rejected spike from causing a permanent
                 * reject streak against a stale last-accepted sample.
                 */
                current_prev_raw_u = u;
                current_prev_raw_v = v;
                current_prev_raw_valid = 1U;

                if (frame_ok != 0U)
                {
                    uint16_t u_pub = u;
                    uint16_t v_pub = v;
                    int32_t du_pub;
                    int32_t dv_pub;
                    int32_t w_pub;

                    /*
                     * Only samples that already passed the physical step gate
                     * enter the median buffer.
                     */
                    current_med_u[current_med_index] = u;
                    current_med_v[current_med_index] = v;
                    current_med_index =
                        (uint8_t)((current_med_index + 1U) % 3U);

                    if (current_med_count < 3U)
                        current_med_count++;

                    if (current_med_count >= 3U)
                    {
                        u_pub = Median3_U16(current_med_u[0],
                                            current_med_u[1],
                                            current_med_u[2]);
                        v_pub = Median3_U16(current_med_v[0],
                                            current_med_v[1],
                                            current_med_v[2]);
                    }

                    /*
                     * Reconstruct W from the exact U/V pair that is published
                     * to the FOC, so Clarke/Park always sees a self-consistent
                     * three-phase current set.
                     */
                    du_pub =
                        (int32_t)u_pub - (int32_t)iu_zero_raw;
                    dv_pub =
                        (int32_t)v_pub - (int32_t)iv_zero_raw;
                    w_pub =
                        (int32_t)iw_zero_raw - du_pub - dv_pub;

                    if (w_pub < 0)
                        w_pub = 0;
                    else if (w_pub > (int32_t)ADC_FULL_SCALE)
                        w_pub = (int32_t)ADC_FULL_SCALE;

                    iu_inj_raw = u_pub;
                    iv_inj_raw = v_pub;
                    iw_inj_raw = (uint16_t)w_pub;

                    current_valid_count++;
                    current_reject_streak = 0U;
                }
                else
                {
                    int32_t abs_u = (step_u >= 0) ? step_u : -step_u;
                    int32_t abs_v = (step_v >= 0) ? step_v : -step_v;

                    current_reject_count++;
                    current_reject_streak++;
                    current_last_rejected_sum_counts =
                        (abs_u > abs_v) ? abs_u : abs_v;

                    /*
                     * A true isolated spike normally rejects at most the spike
                     * sample and possibly the return sample. 20 consecutive
                     * raw-to-raw large jumps still indicates a real problem.
                     */
                    if (current_reject_streak >= CURRENT_REJECT_STREAK_LIMIT)
                    {
                        adc_fault = 1U;

                        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                                          DRIVER_SD_Pin,
                                          GPIO_PIN_RESET);
                    }
                }
            }
            else
            {
                iu_inj_raw = u;
                iv_inj_raw = v;
                iw_inj_raw = (uint16_t)w_recon;
            }

            /*
             * Run the current PI on the latest ACCEPTED current frame.
             * If the physical sample was rejected as a spike, iu_inj_raw /
             * iv_inj_raw still contain the previous valid frame, so the
             * controller automatically holds that current sample briefly.
             */
            if ((foc_enable != 0U) && (run_zero_cal_active == 0U))
            {
                FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw);
            }
        }
    }
}


void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc->Instance == ADC1) || (hadc->Instance == ADC2))
    {
        adc_fault = 1U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                          DRIVER_SD_Pin,
                          GPIO_PIN_RESET);
    }
}
/* USER CODE END 0 */


static void StartupTask(void *argument)
{
    uint32_t seq_start;
    uint32_t seq_delta;
    char msg[160];

    (void)argument;

    /*
     * Scheduler is running from this point onward, so HAL_Delay() and
     * FreeRTOS timing can safely coexist through the shared SysTick handler.
     */
    g_rtos_started = 1U;

    /*
     * IMPORTANT:
     * Keep UART blocking during StartupTask bring-up.
     *
     * StartupTask runs at priority 5 and its existing HAL_Delay() calls are
     * busy-wait based.  If the low-priority DMA TX service task is created
     * here, it cannot run while StartupTask remains runnable, so all startup
     * messages appear to disappear after "Starting scheduler...".
     *
     * We therefore switch to async TX only after all bring-up/calibration
     * work is complete.
     */
    PowerStage_Disable();
    foc_enable = 0U;
    foc_fault = 0U;
    foc_fault_reason = 0U;
    adc_fault = 0U;

    UART_SendString(
        "\r\n"
        "==========================================\r\n"
        "FreeRTOS generic motor-control API + TighteningTask test\r\n"
        "PARAMETER V2 build: Protocol V2 + Flash SAVE/LOAD + CRC32\r\n"
        "StartupTask active\r\n"
        "Power stage starts DISABLED\r\n"
        "==========================================\r\n");

    {
        TightenParamsFlashLoadStatus_t param_load_status;
        char param_msg[160];

        param_load_status = TightenParams_LoadFromFlash();

        if (param_load_status == PARAM_FLASH_LOAD_OK)
        {
            snprintf(
                param_msg,
                sizeof(param_msg),
                "PARAM FLASH: LOADED CRC32=0x%08lX RUNDOWN_RPM=%lu\r\n",
                (unsigned long)tighten_params_last_crc32,
                (unsigned long)tighten_params.rundown_rpm);
        }
        else
        {
            tighten_params = tighten_params_defaults;
            tighten_params_flash_valid = 0U;
            tighten_params_dirty = 0U;
            tighten_params_last_crc32 = 0U;

            snprintf(
                param_msg,
                sizeof(param_msg),
                "PARAM FLASH: NO VALID RECORD -> DEFAULTS RUNDOWN_RPM=%lu\r\n",
                (unsigned long)tighten_params.rundown_rpm);
        }

        UART_SendString(param_msg);
    }

    /*
     * 1) ADC hardware calibration.
     */
    if (HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendString("ADC1 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_Calibration_Start(&hadc2, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendString("ADC2 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    /*
     * 2) Static current zero with bridge disabled / PWM stopped.
     */
    if (ADC_CurrentZeroCalibrate() != HAL_OK)
    {
        UART_SendString("STATIC CURRENT ZERO CAL FAILED\r\n");
        Error_Handler();
    }

    /*
     * 3) Encoder sanity check.
     */
    if (AS5047P_StartupCheck() != HAL_OK)
    {
        UART_SendString(
            "AS5047P STARTUP CHECK FAILED - POWER STAGE STAYS OFF\r\n");
        PowerStage_Disable();
        Error_Handler();
    }

    /*
     * 4) Configure and arm the 20 kHz injected ADC chain.
     */
    if (ADC_ConfigIndependentSameTrigger() != HAL_OK)
    {
        UART_SendString("ADC1/ADC2 SAME-TRIGGER CONFIG ERROR\r\n");
        Error_Handler();
    }

    UART_SendString(
        "ADC1/ADC2 independent same-trigger mode configured\r\n"
        "Both injected groups use TIM1 TRGO2 rising edge\r\n");

    if (HAL_ADCEx_InjectedStart(&hadc2) != HAL_OK)
    {
        UART_SendString("ADC2 INDEPENDENT INJECTED ARM ERROR\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_InjectedStart_IT(&hadc1) != HAL_OK)
    {
        UART_SendString("ADC1 INDEPENDENT INJECTED START ERROR\r\n");
        Error_Handler();
    }

    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PWM_StartAll();

    UART_SendString(
        "PWM started at 50/50/50\r\n"
        "Checking 20kHz ADC injected chain...\r\n");

    seq_start = injected_seq_count;
    vTaskDelay(pdMS_TO_TICKS(100U));
    seq_delta = injected_seq_count - seq_start;

    snprintf(msg, sizeof(msg),
             "Injected IRQ count/100ms=%lu\r\n",
             (unsigned long)seq_delta);
    UART_SendString(msg);

    if (seq_delta < 500U)
    {
        UART_SendString("ERROR: injected trigger/IRQ count too low\r\n");
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * 5) Enable the bridge ONLY with all three PWM duties at 50%.
     *    Equal phase commands mean zero commanded line-line voltage.
     */
    foc_enable = 0U;
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PowerStage_Enable();

    UART_SendString(
        "\r\nCTRL_SD=HIGH\r\n"
        "Bridge enabled at 50/50/50, FOC still OFF, Iq_ref=0\r\n");

    /*
     * Give gate driver / current-sense circuitry a short settling time.
     */
    vTaskDelay(pdMS_TO_TICKS(50U));

    /*
     * 6) Measure current offsets again in the real PWM-switching environment.
     */
    if (ADC_RunZeroCalibrate() != HAL_OK)
    {
        UART_SendString("PWM-ON RUN ZERO CAL ERROR\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * 7) Refresh encoder immediately before closing the current loop.
     */
    {
        uint16_t raw_enc = 0U;

        if (AS5047P_ReadAngle(&raw_enc) != HAL_OK)
        {
            UART_SendString("ENCODER READ FAILED BEFORE FOC ENABLE\r\n");
            foc_enable = 0U;
            PowerStage_Disable();
            PWM_StopAll();
            Error_Handler();
        }

        encoder_raw = raw_enc;
        encoder_theta_e = Encoder_ElectricalAngleRad(raw_enc);
        encoder_theta_e_pred = encoder_theta_e;
        encoder_prev_raw = raw_enc;
        encoder_prev_valid = 1U;
        encoder_speed_rpm = 0.0f;
        encoder_omega_e_rad_s = 0.0f;
        encoder_rpm_instant = 0.0f;
        encoder_speed_dt_accum_s = 0.0f;
        encoder_speed_glitch_count = 0U;
        encoder_speed_glitch_streak = 0U;
        encoder_valid = 1U;
    }

    /*
     * 8) Reset current-controller state and explicitly force zero torque.
     */
    FOC_ResetController();

    foc_fault = 0U;
    foc_fault_reason = 0U;
    adc_fault = 0U;

    foc_id_ref_A = 0.0f;
    foc_iq_ref_A = 0.0f;

    /*
     * 9) Enable ONLY the 20 kHz current controller.
     *
     * The 1 kHz position/speed outer-loop function is NOT called in this
     * build, so no intentional torque command can be generated.
     */
    foc_enable = 1U;

    MotorControl_SetIdle();

    UART_SendString(
        "\r\n"
        "==========================================\r\n"
        "GENERIC MOTOR-CONTROL API ENABLED\r\n"
        "Current loop    : ADC ISR @ 20kHz\r\n"
        "Motor control   : MotorControlTask @ 1kHz\r\n"
        "Application     : TighteningTask @ 100Hz, command-driven\r\n"
        "Protocol        : ProtocolTask @ 5ms\r\n"
        "Monitor         : 3s IDLE / 1s ACTIVE\r\n"
        "UART TX runtime : DMA1_CH1 + 8KiB ring\r\n"
        "UART RX runtime : DMA1_CH2 circular + 512B RX ring\r\n"
        "Protocol V2     : <REQ_ID> <COMMAND>, correlated replies\r\n"
        "Parameters      : GET/SET + SAVE/LOAD Flash + CRC32\r\n"
        "Commands        : HELP / PING / STATUS / START / STOP / RESULT\r\n"
        "Modes           : IDLE / POSITION / SPEED / IQ\r\n"
        "Test            : one tightening cycle per START command\r\n"
        "RUNDOWN         : runtime parameter, SPEED Iq limit +/-0.40A\r\n"
        "Contact         : runtime thresholds\r\n"
        "SEATING         : runtime current/time\r\n"
        "TIGHTENING      : runtime stage currents/times\r\n"
        "HOLD            : runtime current/time\r\n"
        "Torque abort    : runtime speed/travel limits\r\n"
        "UART            : CTRL/DET/RAW + DriveIq + TRV/PTRV + C/CT\r\n"
        "Result log      : 100Hz IqAvg/IqMax/CtrlMax/DetAvg/dAng\r\n"
        "Start behavior  : power-up stays IDLE; no automatic rundown\r\n"
        "Phase trip      : 2.0A unchanged\r\n"
        "==========================================\r\n");

    /*
     * Startup/calibration logging above intentionally used the proven blocking
     * UART path.  From this point onward, switch normal RTOS logging to
     * DMA + ring buffer.
     */
    if (UART_Async_Init(&hlpuart1) != HAL_OK)
    {
        static const char warn[] =
            "WARNING: UART async TX init failed; runtime logs stay blocking\r\n";

        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)warn,
                          (uint16_t)(sizeof(warn) - 1U),
                          HAL_MAX_DELAY);
    }
    else
    {
        UART_AsyncSelfTestInfo_t info;
        UART_AsyncSelfTestResult_t test_result;
        char dma_dbg[320];

        /*
         * This blocking line proves UART_Async_Init() returned HAL_OK.
         */
        static const char ok[] =
            "UART ASYNC INIT OK: running DIRECT DMA self-test...\r\n";

        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)ok,
                          (uint16_t)(sizeof(ok) - 1U),
                          HAL_MAX_DELAY);

        /*
         * Bypass RingBuffer and UartTx task completely.
         * This isolates the raw HAL UART-DMA path.
         */
        test_result =
            UART_Async_RunDirectDmaSelfTest(&info);

        snprintf(
            dma_dbg,
            sizeof(dma_dbg),
            "UART DMA SELFTEST RESULT=%u HAL=%u "
            "UG:%lu->%lu DG:%lu->%lu "
            "CNDTR:%lu->%lu REQ=%lu CCR=0x%08lX CR3=0x%08lX\r\n",
            (unsigned int)test_result,
            (unsigned int)info.start_status,
            (unsigned long)info.uart_gstate_before,
            (unsigned long)info.uart_gstate_after,
            (unsigned long)info.dma_state_before,
            (unsigned long)info.dma_state_after,
            (unsigned long)info.dma_remaining_before,
            (unsigned long)info.dma_remaining_after,
            (unsigned long)info.dma_request,
            (unsigned long)info.dma_ccr,
            (unsigned long)info.uart_cr3);

        /*
         * The self-test aborts the UART DMA on timeout, so blocking UART is
         * safe here for all result paths.
         */
        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)dma_dbg,
                          (uint16_t)strlen(dma_dbg),
                          HAL_MAX_DELAY);

        if (test_result == UART_ASYNC_SELFTEST_PASS)
        {
            static const char pass[] =
                "UART DMA SELFTEST PASS -> enabling ring-buffer runtime TX\r\n";

            HAL_UART_Transmit(&hlpuart1,
                              (uint8_t *)pass,
                              (uint16_t)(sizeof(pass) - 1U),
                              HAL_MAX_DELAY);

            UART_SendString(
                "UART ASYNC TX: first queued DMA message\r\n");
        }
        else
        {
            static const char fail[] =
                "UART DMA SELFTEST FAILED -> do not trust async runtime yet\r\n";

            HAL_UART_Transmit(&hlpuart1,
                              (uint8_t *)fail,
                              (uint16_t)(sizeof(fail) - 1U),
                              HAL_MAX_DELAY);
        }
    }

    /*
     * Layer 1B RX path. The TX path remains unchanged and already validated.
     */
    if (UART_RxDma_Init(&hlpuart1) != HAL_OK)
    {
        UART_SendString(
            "WARNING: UART RX DMA init failed; commands unavailable\r\n");
    }
    else
    {
        UART_SendString(
            "UART RX DMA: DMA1_CH2 circular + RX ring READY\r\n");
    }

    /*
     * High-priority deterministic motor-control task.
     */
    if (xTaskCreate(MotorControlTask,
                    "MotorCtrl",
                    768U,
                    NULL,
                    4U,
                    NULL) != pdPASS)
    {
        UART_SendString("MotorControlTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Application-layer tightening task.
     *
     * Priority is intentionally below MotorControlTask.  It can change motor
     * commands, but cannot preempt the 1 kHz control service indefinitely.
     */
    if (xTaskCreate(TighteningTask,
                    "Tighten",
                    768U,
                    NULL,
                    3U,
                    NULL) != pdPASS)
    {
        UART_SendString("TighteningTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Command parser. Same priority as UartTx service; both remain below the
     * application and motor-control tasks.
     */
    if (xTaskCreate(ProtocolTask,
                    "Protocol",
                    512U,
                    NULL,
                    2U,
                    NULL) != pdPASS)
    {
        UART_SendString("ProtocolTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Low-priority UART diagnostics task. Keeping UART out of MotorControlTask
     * prevents serial work from disturbing the 1 kHz control loop.
     */
    if (xTaskCreate(MonitorTask,
                    "Monitor",
                    768U,
                    NULL,
                    1U,
                    NULL) != pdPASS)
    {
        UART_SendString("MonitorTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    UART_SendString(
        "StartupTask complete -> MotorControlTask + TighteningTask + ProtocolTask + MonitorTask running\r\n");

    vTaskDelete(NULL);
}

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
uint32_t last_encoder_update;
uint32_t last_print;
uint32_t last_print_tick;
uint32_t speed_profile_start_tick;
uint32_t stage_settle_start_tick;
uint32_t stage_settle_elapsed_ms;
uint8_t stage_settle_armed;
uint32_t last_print_seq;
uint32_t last_print_reject;
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
  MX_SPI1_Init();
  MX_LPUART1_UART_Init();
  MX_ADC1_Init();
  MX_ADC2_Init();
  /* USER CODE BEGIN 2 */

    /*
     * Start FreeRTOS BEFORE running any startup helper that uses HAL_Delay().
     * StartupTask performs ADC calibration, encoder check, TIM1/ADC bring-up,
     * and then creates MotorControlTask, TighteningTask and MonitorTask.
     */
    PowerStage_Disable();

    UART_SendString(
        "\r\n"
        "Creating FreeRTOS StartupTask...\r\n"
        "Power stage remains DISABLED\r\n");

    if (xTaskCreate(StartupTask,
                    "Startup",
                    768U,
                    NULL,
                    5U,
                    NULL) != pdPASS)
    {
        UART_SendString("StartupTask CREATE FAILED\r\n");
        Error_Handler();
    }

    UART_SendString("Starting scheduler...\r\n");

    vTaskStartScheduler();

    /* A correctly running scheduler never returns here. */
    UART_SendString("ERROR: scheduler returned\r\n");
    PowerStage_Disable();
    PWM_StopAll();
    Error_Handler();

    /*
     * The original power-stage enable and closed-loop FOC startup below are
     * intentionally unreachable in this coexistence-test build.
     */

    /*
     * Enable bridge while the three phase commands are still exactly
     * 50/50/50.  Do NOT start rotating yet.
     */
    PowerStage_Enable();

    UART_SendString(
        "CTRL_SD=HIGH\r\n"
        "Bridge switching at 50/50/50, MOD=0\r\n");

    /*
     * Second zero calibration in the real PWM-switching environment.
     * The resulting RUN ZERO values replace the static zero values.
     */
    if (ADC_RunZeroCalibrate() != HAL_OK)
    {
        UART_SendString(
            "PWM-ON RUN ZERO CAL ERROR\r\n");

        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Refresh encoder once immediately before closing the current loop.
     */
    {
        uint16_t raw_enc = 0U;

        if (AS5047P_ReadAngle(&raw_enc) != HAL_OK)
        {
            UART_SendString("ENCODER READ FAILED BEFORE FOC ENABLE\r\n");
            PowerStage_Disable();
            PWM_StopAll();
            Error_Handler();
        }

        encoder_raw = raw_enc;
        encoder_theta_e = Encoder_ElectricalAngleRad(raw_enc);
        encoder_theta_e_pred = encoder_theta_e;
        encoder_prev_raw = raw_enc;
        encoder_prev_valid = 1U;
        encoder_speed_rpm = 0.0f;
        encoder_omega_e_rad_s = 0.0f;
        encoder_rpm_instant = 0.0f;
        encoder_speed_dt_accum_s = 0.0f;
        encoder_speed_glitch_count = 0U;
        encoder_speed_glitch_streak = 0U;
        encoder_valid = 1U;
    }

    FOC_ResetController();

    /*
     * The bridge is already enabled after the PWM-on run-zero calibration.
     * Enable the 20 kHz current PI with zero Iq first; foreground code then
     * ramps Iq_ref to +0.20 A at only 0.50 A/s.
     */
    foc_enable = 1U;

    UART_SendString(
        "POSITION SEQUENCE 0->+90->0->-90->0 FOC TEST ENABLED\r\n"
        "Mechanical position zero = rotor position at FOC enable\r\n"
        "Profile: 0deg(1s) -> +90 -> 0 -> -90 -> 0; each move waits for |PERR|<=1.30deg and |SPD|<=2rpm continuously 500ms\r\n"
        "Position P: Kp=1.00 rpm/deg, speed limit=+/-20rpm, deadband hysteresis enter=+/-1.00deg exit=+/-1.30deg\r\n"
        "Stage advance: first observe PDB=0 (ARM=1), then require |PERR|<=1.30deg and |SPD|<=2rpm for 500ms\r\n"
        "STG5 HYBRID HOLD: enter AHLD at |PERR|<=2.00deg, exit to cascade at |PERR|>=3.00deg\r\n"
        "AHLD law: Iq=0.100A/deg*PERR - 0.004A/rpm*SPD, clamp +/-0.300A\r\n"
        "Outside hold region STG5 returns with Position->Speed->Iq cascade, limit +/-10rpm and +/-0.35A\r\n"
        "Speed ramp: +200 rpm/s, -200 rpm/s\r\n"
        "Id_ref=0mA; STG0-4 speed PI Iq limit=+/-400mA; STG5 return=+/-350mA; speed I-limit=+/-350mA\r\n"
        "At target: speed-I bleed=0.50A/s while PDB=1, |REF|<=1rpm, |SPD|<=2rpm\r\n"
        "Overspeed I-release: 5.0A/s when P is braking but old I still pushes rotor motion\r\n"
        "PERR direction reversal: clear old speed-PI integral immediately\r\n"
        "STALL: normal >=350mA; STG5 return >=320mA, with |REF|>5rpm and |SPD|<2rpm for 1.0s -> shutdown\r\n"
        "UART period=137ms\r\n"
        "UART shows POS/PTGT/PERR at 0.01deg + VCMD/REF/SPD + speed PI + Id/Iq\r\n"
        "Current filter = proven raw-step reject + median-of-3 accepted samples\r\n"
        "Overspeed protection remains 300rpm\r\n"
        "Positive position/speed = RAW decreases because ENCODER_DIRECTION=-1.\r\n"
        "20kHz electrical-angle prediction remains enabled.\r\n"
        "Single implausible speed samples >600rpm are rejected.\r\n"
        "3 consecutive implausible samples -> encoder fault.\r\n"
        "If a fault occurs, CTRL_SD is driven LOW immediately.\r\n\r\n");

    encoder_position_deg = 0.0f;
    position_target_deg = 0.0f;
    position_error_deg = 0.0f;
    position_speed_cmd_rpm = 0.0f;
    position_deadband_active = 1U;
    active_hold_enable = 0U;
    active_hold_iq_cmd_A = 0.0f;
    position_error_sign_prev = 0;
    position_direction_reset_count = 0U;
    speed_target_rpm = 0.0f;
    speed_ref_rpm = 0.0f;

    stall_timer_s = 0.0f;
    stall_trip_position_deg = 0.0f;
    stall_trip_target_deg = 0.0f;
    stall_trip_ref_rpm = 0.0f;
    stall_trip_speed_rpm = 0.0f;

    speed_profile_stage = 0U;
    active_hold_enable = 0U;
    active_hold_iq_cmd_A = 0.0f;
    speed_profile_start_tick = HAL_GetTick();
    stage_settle_start_tick = 0U;
    stage_settle_elapsed_ms = 0U;
    stage_settle_armed = 0U;

    last_encoder_update = speed_profile_start_tick;
    last_print = speed_profile_start_tick;
    last_print_tick = last_print;
    last_print_seq = injected_seq_count;
    last_print_reject = current_reject_count;
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    uint32_t now = HAL_GetTick();

    /*
     * SETTLE-QUALIFIED POSITION SEQUENCE STATE MACHINE
     *
     * STG0 uses only the initial 1 s hold.
     *
     * STG1..STG4 advance only after:
     *   1) the new target has caused PDB=0 at least once (ARM=1), then
     *   2) |PERR|<=1.30 deg and |SPD|<=2 rpm remain true continuously
     *      for 500 ms (SET reaches 500 ms).
     *
     * If either completion condition is lost before 500 ms completes,
     * SET is reset to 0.
     *
     * STG5 is the final 0 deg hold.
     */
    {
        /*
         * STG5 HYBRID MODE SELECTION WITH HYSTERESIS
         *
         * STG0..STG4 always use the normal position->speed->Iq cascade.
         *
         * In STG5:
         *   hold -> cascade when |PERR| >= 3.0 deg
         *   cascade -> hold when |PERR| <= 2.0 deg
         *
         * Between 2 and 3 deg, preserve the previous mode.  This prevents
         * chatter if the rotor sits close to the mode-switch threshold.
         */
        if (speed_profile_stage < 5U)
        {
            active_hold_enable = 0U;
        }
        else
        {
            float hold_abs_err = fabsf(position_error_deg);

            if (active_hold_enable != 0U)
            {
                if (hold_abs_err >= ACTIVE_HOLD_EXIT_DEG)
                {
                    active_hold_enable = 0U;
                    active_hold_iq_cmd_A = 0.0f;
                    speed_integrator_A = 0.0f;
                    speed_integrator_bleed_active = 0U;
                    speed_overspeed_bleed_active = 0U;
                    stall_timer_s = 0.0f;
                }
            }
            else
            {
                if (hold_abs_err <= ACTIVE_HOLD_ENTER_DEG)
                {
                    active_hold_enable = 1U;
                    active_hold_iq_cmd_A = 0.0f;
                    speed_ref_rpm = 0.0f;
                    speed_target_rpm = 0.0f;
                    speed_integrator_A = 0.0f;
                    speed_integrator_bleed_active = 0U;
                    speed_overspeed_bleed_active = 0U;
                    stall_timer_s = 0.0f;
                }
            }
        }

        if (speed_profile_stage == 0U)
        {
            position_target_deg = POSITION_TARGET_0_DEG;
            stage_settle_armed = 0U;
            stage_settle_start_tick = 0U;
            stage_settle_elapsed_ms = 0U;

            if ((now - speed_profile_start_tick) >=
                POSITION_INITIAL_HOLD_MS)
            {
                speed_profile_stage = 1U;
                position_target_deg = POSITION_TARGET_P90_DEG;
                stage_settle_armed = 0U;
                stage_settle_start_tick = 0U;
                stage_settle_elapsed_ms = 0U;
            }
        }
        else if (speed_profile_stage == 1U)
        {
            position_target_deg = POSITION_TARGET_P90_DEG;
        }
        else if (speed_profile_stage == 2U)
        {
            position_target_deg = POSITION_TARGET_0_DEG;
        }
        else if (speed_profile_stage == 3U)
        {
            position_target_deg = POSITION_TARGET_M90_DEG;
        }
        else if (speed_profile_stage == 4U)
        {
            position_target_deg = POSITION_TARGET_0_DEG;
        }
        else
        {
            speed_profile_stage = 5U;
            position_target_deg = POSITION_TARGET_0_DEG;
            stage_settle_armed = 1U;
            stage_settle_start_tick = 0U;
            stage_settle_elapsed_ms = POSITION_SETTLE_HOLD_MS;
        }

        if ((speed_profile_stage >= 1U) &&
            (speed_profile_stage <= 4U))
        {
            /*
             * Arm only after the NEW target has actually pulled the outer
             * position loop out of the hysteresis deadband.
             */
            if (stage_settle_armed == 0U)
            {
                stage_settle_start_tick = 0U;
                stage_settle_elapsed_ms = 0U;

                if (position_deadband_active == 0U)
                {
                    stage_settle_armed = 1U;
                }
            }
            else
            {
                /*
                 * Stage completion is intentionally independent from PDB.
                 *
                 * A move is considered mechanically settled when:
                 *   |PERR| <= 1.30 deg
                 *   |SPD|  <= 2.00 rpm
                 *
                 * continuously for 500 ms.
                 *
                 * This allows a stage to complete even if static friction /
                 * cogging leaves the rotor around 1.05~1.25 deg from target,
                 * where PDB may still be 0 because its ENTER threshold is
                 * tighter at 1.00 deg.
                 */
                if ((fabsf(position_error_deg) <=
                     POSITION_STAGE_SETTLE_ERR_DEG) &&
                    (fabsf(encoder_speed_rpm) <=
                     POSITION_STAGE_SETTLE_SPD_RPM))
                {
                    if (stage_settle_start_tick == 0U)
                    {
                        stage_settle_start_tick = now;
                        stage_settle_elapsed_ms = 0U;
                    }
                    else
                    {
                        stage_settle_elapsed_ms =
                            now - stage_settle_start_tick;

                        if (stage_settle_elapsed_ms >=
                            POSITION_SETTLE_HOLD_MS)
                        {
                            speed_profile_stage++;

                            stage_settle_armed = 0U;
                            stage_settle_start_tick = 0U;
                            stage_settle_elapsed_ms = 0U;

                            /*
                             * Apply the next target immediately.
                             */
                            if (speed_profile_stage == 2U)
                            {
                                position_target_deg =
                                    POSITION_TARGET_0_DEG;
                            }
                            else if (speed_profile_stage == 3U)
                            {
                                position_target_deg =
                                    POSITION_TARGET_M90_DEG;
                            }
                            else if (speed_profile_stage == 4U)
                            {
                                position_target_deg =
                                    POSITION_TARGET_0_DEG;
                            }
                            else
                            {
                                speed_profile_stage = 5U;
                                active_hold_enable = 1U;
                                position_target_deg =
                                    POSITION_TARGET_0_DEG;
                                stage_settle_armed = 1U;
                                stage_settle_start_tick = 0U;
                                stage_settle_elapsed_ms =
                                    POSITION_SETTLE_HOLD_MS;
                            }
                        }
                    }
                }
                else
                {
                    /*
                     * Completion window was lost before 500 ms elapsed.
                     * Restart the qualification interval from zero.
                     */
                    stage_settle_start_tick = 0U;
                    stage_settle_elapsed_ms = 0U;
                }
            }
        }
    }

    if ((adc_fault != 0U) || (foc_fault != 0U))
    {
        char fault_msg[360];

        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();

        snprintf(
            fault_msg,
            sizeof(fault_msg),
            "\r\nFOC/CURRENT/ADC FAULT - POWER STAGE DISABLED\r\n"
            "adc_fault=%u foc_fault=%u reason=%lu encoder_valid=%u EE=%lu\r\n"
            "trip IU=%ld IV=%ld IW=%ld mA | speed=%ld rpm inst=%ld rpm\r\n"
            "enc_speed_glitch=%lu streak=%lu\r\n"
            "reject_streak=%lu last_bad_counts=%ld\r\n"
            "stall_timer=%lums | stall POSx10=%ld PTGTx10=%ld REFx10=%ld SPDx10=%ld | RCLR=%lu\r\n",
            (unsigned int)adc_fault,
            (unsigned int)foc_fault,
            (unsigned long)foc_fault_reason,
            (unsigned int)encoder_valid,
            (unsigned long)encoder_error_count,
            (long)foc_trip_iu_mA,
            (long)foc_trip_iv_mA,
            (long)foc_trip_iw_mA,
            (long)encoder_speed_rpm,
            (long)encoder_rpm_instant,
            (unsigned long)encoder_speed_glitch_count,
            (unsigned long)encoder_speed_glitch_streak,
            (unsigned long)current_reject_streak,
            (long)current_last_rejected_sum_counts,
            (unsigned long)(stall_timer_s * 1000.0f),
            (long)((int32_t)(stall_trip_position_deg * 10.0f)),
            (long)((int32_t)(stall_trip_target_deg * 10.0f)),
            (long)((int32_t)(stall_trip_ref_rpm * 10.0f)),
            (long)((int32_t)(stall_trip_speed_rpm * 10.0f)),
            (unsigned long)position_direction_reset_count);

        UART_SendString(fault_msg);
        Error_Handler();
    }

    if ((uint32_t)(now - last_encoder_update) >= ENCODER_UPDATE_PERIOD_MS)
    {
        uint32_t elapsed_ms = now - last_encoder_update;
        float dt_s = (float)elapsed_ms * 0.001f;

        /* One real read using the real elapsed time; no catch-up burst. */
        last_encoder_update = now;
        (void)FOC_EncoderSpeedUpdate(dt_s);
    }

    if ((uint32_t)(now - last_print) >= PRINT_PERIOD_MS)
    {
        uint16_t u_raw, v_raw, w_raw;
        uint32_t seq;
        uint32_t dt, dn, fs;
        uint32_t reject_now;
        uint32_t reject_delta;
        int32_t iu, iv, iw;
        int32_t id_ref_mA;
        int32_t iq_ref_mA;
        int32_t id_mA;
        int32_t iq_mA;
        int32_t vd_mV;
        int32_t vq_mV;
        int32_t position_now_print_x100;
        int32_t position_target_print_x100;
        int32_t position_error_print_x100;
        uint32_t stall_print_ms;
        uint32_t int_bleed_print;
        uint32_t overspeed_bleed_print;
        uint32_t position_deadband_print;
        uint32_t stage_arm_print;
        uint32_t stage_settle_print_ms;
        uint32_t active_hold_print;
        int32_t active_hold_iq_print_mA;
        uint32_t dir_reset_print;
        int32_t speed_target_print_rpm;
        int32_t speed_ref_print_rpm;
        int32_t speed_meas_print_rpm;
        int32_t speed_inst_print_rpm;
        int32_t speed_error_print_rpm;
        int32_t speed_avg_print_x10;
        int32_t speed_min_print_x10;
        int32_t speed_max_print_x10;
        int32_t error_avg_print_x10;
        int32_t speed_p_print_mA;
        int32_t speed_i_print_mA;
        uint32_t speed_glitch_print;
        uint32_t profile_time_ms;
        uint32_t profile_stage_print;
        uint32_t duty_u_permille;
        uint32_t duty_v_permille;
        uint32_t duty_w_permille;
        uint32_t enc_angle_deg = 0U;
        uint16_t enc_raw_now;
        uint8_t enc_valid_now;
        uint32_t enc_err_now;
        char pos_buf[24];
        char ptgt_buf[24];
        char perr_buf[24];
        char msg[620];

        last_print = now;
        profile_time_ms = now - speed_profile_start_tick;
        profile_stage_print = speed_profile_stage;
        stage_arm_print = (uint32_t)stage_settle_armed;
        stage_settle_print_ms = stage_settle_elapsed_ms;
        active_hold_print = (uint32_t)active_hold_enable;
        active_hold_iq_print_mA =
            (int32_t)(active_hold_iq_cmd_A * 1000.0f);

        /*
         * Convert the just-finished diagnostic window to 0.1-rpm units.
         * Example: 1503 means 150.3 rpm.
         */
        if ((speed_diag_valid != 0U) && (speed_diag_time_s > 0.0f))
        {
            float speed_avg =
                speed_diag_speed_integral / speed_diag_time_s;
            float error_avg =
                speed_diag_error_integral / speed_diag_time_s;

            speed_avg_print_x10 =
                (int32_t)(speed_avg * 10.0f);
            error_avg_print_x10 =
                (int32_t)(error_avg * 10.0f);
            speed_min_print_x10 =
                (int32_t)(speed_diag_min_rpm * 10.0f);
            speed_max_print_x10 =
                (int32_t)(speed_diag_max_rpm * 10.0f);
        }
        else
        {
            speed_avg_print_x10 = 0;
            error_avg_print_x10 = 0;
            speed_min_print_x10 = 0;
            speed_max_print_x10 = 0;
        }

        /* Start a fresh 137 ms diagnostic window. */
        speed_diag_time_s = 0.0f;
        speed_diag_speed_integral = 0.0f;
        speed_diag_error_integral = 0.0f;
        speed_diag_min_rpm = 0.0f;
        speed_diag_max_rpm = 0.0f;
        speed_diag_valid = 0U;

        ADC_GetInjectedSnapshot(&u_raw, &v_raw, &w_raw, &seq);

        iu = Current_FromRaw_mA(u_raw, iu_zero_raw);
        iv = Current_FromRaw_mA(v_raw, iv_zero_raw);
        iw = Current_FromRaw_mA(w_raw, iw_zero_raw);

        dt = now - last_print_tick;
        dn = seq - last_print_seq;
        fs = (dt > 0U) ? (dn * 1000U / dt) : 0U;

        reject_now = current_reject_count;

        reject_delta = reject_now - last_print_reject;

        last_print_tick = now;
        last_print_seq = seq;
        last_print_reject = reject_now;

        /*
         * Snapshot control-state variables published by the 20 kHz ISR.
         * Printing uses integer mA/mV/permille so no printf-float support is
         * required from the embedded C library.
         */
        {
            uint32_t primask = __get_PRIMASK();
            float id_ref_A;
            float iq_ref_A;
            float id_A;
            float iq_A;
            float vd_V;
            float vq_V;
            float position_now;
            float position_target_now;
            float position_error_now;
            float speed_target_now;
            float speed_ref_now;
            float speed_now;
            float speed_inst_now;
            float speed_error_now;
            float speed_p_now;
            float speed_i_now;
            uint32_t speed_glitch_now;
            uint32_t int_bleed_now;
            uint32_t overspeed_bleed_now;
            uint32_t position_deadband_now;
            uint32_t dir_reset_now;
            float du;
            float dv;
            float dw;

            __disable_irq();

            enc_raw_now = encoder_raw;
            enc_valid_now = encoder_valid;
            enc_err_now = encoder_error_count;

            id_ref_A = foc_id_ref_A;
            iq_ref_A = foc_iq_ref_A;
            id_A = foc_id_A;
            iq_A = foc_iq_A;
            vd_V = foc_vd_V;
            vq_V = foc_vq_V;
            position_now = encoder_position_deg;
            position_target_now = position_target_deg;
            position_error_now = position_error_deg;
            speed_target_now = speed_target_rpm;
            speed_ref_now = speed_ref_rpm;
            speed_now = encoder_speed_rpm;
            speed_inst_now = encoder_rpm_instant;
            speed_error_now = speed_error_rpm;
            speed_p_now = speed_p_term_A;
            speed_i_now = speed_integrator_A;
            speed_glitch_now = encoder_speed_glitch_count;
            int_bleed_now = (uint32_t)speed_integrator_bleed_active;
            overspeed_bleed_now = (uint32_t)speed_overspeed_bleed_active;
            position_deadband_now = (uint32_t)position_deadband_active;
            dir_reset_now = position_direction_reset_count;
            du = foc_duty_u;
            dv = foc_duty_v;
            dw = foc_duty_w;

            if (primask == 0U)
                __enable_irq();

            if (enc_valid_now != 0U)
            {
                float theta = encoder_theta_e;
                enc_angle_deg =
                    (uint32_t)(theta * 180.0f / PI_F);
            }

            id_ref_mA = (int32_t)(id_ref_A * 1000.0f);
            (void)id_ref_mA;
            iq_ref_mA = (int32_t)(iq_ref_A * 1000.0f);
            id_mA = (int32_t)(id_A * 1000.0f);
            iq_mA = (int32_t)(iq_A * 1000.0f);
            vd_mV = (int32_t)(vd_V * 1000.0f);
            vq_mV = (int32_t)(vq_V * 1000.0f);
            position_now_print_x100 =
                (int32_t)(position_now * 100.0f);
            position_target_print_x100 =
                (int32_t)(position_target_now * 100.0f);
            position_error_print_x100 =
                (int32_t)(position_error_now * 100.0f);

            stall_print_ms = (uint32_t)(stall_timer_s * 1000.0f);
            int_bleed_print = int_bleed_now;
            overspeed_bleed_print = overspeed_bleed_now;
            position_deadband_print = position_deadband_now;
            dir_reset_print = dir_reset_now;
            speed_target_print_rpm = (int32_t)speed_target_now;
            speed_ref_print_rpm = (int32_t)speed_ref_now;
            speed_meas_print_rpm = (int32_t)speed_now;
            speed_inst_print_rpm = (int32_t)speed_inst_now;
            speed_error_print_rpm = (int32_t)speed_error_now;
            speed_p_print_mA = (int32_t)(speed_p_now * 1000.0f);
            speed_i_print_mA = (int32_t)(speed_i_now * 1000.0f);
            speed_glitch_print = speed_glitch_now;

            duty_u_permille = (uint32_t)(ClampFloat(du, 0.0f, 1.0f) * 1000.0f);
            duty_v_permille = (uint32_t)(ClampFloat(dv, 0.0f, 1.0f) * 1000.0f);
            duty_w_permille = (uint32_t)(ClampFloat(dw, 0.0f, 1.0f) * 1000.0f);
        }

        FormatSignedX100(pos_buf, sizeof(pos_buf), position_now_print_x100);
        FormatSignedX100(ptgt_buf, sizeof(ptgt_buf), position_target_print_x100);
        FormatSignedX100(perr_buf, sizeof(perr_buf), position_error_print_x100);

        snprintf(msg, sizeof(msg),
                 "T=%5lums STG=%lu | FS=%5lu RJ=%2lu | "
                 "POS=%s PTGT=%s PERR=%s deg | "
                 "SPD=%4ld VCMD=%3ld REF=%3ld SERR=%4ld STALL=%4lums | "
                 "AVG=%ld.%01ld MIN=%ld.%01ld MAX=%ld.%01ld ERR_AVG=%ld.%01ld rpm | "
                 "P=%4ld I=%4ld IqRef=%4ld mA PDB=%lu ARM=%lu SET=%lums AHLD=%lu HQ=%4ldmA IBLD=%lu OBLD=%lu RCLR=%lu | "
                 "INST=%5ld GL=%lu | "
                 "Id=%5ld Iq=%5ld | Vd=%4ld Vq=%4ld | "
                 "ENC=%3ludeg EV=%u EE=%lu | RJTOT=%lu\r\n",
                 (unsigned long)profile_time_ms,
                 (unsigned long)profile_stage_print,
                 (unsigned long)fs,
                 (unsigned long)reject_delta,
                 pos_buf,
                 ptgt_buf,
                 perr_buf,
                 (long)speed_meas_print_rpm,
                 (long)speed_target_print_rpm,
                 (long)speed_ref_print_rpm,
                 (long)speed_error_print_rpm,
                 (unsigned long)stall_print_ms,
                 (long)(speed_avg_print_x10 / 10),
                 (long)labs(speed_avg_print_x10 % 10),
                 (long)(speed_min_print_x10 / 10),
                 (long)labs(speed_min_print_x10 % 10),
                 (long)(speed_max_print_x10 / 10),
                 (long)labs(speed_max_print_x10 % 10),
                 (long)(error_avg_print_x10 / 10),
                 (long)labs(error_avg_print_x10 % 10),
                 (long)speed_p_print_mA,
                 (long)speed_i_print_mA,
                 (long)iq_ref_mA,
                 (unsigned long)position_deadband_print,
                 (unsigned long)stage_arm_print,
                 (unsigned long)stage_settle_print_ms,
                 (unsigned long)active_hold_print,
                 (long)active_hold_iq_print_mA,
                 (unsigned long)int_bleed_print,
                 (unsigned long)overspeed_bleed_print,
                 (unsigned long)dir_reset_print,
                 (long)speed_inst_print_rpm,
                 (unsigned long)speed_glitch_print,
                 (long)id_mA,
                 (long)iq_mA,
                 (long)vd_mV,
                 (long)vq_mV,
                 (unsigned long)enc_angle_deg,
                 (unsigned int)enc_valid_now,
                 (unsigned long)enc_err_now,
                 (unsigned long)reject_now);

        UART_SendString(msg);
    }

  }  /* close while (1) */
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1_BOOST);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV4;
  RCC_OscInitStruct.PLL.PLLN = 85;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief ADC1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC1_Init(void)
{

  /* USER CODE BEGIN ADC1_Init 0 */

  /* USER CODE END ADC1_Init 0 */

  ADC_MultiModeTypeDef multimode = {0};
  ADC_ChannelConfTypeDef sConfig = {0};
  ADC_InjectionConfTypeDef sConfigInjected = {0};

  /* USER CODE BEGIN ADC1_Init 1 */

  /* USER CODE END ADC1_Init 1 */

  /** Common config
  */
  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.GainCompensation = 0;
  hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SEQ_CONV;
  hadc1.Init.LowPowerAutoWait = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.NbrOfConversion = 1;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc1.Init.DMAContinuousRequests = DISABLE;
  hadc1.Init.Overrun = ADC_OVR_DATA_PRESERVED;
  hadc1.Init.OversamplingMode = DISABLE;
  if (HAL_ADC_Init(&hadc1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure the ADC multi-mode
  */
  multimode.Mode = ADC_DUALMODE_INJECSIMULT;
  multimode.DMAAccessMode = ADC_DMAACCESSMODE_DISABLED;
  multimode.TwoSamplingDelay = ADC_TWOSAMPLINGDELAY_1CYCLE;
  if (HAL_ADCEx_MultiModeConfigChannel(&hadc1, &multimode) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Regular Channel
  */
  sConfig.Channel = ADC_CHANNEL_1;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_47CYCLES_5;
  sConfig.SingleDiff = ADC_SINGLE_ENDED;
  sConfig.OffsetNumber = ADC_OFFSET_NONE;
  sConfig.Offset = 0;
  if (HAL_ADC_ConfigChannel(&hadc1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Injected Channel
  */
  sConfigInjected.InjectedChannel = ADC_CHANNEL_1;
  sConfigInjected.InjectedRank = ADC_INJECTED_RANK_1;
  sConfigInjected.InjectedSamplingTime = ADC_SAMPLETIME_12CYCLES_5;
  sConfigInjected.InjectedSingleDiff = ADC_SINGLE_ENDED;
  sConfigInjected.InjectedOffsetNumber = ADC_OFFSET_NONE;
  sConfigInjected.InjectedOffset = 0;
  sConfigInjected.InjectedNbrOfConversion = 1;
  sConfigInjected.InjectedDiscontinuousConvMode = DISABLE;
  sConfigInjected.AutoInjectedConv = DISABLE;
  sConfigInjected.QueueInjectedContext = DISABLE;
  sConfigInjected.ExternalTrigInjecConv = ADC_EXTERNALTRIGINJEC_T1_TRGO2;
  sConfigInjected.ExternalTrigInjecConvEdge = ADC_EXTERNALTRIGINJECCONV_EDGE_RISING;
  sConfigInjected.InjecOversamplingMode = DISABLE;
  if (HAL_ADCEx_InjectedConfigChannel(&hadc1, &sConfigInjected) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC1_Init 2 */

  /* USER CODE END ADC1_Init 2 */

}

/**
  * @brief ADC2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_ADC2_Init(void)
{

  /* USER CODE BEGIN ADC2_Init 0 */

  /* USER CODE END ADC2_Init 0 */

  ADC_ChannelConfTypeDef sConfig = {0};
  ADC_InjectionConfTypeDef sConfigInjected = {0};

  /* USER CODE BEGIN ADC2_Init 1 */

  /* USER CODE END ADC2_Init 1 */

  /** Common config
  */
  hadc2.Instance = ADC2;
  hadc2.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
  hadc2.Init.Resolution = ADC_RESOLUTION_12B;
  hadc2.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc2.Init.GainCompensation = 0;
  hadc2.Init.ScanConvMode = ADC_SCAN_DISABLE;
  hadc2.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  hadc2.Init.LowPowerAutoWait = DISABLE;
  hadc2.Init.ContinuousConvMode = DISABLE;
  hadc2.Init.NbrOfConversion = 1;
  hadc2.Init.DiscontinuousConvMode = DISABLE;
  hadc2.Init.DMAContinuousRequests = DISABLE;
  hadc2.Init.Overrun = ADC_OVR_DATA_PRESERVED;
  hadc2.Init.OversamplingMode = DISABLE;
  if (HAL_ADC_Init(&hadc2) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Regular Channel
  */
  sConfig.Channel = ADC_CHANNEL_2;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_2CYCLES_5;
  sConfig.SingleDiff = ADC_SINGLE_ENDED;
  sConfig.OffsetNumber = ADC_OFFSET_NONE;
  sConfig.Offset = 0;
  if (HAL_ADC_ConfigChannel(&hadc2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Injected Channel
  */
  sConfigInjected.InjectedChannel = ADC_CHANNEL_2;
  sConfigInjected.InjectedRank = ADC_INJECTED_RANK_1;
  sConfigInjected.InjectedSamplingTime = ADC_SAMPLETIME_12CYCLES_5;
  sConfigInjected.InjectedSingleDiff = ADC_SINGLE_ENDED;
  sConfigInjected.InjectedOffsetNumber = ADC_OFFSET_NONE;
  sConfigInjected.InjectedOffset = 0;
  sConfigInjected.InjectedNbrOfConversion = 1;
  sConfigInjected.InjectedDiscontinuousConvMode = DISABLE;
  sConfigInjected.AutoInjectedConv = DISABLE;
  sConfigInjected.QueueInjectedContext = DISABLE;
  sConfigInjected.InjecOversamplingMode = DISABLE;
  if (HAL_ADCEx_InjectedConfigChannel(&hadc2, &sConfigInjected) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ADC2_Init 2 */

  /* USER CODE END ADC2_Init 2 */

}

/**
  * @brief LPUART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_LPUART1_UART_Init(void)
{

  /* USER CODE BEGIN LPUART1_Init 0 */

  /* USER CODE END LPUART1_Init 0 */

  /* USER CODE BEGIN LPUART1_Init 1 */

  /* USER CODE END LPUART1_Init 1 */
  hlpuart1.Instance = LPUART1;
  hlpuart1.Init.BaudRate = 115200;
  hlpuart1.Init.WordLength = UART_WORDLENGTH_8B;
  hlpuart1.Init.StopBits = UART_STOPBITS_1;
  hlpuart1.Init.Parity = UART_PARITY_NONE;
  hlpuart1.Init.Mode = UART_MODE_TX_RX;
  hlpuart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  hlpuart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  hlpuart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  hlpuart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&hlpuart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&hlpuart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN LPUART1_Init 2 */

  /* USER CODE END LPUART1_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_16BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_32;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 7;
  hspi1.Init.CRCLength = SPI_CRC_LENGTH_DATASIZE;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};
  TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 0;
  htim1.Init.CounterMode = TIM_COUNTERMODE_CENTERALIGNED1;
  htim1.Init.Period = 4249;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_OC4REF;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 2125;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
  sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM2;
  sConfigOC.Pulse = 3500;
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  sBreakDeadTimeConfig.OffStateRunMode = TIM_OSSR_DISABLE;
  sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
  sBreakDeadTimeConfig.LockLevel = TIM_LOCKLEVEL_OFF;
  sBreakDeadTimeConfig.DeadTime = 85;
  sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
  sBreakDeadTimeConfig.BreakPolarity = TIM_BREAKPOLARITY_HIGH;
  sBreakDeadTimeConfig.BreakFilter = 0;
  sBreakDeadTimeConfig.BreakAFMode = TIM_BREAK_AFMODE_INPUT;
  sBreakDeadTimeConfig.Break2State = TIM_BREAK2_DISABLE;
  sBreakDeadTimeConfig.Break2Polarity = TIM_BREAK2POLARITY_HIGH;
  sBreakDeadTimeConfig.Break2Filter = 0;
  sBreakDeadTimeConfig.Break2AFMode = TIM_BREAK_AFMODE_INPUT;
  sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
  if (HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */
  HAL_TIM_MspPostInit(&htim1);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(AS5047_CS_GPIO_Port, AS5047_CS_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : AS5047_CS_Pin */
  GPIO_InitStruct.Pin = AS5047_CS_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(AS5047_CS_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : DRIVER_SD_Pin */
  GPIO_InitStruct.Pin = DRIVER_SD_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(DRIVER_SD_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
/* Best-effort safe shutdown before halting. */
HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
__disable_irq();
while (1)
{
}
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */

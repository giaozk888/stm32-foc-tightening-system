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
#include "foc_fast_path_profile.h"
#if defined(FOC_SPEED_STARTUP_BRAKE)
#include "speed_startup_brake.h"
#endif
#if defined(FOC_SPEED_BUMPLESS)
#include "speed_bumpless.h"
#if defined(FOC_SPEED_BRAKE_TRACK)
#include "speed_brake_track.h"
static SpeedBrakeTrack speed_brake_track;
#endif
#endif

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#define FOC_TIMEOUT_DIAGNOSTICS 1
/* UART_LAYER_1B: TX DMA ring + RX DMA circular + ProtocolTask */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include <ctype.h>
#include <stddef.h>
#include <stdarg.h>
#include "as5047p_protocol.h"
#include "as5047p_transaction.h"
#include "foc_adc_clock_stm32.h"
#include "foc_current_median.h"
#if defined(FOC_ORIGINAL_CLOSED_LOOP_UPDATED)
#include "original_closed_loop_profile.h"
#endif
#if defined(FOC_FAST_MATH)
#include "foc_fast_trig.h"
#include "foc_irq_load.h"
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_closed_loop.h"
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
#include "foc_feedback_binding_stm32.h"
#endif
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow.h"
static FocOcShadow foc_oc_shadow;
#if defined(FOC_FILTERED_OBSERVE_ONLY)
static FocOcShadow foc_filtered_oc_shadow;
#endif
static uint32_t foc_trend_pairs, foc_trend_changed, foc_trend_u_changed, foc_trend_v_changed;
#endif
#if defined(FOC_RAW_OBSERVE_ONLY) || defined(FOC_FILTERED_OBSERVE_ONLY)
#include "foc_raw_observe_policy.h"
#endif
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
#include "adc_control_pins_low.h"
#endif
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
#include "adc_dma_diag.h"
#endif
#if defined(FOC_ADC_WINDOW)
#include "foc_adc_timing_stm32.h"
#include "foc_adc_statistics_task.h"
#endif
#if defined(AS5047P_SPI_DMA)
#include "as5047p_dma_stm32.h"
static AsDmaCursor encoder_dma_cursor;
#endif
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "uart_async.h"
#include "protocol_tx_format.h"
#include "protocol_tx_buffer.h"
#include "uart_rx_dma.h"
#include "uart_line_parser.h"
#ifndef UART_LOG_BAUD
#define UART_LOG_BAUD 115200U
#endif
#if UART_LOG_BAUD > 115200U
#define UART_ROUTER_POLL_MS 1U
#else
#define UART_ROUTER_POLL_MS 5U
#endif
#include "modbus_probe.h"
#include "esp_link.h"
#include "esp_ping.h"
#if defined(ESP_NETWORK_OBSERVER)
#include "network_v1.h"
#endif
#include "router.h"
#include "router_uart_tx.h"
#include "pw_kvs_params.h"
#if defined(UART_FIRMWARE_TRANSFER)
#include "uart_firmware_transfer.h"
#endif
#include "tighten_params_storage.h"
#if defined(TIGHTEN_SPEED_X2_OFFLINE) && \
    (!defined(FOC_ISOLATED_CONCURRENCY) || !defined(TIGHTEN_SYNTHETIC_BENCH))
#error Double-speed recipe is restricted to the output-locked synthetic profile
#endif
#include "pw_allocator_port.h"
#include "pw_log_backend.h"
#include "pw_log_router_bridge.h"
#if defined(CAN_RPC_READ_ONLY)
#include "pw_can_rpc.h"
#include "rpc_readonly.h"
#endif
#if defined(CAN_LINK_PROBE_ONLY)
#include "can_link_probe.h"
#endif
#if defined(CAN_STATUS_TELEMETRY)
#include "can_status_tx.h"
#if defined(CAN_LOG_STREAM)
#include "pw_can_log.h"
#endif
#endif
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
    PROTO_ERR_NO_VALID_PARAMS = 108,
    PROTO_ERR_FW_STATE        = 109,
    PROTO_ERR_FW_CRC          = 110,
    PROTO_ERR_FW_RANGE        = 111,
    PROTO_ERR_FW_SEQUENCE     = 112
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
 * refactor_backups/20261002_cpp_params/main_b.c. Runtime motion belongs
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
#define TIGHTEN_RUNDOWN_RPM                   ((float)TIGHTEN_RUNDOWN_DEFAULT_RPM)
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

/* One-shot analog wiring diagnostic, sampled before injected FOC starts. */
static volatile uint16_t analog_boot_pc4_raw = 0U;
static volatile uint16_t analog_boot_pc5_raw = 0U;
static volatile uint8_t analog_boot_valid = 0U;

/* Factory-VREFINT-based VDDA estimate, taken before ADC1 injected FOC starts. */
static volatile uint16_t analog_vref_boot_raw = 0U;
static volatile uint16_t analog_vdda_boot_mv = 0U;
static volatile uint8_t analog_vdda_boot_valid = 0U;

/* IDLE-only, low-rate regular ADC2 diagnostic while injected FOC is armed. */
static volatile uint16_t analog_live_pc4_raw = 0U;
static volatile uint16_t analog_live_pc5_raw = 0U;
static volatile uint32_t analog_live_last_tick_ms = 0U;
static volatile uint32_t analog_live_sample_count = 0U;
static volatile uint32_t analog_live_error_count = 0U;
static volatile uint8_t analog_live_valid = 0U;
/* Raw PC4 conversions before/after a same-channel repeat, SAFE mode only. */
typedef struct
{
    uint16_t last_first;
    uint16_t last_second;
    uint16_t peak_first;
    uint16_t peak_first_second;
    uint16_t peak_second;
    uint16_t peak_second_first;
    uint32_t count;
    uint32_t errors;
} AnalogPairDiag_t;
static volatile AnalogPairDiag_t analog_pair_diag;
/* Three consecutive PC4 conversions; median is experimental, not protection. */
typedef struct
{
    uint16_t last_first;
    uint16_t last_second;
    uint16_t last_third;
    uint16_t last_median;
    uint16_t peak_raw_value;
    uint16_t peak_raw_first;
    uint16_t peak_raw_second;
    uint16_t peak_raw_third;
    uint16_t peak_median_value;
    uint16_t peak_median_first;
    uint16_t peak_median_second;
    uint16_t peak_median_third;
    uint16_t max_spread;
    uint32_t count;
    uint32_t errors;
    uint32_t disagree_count;
    uint32_t last_tick_ms;
} AnalogTripleDiag_t;
static volatile AnalogTripleDiag_t analog_triple_diag;
static volatile AnalogTripleDiag_t analog_pc5_triple_diag;
/* One-way, voltage-diagnostics-only shutdown until the next MCU reset. */
static volatile uint8_t analog_safe_latched = 0U;

static volatile uint16_t iu_inj_raw = 0U;
static volatile uint16_t iv_inj_raw = 0U;
static volatile uint16_t iw_inj_raw = 0U;
static volatile uint32_t injected_seq_count = 0U;
static volatile uint8_t adc_fault = 0U;

/* PWM-ON dynamic zero calibration state */
static volatile uint8_t run_zero_cal_active = 0U;
static volatile uint8_t run_zero_cal_done = 0U;
static FocCurrentMedian run_zero_median; /* Sole writer: ADC1 ISR while active. */

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
#if defined(FOC_CURRENT_SPIKE_ONLY)
static FocCurrentMedian current_spike_filter;
#if defined(FOC_CURRENT_TREND4)
static FocTrend4Angle current_trend4_angle;
#endif
#endif

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
/* C ABI recipe layout shared by both slots; implementation is C++17. */

#define PARAM_FLASH_ADDRESS       (0x0807F800UL)

#define APP_A_ADDRESS          (0x08008000UL)
#define APP_A_END              (0x08040000UL)
#define APP_B_ADDRESS          (0x08040000UL)
#define APP_B_END              (0x08078000UL)

/*
 * Metadata V3: two independent erase pages.
 *
 * Copy1 / Page125 : 0x0807E800..0x0807EFFF
 * Copy0 / Page126 : 0x0807F000..0x0807F7FF
 * Parameters      : 0x0807F800..0x0807FFFF (unchanged)
 *
 * Copy0 deliberately keeps the historical V1/V2 address for staged
 * migration compatibility.
 */
#define BOOT_META_COPY0_ADDRESS (0x0807F000UL)
#define BOOT_META_COPY0_PAGE    (126U)
#define BOOT_META_COPY1_ADDRESS (0x0807E800UL)
#define BOOT_META_COPY1_PAGE    (125U)
#define BOOT_META_BANK          FLASH_BANK_2

#define BOOT_META_ADDRESS       BOOT_META_COPY0_ADDRESS

#define BOOT_META_MAGIC         (0x424F4F54UL)  /* "BOOT" */
#define BOOT_META_VERSION_V1    (1UL)
#define BOOT_META_VERSION_V2    (2UL)
#define BOOT_META_VERSION_V3    (3UL)

#define BOOT_SLOT_NONE         (0UL)
#define BOOT_SLOT_A            (1UL)
#define BOOT_SLOT_B            (2UL)

#define APP_THIS_SLOT          (BOOT_SLOT_B)
#define APP_THIS_ADDRESS       (APP_B_ADDRESS)
#define APP_TARGET_SLOT        (BOOT_SLOT_A)
#define APP_TARGET_ADDRESS     (APP_A_ADDRESS)
#define APP_TARGET_END         (APP_A_END)
#define APP_TARGET_BANK        FLASH_BANK_1
#define APP_TARGET_FIRST_PAGE  (16U)

#define FW_FLASH_PAGE_SIZE     (0x800UL)
#define FW_SLOT_SIZE           (0x38000UL)
#define FW_DATA_MAX_BYTES      (32U)
#define FW_TRIAL_ATTEMPTS      (2UL)

/*
 * Reserved SRAM mailbox. Linker RAM LENGTH must end at 0x2001FFC0 so the
 * startup stack/.bss never overwrite 0x2001FFC0..0x2001FFFF.
 */
#define BOOT_MAILBOX_ADDRESS        (0x2001FFC0UL)
#define BOOT_MAILBOX_RESERVED_BYTES (64UL)
#define BOOT_MAILBOX_MAGIC          (0x584F424DUL) /* "MBOX" */
#define BOOT_MAILBOX_VERSION        (1UL)

#define BOOT_MAILBOX_CMD_NONE               (0UL)
#define BOOT_MAILBOX_CMD_CONFIRM_CURRENT    (1UL)
#define BOOT_MAILBOX_CMD_START_TRIAL        (2UL)
#define BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT (3UL)

/*
 * Automatic trial-firmware health gate.
 *
 * A newly downloaded slot is NOT confirmed immediately. It must first keep
 * the core control/communication chain healthy for a continuous 5-second
 * window. If that never happens, the APP deliberately resets so Bootloader
 * V2 can consume the remaining trial attempt and eventually roll back.
 */
#define BOOT_HEALTH_CHECK_MS              (500U)
#define BOOT_HEALTH_STABLE_REQUIRED_MS    (5000U)
#define BOOT_HEALTH_FAIL_RESET_MS         (12000U)
#define BOOT_HEALTH_MIN_ADC_DELTA          (9000U)
#define BOOT_HEALTH_MIN_FOC_DELTA          (9000U)

/*
 * Lab-only fault injection.
 * 0 = normal automatic confirmation.
 * 1 = deliberately fail every health sample so rollback can be tested.
 *
 * Keep this 0 in the normal APP A/B builds.
 */
/* Acceptance-only fault injection; normal images must leave this at zero. */
#ifndef BOOT_HEALTH_FORCE_FAIL_TEST
#define BOOT_HEALTH_FORCE_FAIL_TEST        (0U)
#endif

/* Stage 7.1: only software-visible preflight conditions. */
#define PREFLIGHT_FAIL_ADC_FAULT           (1UL << 0)
#define PREFLIGHT_FAIL_FOC_FAULT           (1UL << 1)
#define PREFLIGHT_FAIL_ENCODER             (1UL << 2)
#define PREFLIGHT_FAIL_FOC_DISABLED        (1UL << 3)
#define PREFLIGHT_FAIL_ZERO_CAL            (1UL << 4)
#define PREFLIGHT_FAIL_UART                (1UL << 5)
#define PREFLIGHT_FAIL_MODE                (1UL << 6)
#define PREFLIGHT_FAIL_SPEED               (1UL << 7)
#define PREFLIGHT_FAIL_FW_UPDATE           (1UL << 8)
#define PREFLIGHT_FAIL_TRIAL               (1UL << 9)
#define PREFLIGHT_FAIL_ADC_STALE           (1UL << 10)
#define PREFLIGHT_FAIL_FOC_STALE           (1UL << 11)
#define PREFLIGHT_CHAIN_MAX_STALE_MS       (50U)
#define PREFLIGHT_FAIL_BOOT_LOCK           (1UL << 12)
#define FOC_FAULT_ADC_CHAIN_STALE           (5U)
#define FOC_FAULT_CONTROL_CHAIN_STALE       (6U)
#define FOC_FAULT_STARTUP_ZERO_CAL          (7U)
#define FOC_FAULT_ADC_WINDOW                (8U)

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t active_slot;
    uint32_t crc32;
} BootMetaV1_t;

typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;

    uint32_t confirmed_slot;
    uint32_t pending_slot;
    uint32_t attempts_left;
    uint32_t generation;

    uint32_t app_a_size;
    uint32_t app_a_crc32;
    uint32_t app_b_size;
    uint32_t app_b_crc32;

    uint32_t flags;
    uint32_t crc32;
} BootMetaV2_t;

/*
 * V3 keeps exactly the same payload fields as V2.
 * The upgrade is the storage protocol: dual-page + generation + CRC32.
 */
typedef BootMetaV2_t BootMetaV3_t;

/*
 * V4 APP -> Bootloader command mailbox.
 * The top 64 bytes of SRAM are excluded from the linker RAM region in both
 * APP and bootloader projects, so this request survives NVIC_SystemReset().
 */
typedef struct __attribute__((aligned(8)))
{
    uint32_t magic;
    uint32_t version;
    uint32_t command;
    uint32_t requester_slot;
    uint32_t target_slot;
    uint32_t image_size;
    uint32_t image_crc32;
    uint32_t crc32;
} BootMailbox_t;

_Static_assert(sizeof(BootMailbox_t) <= BOOT_MAILBOX_RESERVED_BYTES,
               "BootMailbox_t exceeds reserved SRAM mailbox");

typedef struct
{
    uint8_t active;
    uint32_t target_slot;
    uint32_t target_address;
    uint32_t image_size;
    uint32_t expected_crc32;
    uint32_t bytes_received;
} FwUpdateContext_t;

static TightenParamsState_t recipe_state = TIGHTEN_PARAMS_STATE_INITIALIZER;

static FwUpdateContext_t fw_update =
{
    .active = 0U,
    .target_slot = APP_TARGET_SLOT,
    .target_address = APP_TARGET_ADDRESS,
    .image_size = 0U,
    .expected_crc32 = 0U,
    .bytes_received = 0U
};


/*
 * GDB-visible IAP diagnostics. These are deliberately non-static.
 * They let us diagnose FW BEGIN even when UART itself is the failing path.
 */
volatile uint32_t g_fw_diag_stage = 0U;
volatile uint32_t g_fw_diag_hal_status = 0U;
volatile uint32_t g_fw_diag_lock_status = 0U;
volatile uint32_t g_fw_diag_page_error = 0xFFFFFFFFUL;
volatile uint32_t g_fw_diag_flash_error = 0U;
volatile uint32_t g_fw_diag_flash_sr = 0U;
volatile uint32_t g_fw_diag_flash_cr = 0U;
volatile uint32_t g_fw_diag_erase_bank = 0U;
volatile uint32_t g_fw_diag_erase_page = 0U;
volatile uint32_t g_fw_diag_erase_pages = 0U;
volatile uint32_t g_fw_diag_ack_queued = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_state = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_remaining = 0U;
volatile uint32_t g_fw_diag_uart_rx_state = 0U;
volatile uint32_t g_fw_diag_uart_rx_dma_ccr = 0U;
volatile uint32_t g_fw_diag_uart_cr3 = 0U;
volatile uint32_t g_fw_diag_uart_rx_errors = 0U;
volatile uint32_t g_fw_diag_uart_rx_last_error = 0U;
volatile uint32_t g_fw_diag_uart_rx_restarts = 0U;
volatile uint32_t g_fw_diag_uart_rx_restart_failures = 0U;
volatile uint32_t g_fw_diag_uart_tx_queued = 0U;
volatile uint32_t g_fw_diag_uart_tx_dropped = 0U;
volatile uint32_t g_fw_diag_uart_tx_dma_errors = 0U;


/* Boot-health state is exposed through FW STATUS for trial diagnostics. */
static volatile uint8_t boot_health_trial_active = 0U;
static volatile uint8_t boot_health_last_sample_ok = 0U;
static volatile uint32_t boot_health_stable_ms = 0U;
static volatile uint32_t boot_health_elapsed_ms = 0U;

/* Stage 8.3 diagnostics only. DWT includes interrupt/preemption time. */
static volatile uint8_t encoder_diag_dwt_ready = 0U;
static volatile uint32_t encoder_diag_reads = 0U;
static volatile uint32_t encoder_diag_failures = 0U;
static volatile uint32_t encoder_diag_over_1ms = 0U;
static volatile uint32_t encoder_diag_last_cycles = 0U;
static volatile uint32_t encoder_diag_max_cycles = 0U;
static volatile uint32_t motor_stack_min_words = UINT32_MAX;
static volatile uint32_t motor_stack_samples = 0U;
static TaskHandle_t motor_control_task_handle = NULL;


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

/*
 * Router Stage 4.1: preserve the origin of a START request after
 * ProtocolTask has finished handling the packet.
 *
 * The short-lived mailbox fields below belong to the START command that is
 * waiting for TighteningTask.  TighteningTask copies them into the persistent
 * session fields only when the cycle actually starts.
 *
 * routed = 0 : legacy/local UART START
 * routed = 1 : START arrived inside a routed ROUTER_PKT_PROTOCOL packet
 */
static volatile uint8_t tightening_start_request_routed = 0U;
static volatile uint16_t tightening_start_request_source_node = 0U;

/*
 * Persistent tightening-session owner.  These symbols are intentionally
 * global (not static) so they are easy to inspect with GDB while learning
 * Stage 4.1.
 *
 * active          : one tightening cycle currently owns this session
 * routed          : the START came from another Router node
 * owner_node      : source node that issued START (0 for local/legacy)
 * request_id      : Protocol V2 request ID of that START
 *
 * On cycle completion only active is cleared.  The remaining fields keep the
 * last owner/request for post-mortem inspection; the next successful START
 * overwrites them.
 */
volatile uint8_t g_tightening_session_active = 0U;
volatile uint8_t g_tightening_session_routed = 0U;
volatile uint16_t g_tightening_session_owner_node = 0U;
volatile uint32_t g_tightening_session_request_id = 0U;

/*
 * Router Stage 4.3: reliable routed asynchronous events.
 *
 * Stage 4.2 already moved application events out of TighteningTask and into a
 * ProtocolTask-owned queue. Stage 4.3 adds an application-level EID, ACK and
 * bounded retransmission on top of the existing Router route table.
 *
 * Router packet type 4 = reliable asynchronous EVENT
 * Router packet type 5 = EVENT ACK
 *
 * Router SEQ is transport-level and changes on every retry. EID is the stable
 * business-event identifier and stays unchanged across retransmissions.
 */
#define PROTOCOL_ASYNC_EVENT_QUEUE_DEPTH          (4U)
#define PROTOCOL_ROUTER_TYPE_EVENT                (4U)
#define PROTOCOL_ROUTER_TYPE_EVENT_ACK            (5U)
#define PROTOCOL_RELIABLE_EVENT_SLOTS             (4U)
#define PROTOCOL_RELIABLE_EVENT_RETRY_MS          (500U)
#define PROTOCOL_RELIABLE_EVENT_MAX_ATTEMPTS      (5U)
#define PROTOCOL_RELIABLE_RX_CACHE_SIZE           (8U)
#define PROTOCOL_RELIABLE_RX_CACHE_MS             (5000U)

typedef struct
{
    uint8_t routed;
    uint16_t dst_node;
    char payload[ROUTER_MAX_PAYLOAD + 1U];
} ProtocolAsyncEvent_t;

typedef struct
{
    uint8_t in_use;
    uint8_t attempts;
    uint16_t dst_node;
    uint32_t eid;
    TickType_t next_retry_tick;
    char payload[ROUTER_MAX_PAYLOAD + 1U];
} ProtocolReliableEvent_t;

typedef struct
{
    uint8_t valid;
    uint16_t src_node;
    uint32_t eid;
    TickType_t expires_tick;
} ProtocolReliableRxCache_t;

static QueueHandle_t protocol_async_event_queue = NULL;

/* Stage 6.2: only ModbusTask touches USART3; ProtocolTask never waits for RTU. */
#define MODBUS_QUEUE_DEPTH  (4U)
typedef enum
{
    MODBUS_JOB_READ = 0,
    MODBUS_JOB_RELAY = 1
} ModbusJobType_t;

typedef struct
{
    uint32_t request_id;
    uint32_t baud;
    uint16_t address;
    uint16_t reply_dst;
    uint8_t routed;
    uint8_t type;
    uint8_t slave;
    uint8_t function;
    uint8_t even_parity;
    uint8_t relay;
    uint8_t on;
} ModbusJob_t;

typedef struct
{
    ModbusJob_t job;
    ModbusProbeReply_t reply;
    ModbusProbeResult_t result;
    uint8_t busy;
} ModbusCompletion_t;

static QueueHandle_t modbus_request_queue = NULL;
static QueueHandle_t modbus_completion_queue = NULL;
static volatile uint32_t modbus_submitted = 0U;
static volatile uint32_t modbus_completed = 0U;
static volatile uint32_t modbus_failed = 0U;
static volatile uint32_t modbus_queue_full = 0U;
static volatile uint32_t modbus_timeout = 0U;
static volatile uint32_t modbus_crc_error = 0U;
static ProtocolReliableEvent_t
    protocol_reliable_events[PROTOCOL_RELIABLE_EVENT_SLOTS];
static ProtocolReliableRxCache_t
    protocol_reliable_rx_cache[PROTOCOL_RELIABLE_RX_CACHE_SIZE];
static uint32_t protocol_reliable_next_eid = 1U;
static uint32_t protocol_reliable_rx_cache_cursor = 0U;

volatile uint32_t g_protocol_async_event_enqueued = 0U;
volatile uint32_t g_protocol_async_event_queue_drop = 0U;
volatile uint32_t g_protocol_async_event_route_ok = 0U;
volatile uint32_t g_protocol_async_event_route_fail = 0U;
volatile uint32_t g_protocol_async_event_local_ok = 0U;

/* Stage 4.3 diagnostics, intentionally global for GDB inspection. */
volatile uint32_t g_protocol_reliable_event_created = 0U;
volatile uint32_t g_protocol_reliable_event_sent = 0U;
volatile uint32_t g_protocol_reliable_event_retried = 0U;
volatile uint32_t g_protocol_reliable_event_acked = 0U;
volatile uint32_t g_protocol_reliable_event_giveup = 0U;
volatile uint32_t g_protocol_reliable_event_table_full = 0U;
volatile uint32_t g_protocol_reliable_event_no_route = 0U;
volatile uint32_t g_protocol_reliable_event_rx = 0U;
volatile uint32_t g_protocol_reliable_event_rx_duplicate = 0U;
volatile uint32_t g_protocol_reliable_event_ack_tx = 0U;
volatile uint32_t g_protocol_reliable_event_ack_tx_fail = 0U;
volatile uint32_t g_protocol_reliable_event_bad_event = 0U;
volatile uint32_t g_protocol_reliable_event_bad_ack = 0U;

static volatile TighteningOutcome_t tightening_last_outcome =
    TIGHTEN_OUTCOME_NONE;
#if defined(ESP_NETWORK_OBSERVER)
static volatile uint32_t g_network_run, g_network_seq, g_network_drop;
#endif

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

/* First overcurrent event only. Commit valid last; ProtocolTask never reads
 * partially written ISR data. This is diagnostic RAM, not a fault clear. */
typedef struct
{
    uint32_t tick_ms;
    uint32_t adc_seq;
    uint32_t vbus_age_ms;
    uint32_t current_valid_count;
    uint32_t current_reject_count;
    uint32_t current_reject_streak;
    uint32_t analog_sample_count;
    uint32_t analog_error_count;
    int32_t iu_mA;
    int32_t iv_mA;
    int32_t iw_mA;
    int32_t last_rejected_step;
    uint16_t accepted_u;
    uint16_t accepted_v;
    uint16_t physical_u;
    uint16_t physical_v;
    uint16_t zero_u;
    uint16_t zero_v;
    uint16_t vbus_raw;
    uint16_t median_u[3];
    uint16_t median_v[3];
    uint8_t filter_on;
    uint8_t median_count;
    uint8_t vbus_valid;
#if defined(FOC_CURRENT_TREND4)
    FocOcShadow shadow;
    int32_t raw_mA[3], filtered_mA[3];
    uint16_t trend_u[4], trend_v[4]; /* Chronological p,a,b,c; c is newest. */
    uint32_t trend_pairs, trend_changed, trend_u_changed, trend_v_changed;
    uint8_t trip_source, raw_mask, filtered_mask, spike_mask;
#endif
    uint8_t valid;
} FocCurrentTripSnapshot_t;
static volatile FocCurrentTripSnapshot_t foc_current_trip_snapshot;

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
static volatile TickType_t preflight_adc_progress_tick = 0U;
static volatile TickType_t preflight_foc_progress_tick = 0U;

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

#include "foc_timeout_diag.h"
#include "foc_encoder_timeout_diag.h"
static FocTimeoutReason encoder_timeout_reason;
static void FaultDiag_Monitor(void);
static void FaultDiag_Clear(void);

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

extern void PW_SmokeTest(void);
extern void PW_ThreadSmokeStart(void);
extern void PW_UnitTestsRun(void);
extern void PW_Rpc_Init(void);
extern void PW_Rpc_HandleCommand(uint32_t request_id, const char *args);
#if defined(ROUTER_READ_ONLY_RPC)
#include "pw_router_rpc.h"
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
#include "pw_router_transfer.h"
#endif
extern void PW_Transfer_HandleCommand(uint32_t request_id, const char *args);

/* RTOS task dependencies / forward declarations. */
static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw);
static void EncoderDiag_InitCycleCounter(void);
static float Encoder_ElectricalAngleRad(uint16_t raw);
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s);
static void PowerStage_Disable(void);
static void PowerStage_Enable(void);
#if defined(AS5047P_SPI_DMA)
/* IRQ priority 3: fixed writes only, no UART/HAL waits/FreeRTOS calls. */
static void EncoderDma_FaultFromISR(void)
{
    if (encoder_timeout_reason==FOC_TO_NONE) {
        uint32_t status=AS5047P_DmaFaultStatus();
        if (status==AS_DMA_TIMEOUT) encoder_timeout_reason=FOC_TO_ENCODER_TRANSACTION;
        else if (status==AS_DMA_CONTROL_STALE) encoder_timeout_reason=FOC_TO_ENCODER_CONTROL;
        else if (status==AS_DMA_SCHEDULE) encoder_timeout_reason=FOC_TO_ENCODER_SCHEDULE;
    }
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FB_ENCODER_INVALID);
#endif
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    FaultDiag_Capture(FOC_DIAG_MOTOR,2U,encoder_timeout_reason,
        tightening_test_elapsed_ms,0U);
    foc_enable = 0U;
    encoder_valid = 0U;
    foc_iq_ref_A = 0.0f;
    if (foc_fault == 0U) foc_fault_reason = 2U;
    foc_fault = 1U;
    __DSB();
}
#endif
static void PWM_SetDuty(float du, float dv, float dw);
static void PWM_StopAll(void);
static float ClampFloat(float x, float lo, float hi);
static void FormatSignedX100(char *buf, size_t n, int32_t x100);
static void MotorControlTask(void *argument);
static void TighteningTask(void *argument);
static void RouterTask(void *argument);
static void ProtocolTask(void *argument);
static void ModbusTask(void *argument);

static uint8_t Modbus_Enqueue(const ModbusJob_t *job);
static void Modbus_ServiceCompletions(uint32_t budget);
static void MonitorTask(void *argument);
static void BootHealthTask(void *argument);
static HAL_StatusTypeDef ADC_AnalogLiveSample(void);
static uint8_t Tightening_IsBusy(void);
static const char *TighteningOutcome_Name(TighteningOutcome_t outcome);
static uint8_t Router_Uart1Tx(const RouterPacket_t *packet);
static void Protocol_HandleLine(char *line);
#if defined(ZERO_RETEST_BOOT)
static uint8_t ZeroRetest_HandleCommand(uint32_t request_id, const char *cmd);
static void ZeroRetest_InjectedPair(void);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
void SwitchFeedback_EmergencyOff(uint32_t reason);
#endif
static uint8_t UART_SendReliableString(const char *str);
static uint8_t Protocol_SendString(const char *str);
static uint8_t Protocol_SendFormatted(char *fallback, size_t capacity,
    const char *format, ...) __attribute__((format(printf, 3, 4)));
static uint8_t UART_SendReliableFormatted(char *fallback, size_t capacity,
    const char *format, ...) __attribute__((format(printf, 3, 4)));
static void Protocol_SetReplyRoute(uint16_t dst_node);
static void Protocol_ClearReplyRoute(void);
static uint8_t Protocol_AsyncEventEnqueue(uint8_t routed, uint16_t dst_node, const char *payload);
static void Protocol_AsyncEventService(uint32_t budget);
static uint8_t Protocol_ReliableEventTransmit(ProtocolReliableEvent_t *slot, uint8_t is_retry);
static uint8_t Protocol_ReliableEventStart(uint16_t dst_node, const char *payload);
static void Protocol_ReliableEventService(uint32_t budget);
static uint8_t Protocol_ReliableEventAck(uint16_t src_node, uint32_t eid);
static uint32_t Protocol_ReliableEventPendingCount(void);
static uint8_t Protocol_ReliableEventParseEid(const char *text, const char *prefix, uint32_t *eid_out);
static uint8_t Protocol_ReliableEventRxSeen(uint16_t src_node, uint32_t eid);
static void Protocol_ReliableEventHandleEventPacket(const RouterPacket_t *packet);
static void Protocol_ReliableEventHandleAckPacket(const RouterPacket_t *packet);
static void Protocol_SendDeferredStartError(uint8_t routed, uint16_t dst_node, uint32_t request_id, const char *name);
static void Protocol_PrintStatus(uint32_t request_id);
static void TightenParams_RestoreDefaults(void);
static uint32_t TightenParams_Crc32(const uint8_t *data, size_t length);
static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void);
static uint8_t TightenParams_SaveToFlash(void);
static uint8_t BootMeta_ReadV1(BootMetaV1_t *out);
static uint8_t BootMeta_ReadV2Legacy(BootMetaV2_t *out);
static uint8_t BootMeta_ReadV3At(uint32_t address, BootMetaV3_t *out);
static uint8_t BootMeta_ReadV3(BootMetaV3_t *out);
static uint8_t BootMeta_SaveV3(const BootMetaV3_t *meta);
static uint8_t BootMeta_EnsureV3(BootMetaV3_t *out);

static uint8_t BootMailbox_WriteRequest(uint32_t command,
                                        uint32_t target_slot,
                                        uint32_t image_size,
                                        uint32_t image_crc32);
static uint8_t BootMailbox_RequestConfirmCurrent(void);
static uint8_t BootMailbox_RequestStartTrial(uint32_t target_slot,
                                             uint32_t image_size,
                                             uint32_t image_crc32);
static uint8_t BootMailbox_RequestSetConfirmedSlot(uint32_t target_slot);

static uint8_t BootHealth_IsCurrentTrial(void);
static uint8_t BootMeta_ConfirmCurrent(void);
static uint8_t BootMeta_SaveSlot(uint32_t slot);

static uint8_t Fw_HexNibble(char c, uint8_t *value);
static uint8_t Fw_ParseHexBytes(const char *text,
                                uint8_t *out,
                                uint32_t *out_len);
static uint8_t Fw_TargetVectorValid(void);
static uint8_t Fw_EraseTarget(uint32_t image_size);
static uint8_t Fw_ProgramData(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length);
static uint32_t Fw_TargetCrc32(uint32_t image_size);
static void Fw_EnterSafeState(void);
static void Fw_ResetContext(void);
static void Fw_DiagSnapshotComms(void);
static void Fw_SendStatus(uint32_t request_id);
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
/*
 * StartupTask runs at priority 5 while UART TX service runs lower.
 * Do not enter the async enqueue path until StartupTask has completed and
 * deleted itself; otherwise the first runtime write can deadlock/starve the
 * TX service before it ever gets CPU time.
 */
static volatile uint8_t g_uart_async_runtime_enable = 0U;

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
        (g_uart_async_runtime_enable != 0U))
    {
        /* A faulted DMA backend must not fall back to competing blocking TX. */
        (void)UART_Async_Write((const uint8_t *)str, len);
        return;
    }

    HAL_UART_Transmit(&hlpuart1,
                      (uint8_t *)str,
                      (uint16_t)len,
                      HAL_MAX_DELAY);
}

#define UART_PROTOCOL_TX_TIMEOUT_MS  250U
/* Private literal-only path. All callers below pass compile-time strings;
 * arbitrary/reusable caller buffers still use the copying compatibility API. */
static void UART_SendLiteral(const char *literal)
{
    if ((g_rtos_started != 0U) && (g_uart_async_runtime_enable != 0U)) {
        (void)UART_Async_WriteStatic((const uint8_t *)literal, strlen(literal));
        return;
    }
    UART_SendString(literal); /* preserve early boot's synchronous lifetime */
}

/* Generate directly into final DMA storage at runtime. The existing caller
 * array is only a pre-async boot fallback; never copied into TX at runtime. */
static void UART_SendFormatted(char *boot_buffer, size_t capacity, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    if ((g_rtos_started != 0U) && (g_uart_async_runtime_enable != 0U)) {
        (void)UART_Async_VPrintf(capacity, 0U, format, args);
    } else {
        (void)vsnprintf(boot_buffer, capacity, format, args);
        UART_SendString(boot_buffer);
    }
    va_end(args);
}

/*
 * Reliable path for protocol/router traffic.
 *
 * Runtime logs remain best-effort and nonblocking through UART_SendString().
 * Commands, replies and Router frames get a bounded wait so they are not
 * silently lost when the fixed TX pool temporarily lacks a contiguous run.
 */
static uint8_t UART_SendReliableString(const char *str)
{
    size_t len;

    if (str == NULL)
    {
        return 0U;
    }

    len = strlen(str);

    if ((g_rtos_started != 0U) &&
        (g_uart_async_runtime_enable != 0U))
    {
        return (UART_Async_WriteReliable(
                    (const uint8_t *)str,
                    len,
                    UART_PROTOCOL_TX_TIMEOUT_MS) == len) ? 1U : 0U;
    }

    return (HAL_UART_Transmit(
                &hlpuart1,
                (uint8_t *)str,
                (uint16_t)len,
                HAL_MAX_DELAY) == HAL_OK) ? 1U : 0U;
}


/*
 * Router Stage 3: routed synchronous Protocol V2 reply context.
 *
 * Legacy UART commands keep the old raw UART response.
 * A ROUTER_PKT_PROTOCOL packet carries its source node into ProtocolTask.
 * While Protocol_HandleLine() executes, synchronous Protocol output is
 * wrapped back into ROUTER_PKT_PROTOCOL packets addressed to that source.
 */
static uint8_t protocol_reply_route_active = 0U;
static uint16_t protocol_reply_route_dst = 0U;
static volatile uint32_t protocol_reply_route_ok = 0U;
static volatile uint32_t protocol_reply_route_fail = 0U;
/* One COM5-initiated diagnostic request at a time. Never a motor command. */
static uint8_t protocol_esp_ping_uart_local = 0U;
static uint8_t protocol_esp_ping_pending = 0U;
static uint16_t protocol_esp_ping_request_id = 0U;
static TickType_t protocol_esp_ping_deadline = 0U;


static void Protocol_SetReplyRoute(uint16_t dst_node)
{
    if ((dst_node != 0U) &&
        (dst_node != ROUTER_BROADCAST_NODE) &&
        (dst_node != 1U))
    {
        protocol_reply_route_dst = dst_node;
        protocol_reply_route_active = 1U;
    }
    else
    {
        protocol_reply_route_dst = 0U;
        protocol_reply_route_active = 0U;
    }
}


static void Protocol_ClearReplyRoute(void)
{
    protocol_reply_route_active = 0U;
    protocol_reply_route_dst = 0U;
}


static uint8_t Protocol_SendString(const char *str)
{
    const char *p;
    uint8_t ok = 1U;

    if (str == NULL)
    {
        return 0U;
    }

    if (protocol_reply_route_active == 0U)
    {
        return UART_SendReliableString(str);
    }

    /*
     * Router UART framing is line based. Split CR/LF-separated Protocol
     * output into individual routed packets. Return failure if any packet
     * cannot be accepted by the Router, so critical IAP ACK paths can avoid
     * silently committing a half-visible protocol state.
     */
    p = str;

    while (*p != '\0')
    {
        const char *end = p;
        size_t len;
        char payload[ROUTER_MAX_PAYLOAD + 1U];

        while ((*end != '\0') &&
               (*end != '\r') &&
               (*end != '\n'))
        {
            end++;
        }

        len = (size_t)(end - p);

        if (len > 0U)
        {
            uint16_t seq = 0U;

            if (len > ROUTER_MAX_PAYLOAD)
            {
                protocol_reply_route_fail++;
                UART_SendLiteral("EVT ROUTER REPLY_TOO_LONG\r\n");
                return 0U;
            }

            memcpy(payload, p, len);
            payload[len] = '\0';

            if (Router_SendText(
                    protocol_reply_route_dst,
                    ROUTER_PKT_PROTOCOL,
                    payload,
                    &seq) != 0U)
            {
                protocol_reply_route_ok++;
            }
            else
            {
                protocol_reply_route_fail++;
                UART_SendLiteral("EVT ROUTER REPLY_NO_ROUTE\r\n");
                ok = 0U;
            }
        }

        while ((*end == '\r') || (*end == '\n'))
        {
            end++;
        }

        p = end;
    }

    return ok;
}

/* Known producers format into the final UART lease at runtime. A local array
 * is used only by synchronous boot/routed output; no borrowed stack TX. */
static uint8_t Protocol_SendFormatted(char *fallback, size_t capacity,
                                      const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(
        (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
         g_uart_async_runtime_enable != 0U),
        UART_Async_VPrintf, Protocol_SendString, fallback, capacity,
        UART_PROTOCOL_TX_TIMEOUT_MS, format, args);
    va_end(args);
    return accepted;
}

static uint8_t UART_SendReliableFormatted(char *fallback, size_t capacity,
                                          const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(
        (g_rtos_started != 0U && g_uart_async_runtime_enable != 0U),
        UART_Async_VPrintf, UART_SendReliableString, fallback, capacity,
        UART_PROTOCOL_TX_TIMEOUT_MS, format, args);
    va_end(args);
    return accepted;
}

static uint8_t Modbus_Enqueue(const ModbusJob_t *job)
{
    ModbusJob_t queued;

    if ((job == NULL) || (modbus_request_queue == NULL))
    {
        return 0U;
    }
    queued = *job;
    queued.routed = protocol_reply_route_active;
    queued.reply_dst = protocol_reply_route_dst;
    if (xQueueSend(modbus_request_queue, &queued, 0U) != pdPASS)
    {
        modbus_queue_full++;
        return 0U;
    }
    modbus_submitted++;
    return 1U;
}

static void ModbusTask(void *argument)
{
    ModbusJob_t job;

    (void)argument;
    for (;;)
    {
        ModbusCompletion_t completion;

        if (xQueueReceive(modbus_request_queue, &job, portMAX_DELAY) != pdPASS)
        {
            continue;
        }
        memset(&completion, 0, sizeof(completion));
        completion.job = job;
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            completion.busy = 1U;
        }
        else if (job.type == MODBUS_JOB_READ)
        {
            completion.result = ModbusProbe_ReadOne(
                job.baud, job.slave, job.function, job.address,
                job.even_parity, &completion.reply);
        }
        else
        {
            completion.result = ModbusProbe_SetRelay(
                job.relay, job.on, &completion.reply);
        }
        modbus_completed++;
        if ((completion.busy != 0U) ||
            (completion.result != MODBUS_PROBE_OK))
        {
            modbus_failed++;
        }
        if (completion.result == MODBUS_PROBE_TIMEOUT)
        {
            modbus_timeout++;
        }
        if (completion.result == MODBUS_PROBE_CRC_ERROR)
        {
            modbus_crc_error++;
        }
        /* Backpressure is bounded by the request queue; never lose a reply. */
        (void)xQueueSend(modbus_completion_queue, &completion, portMAX_DELAY);
    }
}

static void Modbus_ServiceCompletions(uint32_t budget)
{
    ModbusCompletion_t completion;
    uint32_t handled = 0U;

    while ((handled < budget) &&
           (xQueueReceive(modbus_completion_queue, &completion, 0U) == pdPASS))
    {
        const ModbusJob_t *job = &completion.job;
        const ModbusProbeReply_t *reply = &completion.reply;
        char line[192];

        if (job->routed != 0U)
        {
            Protocol_SetReplyRoute(job->reply_dst);
        }
        else
        {
            Protocol_ClearReplyRoute();
        }
        if (completion.busy != 0U)
        {
            (void)Protocol_SendFormatted(line, sizeof(line), "%lu ERR 101 MOTOR_NOT_IDLE\r\n",
                     (unsigned long)job->request_id);
        }
        else if (job->type == MODBUS_JOB_READ)
        {
            if (completion.result == MODBUS_PROBE_OK)
            {
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu OK MODBUS READ ID=%u FC=%u ADDR=%u VALUE=0x%04X DEC=%u RX=%u\r\n",
                         (unsigned long)job->request_id, job->slave,
                         job->function, job->address,
                         reply->value, reply->value, reply->received_bytes);
            }
            else if (completion.result == MODBUS_PROBE_EXCEPTION)
            {
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu OK MODBUS EXCEPTION ID=%u FC=%u CODE=%u RX=%u\r\n",
                         (unsigned long)job->request_id, job->slave,
                         job->function, reply->exception_code,
                         reply->received_bytes);
            }
            else
            {
                const char *name = completion.result == MODBUS_PROBE_TIMEOUT ? "TIMEOUT" :
                    completion.result == MODBUS_PROBE_CRC_ERROR ? "CRC" :
                    completion.result == MODBUS_PROBE_BAD_FRAME ? "BAD_FRAME" :
                    completion.result == MODBUS_PROBE_BAD_ARGUMENT ? "BAD_ARGUMENT" : "UART";
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu ERR MODBUS %s ID=%u FC=%u BAUD=%lu RX=%u UART=0x%lX\r\n",
                         (unsigned long)job->request_id, name, job->slave,
                         job->function, (unsigned long)job->baud,
                         reply->received_bytes, (unsigned long)reply->uart_error);
            }
        }
        else if (completion.result == MODBUS_PROBE_OK)
        {
            (void)Protocol_SendFormatted(line, sizeof(line),
                     "%lu OK MODBUS RELAY=%u STATE=%s ACK=1\r\n",
                     (unsigned long)job->request_id, job->relay,
                     job->on != 0U ? "ON" : "OFF");
        }
        else
        {
            const char *name = completion.result == MODBUS_PROBE_TIMEOUT ? "TIMEOUT" :
                completion.result == MODBUS_PROBE_CRC_ERROR ? "CRC" :
                completion.result == MODBUS_PROBE_BAD_FRAME ? "BAD_FRAME" :
                completion.result == MODBUS_PROBE_EXCEPTION ? "EXCEPTION" : "UART";
            (void)Protocol_SendFormatted(line, sizeof(line),
                     "%lu ERR MODBUS RELAY=%u %s CODE=%u RX=%u UART=0x%lX\r\n",
                     (unsigned long)job->request_id, job->relay, name,
                     reply->exception_code, reply->received_bytes,
                     (unsigned long)reply->uart_error);
        }
        (void)
        Protocol_ClearReplyRoute();
        handled++;
    }
}

/* C linkage bridge used by the C++ pw_rpc ChannelOutput. */
uint8_t PW_Rpc_ProtocolSend(const char *line)
{
    return Protocol_SendString(line);
}

#if defined(CAN_RPC_READ_ONLY)
/* Short RAM snapshots only. Never dispatch textual commands from CAN RPC. */
size_t PW_Rpc_ReadOnlySnapshot(uint32_t kind, uint8_t *out, size_t capacity)
{
    uint32_t words[RPC_READONLY_PARAMS_WORDS] = {RPC_READONLY_VERSION};
    size_t count = 0U;
    if (out == NULL) return 0U;
    if (kind == RPC_READONLY_SNAPSHOT_STATUS)
    {
        count = RPC_READONLY_STATUS_WORDS;
        taskENTER_CRITICAL();
        words[1] = HAL_GetTick();
        words[2] = (uint32_t)motor_control_mode;
        words[3] = (foc_enable != 0U ? 1U : 0U) |
                   (foc_fault != 0U ? 2U : 0U) |
                   (encoder_valid != 0U ? 4U : 0U);
        words[4] = foc_fault_reason;
        words[5] = analog_safe_latched;
        words[6] = fw_update.active;
        words[7] = 0U; /* CAN motion control is permanently rejected in this profile. */
        taskEXIT_CRITICAL();
    }
    else if (kind == RPC_READONLY_SNAPSHOT_PARAMS)
    {
        TightenParams_t snapshot;
        taskENTER_CRITICAL(); snapshot = recipe_state.params; taskEXIT_CRITICAL();
        size_t index = 1U;
#define RPC_PARAM_WORD(field, name, low, high, initial) words[index++] = snapshot.field;
        TIGHTEN_PARAM_FIELDS(RPC_PARAM_WORD)
#undef RPC_PARAM_WORD
        count = index;
    }
    else if (kind == RPC_READONLY_SNAPSHOT_DIAGNOSTICS)
    {
        PW_LogDiagnostics_t logs;
        CAN_StatusTx_Health can;
        PW_CanRpcDiagnostics rpc;
        PW_Log_GetDiagnostics(&logs);
        PW_CanRpc_GetCanSnapshot(&can);
        PW_CanRpc_GetDiagnostics(&rpc);
        count = RPC_READONLY_DIAG_WORDS;
        words[1] = logs.ready; words[2] = logs.enqueued;
        words[3] = logs.dropped_full; words[4] = logs.dropped_uart;
        words[5] = logs.dropped_pool; words[6] = can.ready;
        words[7] = can.bus_off_events; words[8] = can.recoveries;
        words[9] = rpc.fifo_overruns;
    }
    if (count == 0U || count * 4U > capacity) return 0U;
    for (size_t i = 0U; i < count; ++i)
        for (unsigned byte = 0U; byte < 4U; ++byte)
            out[i * 4U + byte] = (uint8_t)(words[i] >> (byte * 8U));
    return count * 4U;
}
#endif


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
#include "foc_fault_snapshot.inc"

static void MotorControl_SetIdle(void)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_IDLE) ProtectedLoop_PwmInvalidate();
#endif
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
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_SPEED) ProtectedLoop_PwmInvalidate();
#endif
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
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_POSITION) ProtectedLoop_PwmInvalidate();
#endif
    motor_position_command_deg = position_deg;
    motor_speed_command_rpm = 0.0f;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = (active_hold != 0U) ? 1U : 0U;
    motor_control_mode = MOTOR_MODE_POSITION;
}


static void MotorControl_SetIq(float iq_A)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_IQ) ProtectedLoop_PwmInvalidate();
#endif
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
#if defined(FOC_ISOLATED_CONCURRENCY)
#include "isolated_concurrency.inc"
#endif
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
#include "control_chain_reconnect.inc"
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_closed_loop.inc"
#if defined(FOC_LATEST_ORIGINAL_FSM)
#include "latest_original_fsm.inc"
#endif
#endif
static void MotorControlTask(void *argument)
{
    TickType_t last_wake_time;
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendLiteral(
        "MotorControlTask started @ 1kHz\r\n"
        "Generic modes: IDLE / POSITION / SPEED / IQ\r\n"
        "20kHz current loop remains in ADC injected ISR\r\n");

    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;
    preflight_adc_progress_tick = xTaskGetTickCount();
    preflight_foc_progress_tick = preflight_adc_progress_tick;

    for (;;)
    {
        TickType_t now = xTaskGetTickCount();
        uint32_t adc_now = injected_seq_count;
        uint32_t foc_now = foc_control_count;

#if defined(FOC_PROTECTED_CLOSED_LOOP)
        ProtectedLoop_TaskService();
        if (adc_now != last_adc_count) { last_adc_count=adc_now; preflight_adc_progress_tick=now; }
        if (foc_now != last_foc_count) { last_foc_count=foc_now; preflight_foc_progress_tick=now; }
        vTaskDelayUntil(&last_wake_time,pdMS_TO_TICKS(1U));
        continue;
#endif

#if defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedBench_Service();
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
        /* Reuse the original outer-loop task, but NEVER unlock power gates. */
        if (!IsolatedBench_Active())
        {
            MotorControl_SetIdle();
            foc_iq_ref_A = 0.0f;
            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
            continue;
        }
#else
        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
        continue;
#endif
#endif
        /* Stopping TIM1 for analog diagnostics intentionally stops the
         * injected ADC/FOC counters; it is not an ADC-chain fault. */
#if !defined(FOC_CONTROL_CHAIN_RECONNECT)
        if (analog_safe_latched != 0U)
        {
#if defined(AS5047P_SPI_DMA)
            if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
#endif
            foc_enable = 0U;
            foc_iq_ref_A = 0.0f;
            PowerStage_Disable();
            __HAL_TIM_MOE_DISABLE(&htim1);
            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
            continue;
        }
#endif

        if (adc_now != last_adc_count)
        {
            last_adc_count = adc_now;
            preflight_adc_progress_tick = now;
        }
        if (foc_now != last_foc_count)
        {
            last_foc_count = foc_now;
            preflight_foc_progress_tick = now;
        }
        /*
         * A stalled 20 kHz ADC/FOC chain must disable the bridge even after
         * START has already passed preflight.  Only arm this check after run
         * zero calibration; otherwise the intentional startup gap would
         * falsely latch a fault.  Keep the first fault reason intact.
         */
        if ((run_zero_cal_done != 0U) &&
            (adc_fault == 0U) && (foc_fault == 0U))
        {
            if ((now - preflight_adc_progress_tick) >
                pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
            {
                foc_fault_reason = FOC_FAULT_ADC_CHAIN_STALE;
                foc_fault = 1U;
                PowerStage_Disable();
                FaultDiag_Capture(FOC_DIAG_MOTOR,FOC_FAULT_ADC_CHAIN_STALE,
                    FOC_TO_ADC_CHAIN,(uint32_t)((now-preflight_adc_progress_tick)*portTICK_PERIOD_MS),
                    PREFLIGHT_CHAIN_MAX_STALE_MS);
            }
            else if ((now - preflight_foc_progress_tick) >
                     pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
            {
                foc_fault_reason = FOC_FAULT_CONTROL_CHAIN_STALE;
                foc_fault = 1U;
                PowerStage_Disable();
                FaultDiag_Capture(FOC_DIAG_MOTOR,FOC_FAULT_CONTROL_CHAIN_STALE,
                    FOC_TO_CONTROL_CHAIN,(uint32_t)((now-preflight_foc_progress_tick)*portTICK_PERIOD_MS),
                    PREFLIGHT_CHAIN_MAX_STALE_MS);
            }
        }
        if ((adc_fault == 0U) && (foc_fault == 0U))
        {
#if defined(AS5047P_SPI_DMA)
            if (!AS5047P_DmaIsPeriodic())
            {
                encoder_dma_cursor.valid = 0U;
                encoder_prev_valid = 0U;
                encoder_speed_dt_accum_s = 0.0f;
                if (!AS5047P_DmaStartPeriodic()) EncoderDma_FaultFromISR();
            }
            if (foc_fault == 0U)
            {
                HAL_StatusTypeDef update = FOC_EncoderSpeedUpdate(0.001f);
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
                if (update == HAL_OK && control_chain_active)
                    ++control_chain_outer_steps;
#else
                (void)update;
#endif
            }
#else
            (void)FOC_EncoderSpeedUpdate(0.001f);
#endif
        }

        /*
         * Immediate safe-state reaction.  The lower-priority application task
         * cannot override a latched hardware/control fault.
         */
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
#if defined(AS5047P_SPI_DMA)
            if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
#endif
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

    UART_SendFormatted(
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
}


#if defined(ESP_NETWORK_OBSERVER)
#include "network_observer.inc"
#endif
static void TighteningResult_PrintSummary(const char *result_text)
{
    char msg[256];
#if defined(ESP_NETWORK_OBSERVER)
    NetworkObserver_Publish(NET_KIND_RESULT);
#endif

    UART_SendLiteral(
        "\r\n"
        "========== TIGHTEN RESULT ==========\r\n");

    UART_SendFormatted(
        msg,
        sizeof(msg),
        "Start request : %lu\r\n",
        (unsigned long)tightening_cycle_request_id);

    if (tightening_contact_confirmed != 0U)
    {
        int32_t contact_x100 =
            (int32_t)(tightening_contact_position_deg * 100.0f);
        int32_t post_x100 =
            (int32_t)(tightening_post_contact_travel_deg * 100.0f);

        UART_SendFormatted(
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
        UART_SendFormatted(
            msg,
            sizeof(msg),
            "RESULT        : %s\r\n"
            "Contact angle : N/A\r\n"
            "Post travel   : N/A\r\n",
            (result_text != NULL) ? result_text : "UNKNOWN");
    }


    TighteningResult_PrintStage("SEATING", &tighten_result_seating);
    TighteningResult_PrintStage("TIGHTEN#1", &tighten_result_010);
    TighteningResult_PrintStage("TIGHTEN#2", &tighten_result_012);
    TighteningResult_PrintStage("TIGHTEN#3", &tighten_result_015);
    TighteningResult_PrintStage("HOLD", &tighten_result_hold);

    UART_SendLiteral(
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
        (float)recipe_state.params.seating_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_010,
        (float)recipe_state.params.t1_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_012,
        (float)recipe_state.params.t2_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_015,
        (float)recipe_state.params.t3_iq_mA / 1000.0f);
    TighteningResult_Reset(
        &tighten_result_hold,
        (float)recipe_state.params.hold_iq_mA / 1000.0f);
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

    UART_SendLiteral(
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

        UART_SendFormatted(
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

        UART_SendFormatted(
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
    }

    UART_SendLiteral(
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
    char msg[256];

    (void)Protocol_SendFormatted(
        msg,
        sizeof(msg),
        "%lu %s\r\n",
        (unsigned long)request_id,
        (payload != NULL) ? payload : "");
}


static void Protocol_SendError(
    uint32_t request_id,
    ProtocolError_t code,
    const char *name)
{
    char msg[128];

    (void)Protocol_SendFormatted(
        msg,
        sizeof(msg),
        "%lu ERR %u %s\r\n",
        (unsigned long)request_id,
        (unsigned int)code,
        (name != NULL) ? name : "UNKNOWN");
}


static void Protocol_EspPingService(void)
{
    if ((protocol_esp_ping_pending != 0U) &&
        ((int32_t)(xTaskGetTickCount() -
                   protocol_esp_ping_deadline) >= 0))
    {
        const uint16_t request_id = protocol_esp_ping_request_id;
        protocol_esp_ping_pending = 0U;
        Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                           "ESP_PING_TIMEOUT");
    }
}


static void Protocol_EspPingHandlePacket(const RouterPacket_t *packet)
{
    uint16_t reply_id = 0U;

    if ((packet == NULL) ||
        (packet->ingress_port != ROUTER_PORT_ESP32) ||
        (packet->src != 2U) ||
        (packet->dst != ROUTER_LOCAL_NODE_ID) ||
        (packet->type != ROUTER_PKT_PROTOCOL) ||
        (EspPing_ParsePongPayload(packet->payload, &reply_id) == 0U) ||
        (protocol_esp_ping_pending == 0U) ||
        (reply_id != protocol_esp_ping_request_id) ||
        ((int32_t)(xTaskGetTickCount() -
                   protocol_esp_ping_deadline) >= 0))
    {
        return;
    }

    protocol_esp_ping_pending = 0U;
    Protocol_SendTaggedLine(reply_id, "OK ESP32 PONG");
}


static void TighteningSession_Begin(
    uint8_t routed,
    uint16_t owner_node,
    uint32_t request_id)
{
#if defined(ESP_NETWORK_OBSERVER)
    taskENTER_CRITICAL(); g_network_run++; taskEXIT_CRITICAL();
#endif
    g_tightening_session_routed = (routed != 0U) ? 1U : 0U;
    g_tightening_session_owner_node =
        (routed != 0U) ? owner_node : 0U;
    g_tightening_session_request_id = request_id;

    /* Publish active last, after the owner/correlation fields are valid. */
    __DMB();
    g_tightening_session_active = 1U;
}


static void TighteningSession_End(void)
{
    /*
     * Keep owner_node/request_id as the last-session diagnostic snapshot.
     * Stage 4.3 copies the terminal EVT into the reliable-event path before this function is called.
     */
    g_tightening_session_active = 0U;
    __DMB();
}


static uint8_t Protocol_AsyncEventEnqueue(
    uint8_t routed,
    uint16_t dst_node,
    const char *payload)
{
    ProtocolAsyncEvent_t evt;
    size_t len;

    if ((protocol_async_event_queue == NULL) || (payload == NULL))
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    len = strlen(payload);
    if ((len == 0U) || (len > ROUTER_MAX_PAYLOAD))
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    memset(&evt, 0, sizeof(evt));
    evt.routed = (routed != 0U) ? 1U : 0U;
    evt.dst_node = (evt.routed != 0U) ? dst_node : 0U;
    memcpy(evt.payload, payload, len + 1U);

    if (xQueueSend(protocol_async_event_queue, &evt, 0U) != pdPASS)
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    g_protocol_async_event_enqueued++;
    return 1U;
}


static uint8_t Protocol_ReliableEventParseEid(
    const char *text,
    const char *prefix,
    uint32_t *eid_out)
{
    const char *p;
    char *endptr;
    unsigned long value;
    size_t prefix_len;

    if ((text == NULL) || (prefix == NULL) || (eid_out == NULL))
    {
        return 0U;
    }

    prefix_len = strlen(prefix);
    if (strncmp(text, prefix, prefix_len) != 0)
    {
        return 0U;
    }

    p = text + prefix_len;
    value = strtoul(p, &endptr, 10);

    if ((endptr == p) ||
        (value == 0UL) ||
        (value > 0xFFFFFFFFUL))
    {
        return 0U;
    }

    /* EVENT has more payload after EID; ACK ends immediately after EID. */
    if ((*endptr != '\0') && (*endptr != ' ') && (*endptr != '\t'))
    {
        return 0U;
    }

    *eid_out = (uint32_t)value;
    return 1U;
}


static uint8_t Protocol_ReliableEventTransmit(
    ProtocolReliableEvent_t *slot,
    uint8_t is_retry)
{
    uint16_t router_seq = 0U;
    uint8_t ok;

    if ((slot == NULL) || (slot->in_use == 0U))
    {
        return 0U;
    }

    if (is_retry != 0U)
    {
        g_protocol_reliable_event_retried++;
    }

    ok = Router_SendText(
        slot->dst_node,
        PROTOCOL_ROUTER_TYPE_EVENT,
        slot->payload,
        &router_seq);

    /* One initial send + bounded retry attempts. */
    slot->attempts++;
    slot->next_retry_tick =
        xTaskGetTickCount() +
        pdMS_TO_TICKS(PROTOCOL_RELIABLE_EVENT_RETRY_MS);

    if (ok != 0U)
    {
        g_protocol_async_event_route_ok++;
        g_protocol_reliable_event_sent++;
        return 1U;
    }

    g_protocol_async_event_route_fail++;
    g_protocol_reliable_event_no_route++;
    return 0U;
}


static uint8_t Protocol_ReliableEventStart(
    uint16_t dst_node,
    const char *payload)
{
    ProtocolReliableEvent_t *slot = NULL;
    uint32_t i;
    uint32_t eid;
    int n;

    if ((payload == NULL) ||
        (dst_node == 0U) ||
        (dst_node == ROUTER_BROADCAST_NODE) ||
        (dst_node == ROUTER_LOCAL_NODE_ID))
    {
        return 0U;
    }

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        if (protocol_reliable_events[i].in_use == 0U)
        {
            slot = &protocol_reliable_events[i];
            break;
        }
    }

    if (slot == NULL)
    {
        g_protocol_reliable_event_table_full++;
        UART_SendLiteral("EVT RELIABLE TABLE FULL\r\n");
        return 0U;
    }

    eid = protocol_reliable_next_eid++;
    if (eid == 0U)
    {
        eid = protocol_reliable_next_eid++;
    }

    memset(slot, 0, sizeof(*slot));
    slot->eid = eid;
    slot->dst_node = dst_node;

    if (strncmp(payload, "EVT ", 4U) == 0)
    {
        n = snprintf(
            slot->payload,
            sizeof(slot->payload),
            "EVT EID=%lu %s",
            (unsigned long)eid,
            payload + 4U);
    }
    else
    {
        n = snprintf(
            slot->payload,
            sizeof(slot->payload),
            "EVT EID=%lu %s",
            (unsigned long)eid,
            payload);
    }

    if ((n <= 0) || ((size_t)n > ROUTER_MAX_PAYLOAD))
    {
        memset(slot, 0, sizeof(*slot));
        g_protocol_async_event_queue_drop++;
        UART_SendLiteral("EVT RELIABLE PAYLOAD TOO LONG\r\n");
        return 0U;
    }

    /* ProtocolTask is the only writer of the pending table. */
    slot->in_use = 1U;
    __DMB();
    g_protocol_reliable_event_created++;

    (void)Protocol_ReliableEventTransmit(slot, 0U);
    return 1U;
}


static uint8_t Protocol_ReliableEventAck(
    uint16_t src_node,
    uint32_t eid)
{
    uint32_t i;

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        ProtocolReliableEvent_t *slot = &protocol_reliable_events[i];

        if ((slot->in_use != 0U) &&
            (slot->eid == eid) &&
            (slot->dst_node == src_node))
        {
            slot->in_use = 0U;
            __DMB();
            g_protocol_reliable_event_acked++;
            return 1U;
        }
    }

    g_protocol_reliable_event_bad_ack++;
    return 0U;
}


static uint32_t Protocol_ReliableEventPendingCount(void)
{
    uint32_t i;
    uint32_t count = 0U;

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        if (protocol_reliable_events[i].in_use != 0U)
        {
            count++;
        }
    }

    return count;
}


static uint8_t Protocol_ReliableEventRxSeen(
    uint16_t src_node,
    uint32_t eid)
{
    TickType_t now = xTaskGetTickCount();
    uint32_t i;

    for (i = 0U; i < PROTOCOL_RELIABLE_RX_CACHE_SIZE; i++)
    {
        ProtocolReliableRxCache_t *entry =
            &protocol_reliable_rx_cache[i];

        if ((entry->valid != 0U) &&
            ((int32_t)(now - entry->expires_tick) >= 0))
        {
            entry->valid = 0U;
        }

        if ((entry->valid != 0U) &&
            (entry->src_node == src_node) &&
            (entry->eid == eid))
        {
            return 1U;
        }
    }

    i = protocol_reliable_rx_cache_cursor %
        PROTOCOL_RELIABLE_RX_CACHE_SIZE;
    protocol_reliable_rx_cache_cursor++;

    protocol_reliable_rx_cache[i].src_node = src_node;
    protocol_reliable_rx_cache[i].eid = eid;
    protocol_reliable_rx_cache[i].expires_tick =
        now + pdMS_TO_TICKS(PROTOCOL_RELIABLE_RX_CACHE_MS);
    protocol_reliable_rx_cache[i].valid = 1U;
    return 0U;
}


static void Protocol_ReliableEventHandleEventPacket(
    const RouterPacket_t *packet)
{
    uint32_t eid;
    uint8_t duplicate;
    char ack_payload[32];
    char dbg[ROUTER_MAX_PAYLOAD + 64U];
    uint16_t seq = 0U;

    if ((packet == NULL) ||
        (packet->src == 0U) ||
        (packet->src == ROUTER_BROADCAST_NODE) ||
        (Protocol_ReliableEventParseEid(
            packet->payload,
            "EVT EID=",
            &eid) == 0U))
    {
        g_protocol_reliable_event_bad_event++;
        UART_SendLiteral("EVT RX BAD EVENT FRAME\r\n");
        return;
    }

    duplicate = Protocol_ReliableEventRxSeen(packet->src, eid);
    if (duplicate != 0U)
    {
        g_protocol_reliable_event_rx_duplicate++;
    }
    else
    {
        g_protocol_reliable_event_rx++;

        /*
         * Stage 4.3 receiver-side delivery hook. For now delivery is a
         * reliable diagnostic line. A later controller/application layer can
         * replace this with a real event callback without changing the wire
         * protocol.
         */
        UART_SendFormatted(
            dbg,
            sizeof(dbg),
            "REMOTE EVENT SRC=%u %s\r\n",
            (unsigned int)packet->src,
            packet->payload);
    }

    /* ACK every valid copy, including a retry already seen before. */
    snprintf(
        ack_payload,
        sizeof(ack_payload),
        "EID=%lu",
        (unsigned long)eid);

    if (Router_SendText(
            packet->src,
            PROTOCOL_ROUTER_TYPE_EVENT_ACK,
            ack_payload,
            &seq) != 0U)
    {
        g_protocol_reliable_event_ack_tx++;
    }
    else
    {
        g_protocol_reliable_event_ack_tx_fail++;
    }
}


static void Protocol_ReliableEventHandleAckPacket(
    const RouterPacket_t *packet)
{
    uint32_t eid;

    if ((packet == NULL) ||
        (packet->src == 0U) ||
        (packet->src == ROUTER_BROADCAST_NODE) ||
        (Protocol_ReliableEventParseEid(
            packet->payload,
            "EID=",
            &eid) == 0U))
    {
        g_protocol_reliable_event_bad_ack++;
        return;
    }

    (void)Protocol_ReliableEventAck(packet->src, eid);
}


static void Protocol_ReliableEventService(uint32_t budget)
{
    TickType_t now = xTaskGetTickCount();
    uint32_t i;

    for (i = 0U;
         (i < PROTOCOL_RELIABLE_EVENT_SLOTS) && (budget > 0U);
         i++)
    {
        ProtocolReliableEvent_t *slot = &protocol_reliable_events[i];

        if (slot->in_use == 0U)
        {
            continue;
        }

        if ((int32_t)(now - slot->next_retry_tick) < 0)
        {
            continue;
        }

        if (slot->attempts >= PROTOCOL_RELIABLE_EVENT_MAX_ATTEMPTS)
        {
            char dbg[128];

            UART_SendFormatted(
                dbg,
                sizeof(dbg),
                "EVT RELIABLE GIVEUP EID=%lu DST=%u ATTEMPTS=%u\r\n",
                (unsigned long)slot->eid,
                (unsigned int)slot->dst_node,
                (unsigned int)slot->attempts);

            slot->in_use = 0U;
            __DMB();
            g_protocol_reliable_event_giveup++;
            budget--;
            continue;
        }

        (void)Protocol_ReliableEventTransmit(slot, 1U);
        budget--;
    }
}


static void Protocol_AsyncEventService(uint32_t budget)
{
    ProtocolAsyncEvent_t evt;

    while ((budget > 0U) &&
           (protocol_async_event_queue != NULL) &&
           (xQueueReceive(protocol_async_event_queue, &evt, 0U) == pdPASS))
    {
        if ((evt.routed != 0U) &&
            (evt.dst_node != 0U) &&
            (evt.dst_node != ROUTER_BROADCAST_NODE) &&
            (evt.dst_node != ROUTER_LOCAL_NODE_ID))
        {
            if (Protocol_ReliableEventStart(
                    evt.dst_node,
                    evt.payload) == 0U)
            {
                char dbg[96];

                UART_SendFormatted(
                    dbg,
                    sizeof(dbg),
                    "EVT RELIABLE START FAILED DST=%u\r\n",
                    (unsigned int)evt.dst_node);
            }
        }
        else
        {
            char line[ROUTER_MAX_PAYLOAD + 3U];

            if (UART_SendReliableFormatted(line, sizeof(line),
                                           "%s\r\n", evt.payload) != 0U)
            {
                g_protocol_async_event_local_ok++;
            }
        }

        budget--;
    }
}


static void Protocol_SendDeferredStartError(
    uint8_t routed,
    uint16_t dst_node,
    uint32_t request_id,
    const char *name)
{
    char payload[128];

    snprintf(
        payload,
        sizeof(payload),
        "EVT REQ=%lu ERROR RESULT=%s",
        (unsigned long)request_id,
        (name != NULL) ? name : "UNKNOWN");

    if (Protocol_AsyncEventEnqueue(
            routed,
            dst_node,
            payload) == 0U)
    {
        UART_SendLiteral("EVT ASYNC QUEUE FULL: START ERROR LOST\r\n");
    }
}


static void Protocol_SendCycleEvent(
    const char *event_name,
    const char *result_name)
{
    char payload[160];
    uint8_t routed = g_tightening_session_routed;
    uint16_t owner_node = g_tightening_session_owner_node;
    uint32_t request_id = g_tightening_session_request_id;

    if (result_name != NULL)
    {
        snprintf(
            payload,
            sizeof(payload),
            "EVT REQ=%lu %s RESULT=%s",
            (unsigned long)request_id,
            (event_name != NULL) ? event_name : "EVENT",
            result_name);
    }
    else
    {
        snprintf(
            payload,
            sizeof(payload),
            "EVT REQ=%lu %s",
            (unsigned long)request_id,
            (event_name != NULL) ? event_name : "EVENT");
    }

    if (Protocol_AsyncEventEnqueue(
            routed,
            owner_node,
            payload) == 0U)
    {
        UART_SendLiteral("EVT ASYNC QUEUE FULL: TERMINAL EVENT LOST\r\n");
    }

    /*
     * The queue item owns a copy of routed/destination/payload, so the
     * business session can be closed immediately after the terminal event is
     * accepted. The next START cannot accidentally overwrite this event.
     */
    TighteningSession_End();
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

    (void)Protocol_SendFormatted(
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
}


static uint32_t SystemPreflight_FailMask(void)
{
    uint32_t mask = 0U;
#if defined(SAFETY_LOCKED_BOOT)
    mask |= PREFLIGHT_FAIL_BOOT_LOCK;
#endif

    if (adc_fault != 0U) mask |= PREFLIGHT_FAIL_ADC_FAULT;
    if (foc_fault != 0U) mask |= PREFLIGHT_FAIL_FOC_FAULT;
    if (encoder_valid == 0U) mask |= PREFLIGHT_FAIL_ENCODER;
    if (foc_enable == 0U) mask |= PREFLIGHT_FAIL_FOC_DISABLED;
    if (run_zero_cal_done == 0U) mask |= PREFLIGHT_FAIL_ZERO_CAL;
    if (UART_Async_IsReady() == 0U) mask |= PREFLIGHT_FAIL_UART;
    if (motor_control_mode != MOTOR_MODE_IDLE) mask |= PREFLIGHT_FAIL_MODE;
    if (fabsf(encoder_speed_rpm) > TIGHTEN_REPEAT_RESTART_MAX_RPM)
    {
        mask |= PREFLIGHT_FAIL_SPEED;
    }
    if (fw_update.active != 0U) mask |= PREFLIGHT_FAIL_FW_UPDATE;
    if (BootHealth_IsCurrentTrial() != 0U) mask |= PREFLIGHT_FAIL_TRIAL;
    if ((xTaskGetTickCount() - preflight_adc_progress_tick) >
        pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
    {
        mask |= PREFLIGHT_FAIL_ADC_STALE;
    }
    if ((xTaskGetTickCount() - preflight_foc_progress_tick) >
        pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
    {
        mask |= PREFLIGHT_FAIL_FOC_STALE;
    }
    return mask;
}

#include "motor_job_port.inc"

static void Protocol_PrintSelftestStatus(uint32_t request_id)
{
    uint32_t mask = SystemPreflight_FailMask();
    TickType_t now = xTaskGetTickCount();
    char msg[192];

    (void)Protocol_SendFormatted(msg, sizeof(msg),
             "%lu OK SELFTEST READY=%u MASK=0x%03lX ADC=%u FOC=%u ENC=%u ZERO=%u UART=%u MODE=%s SPEED_OK=%u AAGE=%lu FAGE=%lu ADC_CNT=%lu FOC_CNT=%lu\r\n",
             (unsigned long)request_id,
             mask == 0U ? 1U : 0U,
             (unsigned long)mask,
             adc_fault == 0U ? 1U : 0U,
             (foc_fault == 0U) && (foc_enable != 0U) ? 1U : 0U,
             encoder_valid,
             run_zero_cal_done,
             UART_Async_IsReady(),
             MotorControl_ModeName(motor_control_mode),
             (mask & PREFLIGHT_FAIL_SPEED) == 0U ? 1U : 0U,
             (unsigned long)(now - preflight_adc_progress_tick),
             (unsigned long)(now - preflight_foc_progress_tick),
             (unsigned long)injected_seq_count,
             (unsigned long)foc_control_count);
}


static void TightenParams_RestoreDefaults(void)
{
    TightenParams_ResetDefaults(&recipe_state.params);
    recipe_state.dirty = 1U;
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

/* Hardware boundary only; storage policy and record ABI live in C++. */
static int TightenParams_PortLoad(void *context, void *data, size_t length)
{
    (void)context;
    return PW_Kvs_LoadParams(data, length);
}

static int TightenParams_PortSave(void *context, const void *data, size_t length)
{
    (void)context;
    return PW_Kvs_SaveParams(data, length);
}

static void TightenParams_PortReadLegacy(void *context, void *data, size_t length)
{
    (void)context;
    memcpy(data, (const void *)PARAM_FLASH_ADDRESS, length);
}

_Static_assert(PW_KVS_RESULT_OK == 0 && PW_KVS_RESULT_NOT_FOUND == 1 &&
               PW_KVS_RESULT_ERROR == 2, "Parameter storage port result ABI");

static const TightenParamsStoragePort_t params_storage_port =
{
    NULL, TightenParams_PortLoad, TightenParams_PortSave,
    TightenParams_PortReadLegacy
};

static uint8_t TightenParams_SaveToFlash(void)
{
    return TightenParams_StorageSave(&recipe_state, &params_storage_port);
}

static TightenParamsFlashLoadStatus_t TightenParams_LoadFromFlash(void)
{
    return TightenParams_StorageLoad(&recipe_state, &params_storage_port);
}


/*
 * IAP A/B boot metadata V2 + UART firmware-update helpers.
 *
 * Flash layout:
 *   Bank2 Page126 @ 0x0807F000 : boot metadata
 *   Bank2 Page127 @ 0x0807F800 : tightening parameters
 *
 * The bootloader accepts both legacy V1 metadata and V2 metadata. Once an
 * application writes V2, all later boot selection / trial / rollback state is
 * carried by V2.
 */
static uint8_t BootMeta_ReadV1(BootMetaV1_t *out)
{
    BootMetaV1_t record;
    const BootMetaV1_t *flash_record =
        (const BootMetaV1_t *)BOOT_META_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    memcpy(&record, flash_record, sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V1))
    {
        return 0U;
    }

    if ((record.active_slot != BOOT_SLOT_A) &&
        (record.active_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV1_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_ReadV2Legacy(BootMetaV2_t *out)
{
    BootMetaV2_t record;
    const BootMetaV2_t *flash_record =
        (const BootMetaV2_t *)BOOT_META_COPY0_ADDRESS;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    memcpy(&record, flash_record, sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V2))
    {
        return 0U;
    }

    if ((record.confirmed_slot != BOOT_SLOT_A) &&
        (record.confirmed_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.pending_slot != BOOT_SLOT_NONE) &&
        (record.pending_slot != BOOT_SLOT_A) &&
        (record.pending_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.app_a_size > FW_SLOT_SIZE) ||
        (record.app_b_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV2_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_GenerationIsNewer(uint32_t a,
                                          uint32_t b)
{
    return (((int32_t)(a - b)) > 0) ? 1U : 0U;
}


static uint8_t BootMeta_ReadV3At(uint32_t address,
                                 BootMetaV3_t *out)
{
    BootMetaV3_t record;
    uint32_t crc;

    if (out == NULL)
    {
        return 0U;
    }

    if ((address != BOOT_META_COPY0_ADDRESS) &&
        (address != BOOT_META_COPY1_ADDRESS))
    {
        return 0U;
    }

    memcpy(
        &record,
        (const void *)address,
        sizeof(record));

    if ((record.magic != BOOT_META_MAGIC) ||
        (record.version != BOOT_META_VERSION_V3))
    {
        return 0U;
    }

    if ((record.confirmed_slot != BOOT_SLOT_A) &&
        (record.confirmed_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.pending_slot != BOOT_SLOT_NONE) &&
        (record.pending_slot != BOOT_SLOT_A) &&
        (record.pending_slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    if ((record.app_a_size > FW_SLOT_SIZE) ||
        (record.app_b_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    crc = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV3_t, crc32));

    if (crc != record.crc32)
    {
        return 0U;
    }

    *out = record;
    return 1U;
}


static uint8_t BootMeta_ReadV3(BootMetaV3_t *out)
{
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    uint8_t valid0;
    uint8_t valid1;

    if (out == NULL)
    {
        return 0U;
    }

    valid0 = BootMeta_ReadV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = BootMeta_ReadV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    if ((valid0 == 0U) && (valid1 == 0U))
    {
        return 0U;
    }

    if ((valid0 != 0U) && (valid1 == 0U))
    {
        *out = copy0;
        return 1U;
    }

    if ((valid0 == 0U) && (valid1 != 0U))
    {
        *out = copy1;
        return 1U;
    }

    if (BootMeta_GenerationIsNewer(
            copy1.generation,
            copy0.generation) != 0U)
    {
        *out = copy1;
    }
    else
    {
        *out = copy0;
    }

    return 1U;
}


static uint8_t BootMeta_SaveV3(const BootMetaV3_t *meta)
{
    BootMetaV3_t record;
    BootMetaV3_t copy0;
    BootMetaV3_t copy1;
    BootMetaV3_t latest;
    BootMetaV3_t verify;
    FLASH_EraseInitTypeDef erase_init;
    uint32_t page_error = 0U;
    uint32_t target_address;
    uint32_t target_page;
    uint32_t offset;
    uint8_t valid0;
    uint8_t valid1;
    uint8_t have_latest = 0U;
    HAL_StatusTypeDef status;

    if (meta == NULL)
    {
        return 0U;
    }

    valid0 = BootMeta_ReadV3At(
        BOOT_META_COPY0_ADDRESS,
        &copy0);

    valid1 = BootMeta_ReadV3At(
        BOOT_META_COPY1_ADDRESS,
        &copy1);

    /*
     * Always erase/program the invalid or older page.
     * The newest valid page remains untouched until the replacement has been
     * fully written and CRC-verified.
     */
    if ((valid0 == 0U) && (valid1 == 0U))
    {
        /*
         * First V3 migration writes Page125 first, preserving the legacy V2
         * record at Page126.
         */
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 != 0U) && (valid1 == 0U))
    {
        latest = copy0;
        have_latest = 1U;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }
    else if ((valid0 == 0U) && (valid1 != 0U))
    {
        latest = copy1;
        have_latest = 1U;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else if (BootMeta_GenerationIsNewer(
                 copy1.generation,
                 copy0.generation) != 0U)
    {
        latest = copy1;
        have_latest = 1U;
        target_address = BOOT_META_COPY0_ADDRESS;
        target_page = BOOT_META_COPY0_PAGE;
    }
    else
    {
        latest = copy0;
        have_latest = 1U;
        target_address = BOOT_META_COPY1_ADDRESS;
        target_page = BOOT_META_COPY1_PAGE;
    }

    record = *meta;

    /*
     * Keep generation monotonic even if a caller forgets to increment it.
     */
    if (have_latest != 0U)
    {
        if (BootMeta_GenerationIsNewer(
                record.generation,
                latest.generation) == 0U)
        {
            record.generation =
                latest.generation + 1UL;
        }
    }
    else if (record.generation == 0UL)
    {
        record.generation = 1UL;
    }

    record.magic = BOOT_META_MAGIC;
    record.version = BOOT_META_VERSION_V3;
    record.crc32 = TightenParams_Crc32(
        (const uint8_t *)&record,
        offsetof(BootMetaV3_t, crc32));

    if (HAL_FLASH_Unlock() != HAL_OK)
    {
        return 0U;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = BOOT_META_BANK;
    erase_init.Page = target_page;
    erase_init.NbPages = 1U;

    status = HAL_FLASHEx_Erase(
        &erase_init,
        &page_error);

    if (status == HAL_OK)
    {
        for (offset = 0U;
             offset < sizeof(record);
             offset += 8U)
        {
            uint64_t data64;

            memcpy(
                &data64,
                ((const uint8_t *)&record) + offset,
                sizeof(data64));

            status = HAL_FLASH_Program(
                FLASH_TYPEPROGRAM_DOUBLEWORD,
                target_address + offset,
                data64);

            if (status != HAL_OK)
            {
                break;
            }
        }
    }

    (void)HAL_FLASH_Lock();

    if (status != HAL_OK)
    {
        return 0U;
    }

    if (BootMeta_ReadV3At(
            target_address,
            &verify) == 0U)
    {
        return 0U;
    }

    if (memcmp(
            &verify,
            &record,
            sizeof(record)) != 0)
    {
        return 0U;
    }

    return 1U;
}


static uint8_t BootMeta_EnsureV3(BootMetaV3_t *out)
{
    BootMetaV3_t meta;
    BootMetaV2_t old_v2;
    BootMetaV1_t old_v1;

    if (out == NULL)
    {
        return 0U;
    }

    if (BootMeta_ReadV3(&meta) != 0U)
    {
        *out = meta;
        return 1U;
    }

    memset(&meta, 0, sizeof(meta));
    meta.magic = BOOT_META_MAGIC;
    meta.version = BOOT_META_VERSION_V3;

    /*
     * Preferred migration source is the legacy V2 record, because it already
     * contains confirmed/pending/attempt/image CRC state.
     */
    if (BootMeta_ReadV2Legacy(&old_v2) != 0U)
    {
        meta.confirmed_slot = old_v2.confirmed_slot;
        meta.pending_slot = old_v2.pending_slot;
        meta.attempts_left = old_v2.attempts_left;
        meta.generation = old_v2.generation;
        meta.app_a_size = old_v2.app_a_size;
        meta.app_a_crc32 = old_v2.app_a_crc32;
        meta.app_b_size = old_v2.app_b_size;
        meta.app_b_crc32 = old_v2.app_b_crc32;
        meta.flags = old_v2.flags;
    }
    else
    {
        /*
         * V1 contains only one active slot. If even V1 is absent, the slot
         * that is actually executing is the safest confirmed choice.
         */
        meta.confirmed_slot = APP_THIS_SLOT;
        meta.pending_slot = BOOT_SLOT_NONE;
        meta.attempts_left = 0U;
        meta.generation = 1U;
        meta.flags = 0U;

        if (BootMeta_ReadV1(&old_v1) != 0U)
        {
            (void)old_v1;
        }
    }

    if (BootMeta_SaveV3(&meta) == 0U)
    {
        return 0U;
    }

    if (BootMeta_ReadV3(&meta) == 0U)
    {
        return 0U;
    }

    *out = meta;
    return 1U;
}


static uint8_t BootMailbox_WriteRequest(uint32_t command,
                                        uint32_t target_slot,
                                        uint32_t image_size,
                                        uint32_t image_crc32)
{
    BootMailbox_t request;
    BootMailbox_t verify;
    volatile uint32_t *dst =
        (volatile uint32_t *)BOOT_MAILBOX_ADDRESS;
    const uint32_t *src;
    uint32_t i;

    memset(&request, 0, sizeof(request));

    request.magic = BOOT_MAILBOX_MAGIC;
    request.version = BOOT_MAILBOX_VERSION;
    request.command = command;
    request.requester_slot = APP_THIS_SLOT;
    request.target_slot = target_slot;
    request.image_size = image_size;
    request.image_crc32 = image_crc32;
    request.crc32 = TightenParams_Crc32(
        (const uint8_t *)&request,
        offsetof(BootMailbox_t, crc32));

    src = (const uint32_t *)&request;

    /*
     * Make the mailbox invalid while populating it. Write magic LAST so a
     * reset during the copy cannot create a partially valid command.
     */
    dst[0] = 0UL;
    __DSB();

    for (i = 1UL;
         i < (sizeof(BootMailbox_t) / sizeof(uint32_t));
         i++)
    {
        dst[i] = src[i];
    }

    __DSB();

    dst[0] = src[0];

    __DSB();
    __ISB();

    memcpy(
        &verify,
        (const void *)BOOT_MAILBOX_ADDRESS,
        sizeof(verify));

    if (memcmp(&verify, &request, sizeof(request)) != 0)
    {
        dst[0] = 0UL;
        __DSB();
        return 0U;
    }

    return 1U;
}


static uint8_t BootMailbox_RequestConfirmCurrent(void)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_CONFIRM_CURRENT,
        BOOT_SLOT_NONE,
        0UL,
        0UL);
}


static uint8_t BootMailbox_RequestStartTrial(uint32_t target_slot,
                                             uint32_t image_size,
                                             uint32_t image_crc32)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_START_TRIAL,
        target_slot,
        image_size,
        image_crc32);
}


static uint8_t BootMailbox_RequestSetConfirmedSlot(uint32_t target_slot)
{
    return BootMailbox_WriteRequest(
        BOOT_MAILBOX_CMD_SET_CONFIRMED_SLOT,
        target_slot,
        0UL,
        0UL);
}


static uint8_t BootMeta_ConfirmCurrent(void)
{
    /*
     * V4: do not erase/program Metadata V3 from the application.
     * Ask the bootloader to commit confirmation after reset.
     */
    return BootMailbox_RequestConfirmCurrent();
}


static uint8_t BootMeta_SaveSlot(uint32_t slot)
{
    if ((slot != BOOT_SLOT_A) &&
        (slot != BOOT_SLOT_B))
    {
        return 0U;
    }

    return BootMailbox_RequestSetConfirmedSlot(slot);
}


static uint8_t Fw_HexNibble(char c, uint8_t *value)
{
    if (value == NULL)
    {
        return 0U;
    }

    if ((c >= '0') && (c <= '9'))
    {
        *value = (uint8_t)(c - '0');
        return 1U;
    }

    if ((c >= 'A') && (c <= 'F'))
    {
        *value = (uint8_t)(c - 'A' + 10);
        return 1U;
    }

    if ((c >= 'a') && (c <= 'f'))
    {
        *value = (uint8_t)(c - 'a' + 10);
        return 1U;
    }

    return 0U;
}


static uint8_t Fw_ParseHexBytes(const char *text,
                                uint8_t *out,
                                uint32_t *out_len)
{
    size_t n;
    uint32_t i;

    if ((text == NULL) ||
        (out == NULL) ||
        (out_len == NULL))
    {
        return 0U;
    }

    n = strlen(text);

    if ((n == 0U) ||
        ((n & 1U) != 0U) ||
        (n > (FW_DATA_MAX_BYTES * 2U)))
    {
        return 0U;
    }

    *out_len = (uint32_t)(n / 2U);

    for (i = 0U; i < *out_len; i++)
    {
        uint8_t hi;
        uint8_t lo;

        if ((Fw_HexNibble(text[i * 2U], &hi) == 0U) ||
            (Fw_HexNibble(text[i * 2U + 1U], &lo) == 0U))
        {
            return 0U;
        }

        out[i] = (uint8_t)((hi << 4U) | lo);
    }

    return 1U;
}


static uint8_t Fw_TargetVectorValid(void)
{
    uint32_t app_msp;
    uint32_t app_reset;

    app_msp =
        *(volatile const uint32_t *)APP_TARGET_ADDRESS;

    app_reset =
        *(volatile const uint32_t *)(APP_TARGET_ADDRESS + 4U);

    if ((app_msp < 0x20000000UL) ||
        (app_msp > 0x20020000UL))
    {
        return 0U;
    }

    if ((app_reset & 1UL) == 0U)
    {
        return 0U;
    }

    app_reset &= ~1UL;

    if ((app_reset < APP_TARGET_ADDRESS) ||
        (app_reset >= APP_TARGET_END))
    {
        return 0U;
    }

    return 1U;
}


static uint8_t Fw_EraseTarget(uint32_t image_size)
{
    FLASH_EraseInitTypeDef erase_init;
    uint32_t page_error = 0U;
    uint32_t pages;
    HAL_StatusTypeDef status;
    HAL_StatusTypeDef lock_status;

    if ((image_size < 8U) || (image_size > FW_SLOT_SIZE))
    {
        return 0U;
    }

    pages = (image_size + FW_FLASH_PAGE_SIZE - 1U) / FW_FLASH_PAGE_SIZE;

    if ((pages == 0U) || (pages > 112U))
    {
        return 0U;
    }

    g_fw_diag_erase_bank = (uint32_t)APP_TARGET_BANK;
    g_fw_diag_erase_page = (uint32_t)APP_TARGET_FIRST_PAGE;
    g_fw_diag_erase_pages = pages;
    g_fw_diag_page_error = 0xFFFFFFFFUL;
    g_fw_diag_flash_error = 0U;
    g_fw_diag_hal_status = (uint32_t)HAL_ERROR;
    g_fw_diag_lock_status = (uint32_t)HAL_ERROR;
    g_fw_diag_stage = 50U;
    Fw_DiagSnapshotComms();

    status = HAL_FLASH_Unlock();
    g_fw_diag_hal_status = (uint32_t)status;
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;

    if (status != HAL_OK)
    {
        g_fw_diag_stage = 90U;
        Fw_DiagSnapshotComms();
        return 0U;
    }

    g_fw_diag_stage = 60U;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    memset(&erase_init, 0, sizeof(erase_init));
    erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_init.Banks = APP_TARGET_BANK;
    erase_init.Page = APP_TARGET_FIRST_PAGE;
    erase_init.NbPages = pages;

    g_fw_diag_stage = 70U;
    Fw_DiagSnapshotComms();

    status = HAL_FLASHEx_Erase(&erase_init, &page_error);

    g_fw_diag_hal_status = (uint32_t)status;
    g_fw_diag_page_error = page_error;
    g_fw_diag_flash_error = HAL_FLASH_GetError();
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;
    g_fw_diag_stage = 80U;

    lock_status = HAL_FLASH_Lock();
    g_fw_diag_lock_status = (uint32_t)lock_status;
    g_fw_diag_flash_sr = FLASH->SR;
    g_fw_diag_flash_cr = FLASH->CR;
    g_fw_diag_stage = 90U;
    Fw_DiagSnapshotComms();

    if ((status != HAL_OK) || (lock_status != HAL_OK))
    {
        return 0U;
    }

    return 1U;
}


static uint8_t Fw_ProgramData(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length)
{
    uint8_t padded[FW_DATA_MAX_BYTES];
    uint32_t programmed_length;
    uint32_t i;
    HAL_StatusTypeDef status = HAL_OK;

    if ((fw_update.active == 0U) ||
        (data == NULL) ||
        (length == 0U) ||
        (length > FW_DATA_MAX_BYTES))
    {
        return 0U;
    }

    if (offset != fw_update.bytes_received)
    {
        return 0U;
    }

    if ((offset + length) > fw_update.image_size)
    {
        return 0U;
    }

    /*
     * Every non-final packet must be exactly 32 bytes. The last packet may be
     * shorter; it is padded with erased-state 0xFF to a double-word boundary.
     */
    if (((offset + length) != fw_update.image_size) &&
        (length != FW_DATA_MAX_BYTES))
    {
        return 0U;
    }

    if ((offset & 7U) != 0U)
    {
        return 0U;
    }

    memset(padded, 0xFF, sizeof(padded));
    memcpy(padded, data, length);

    programmed_length = (length + 7U) & ~7U;

    if (HAL_FLASH_Unlock() != HAL_OK)
    {
        return 0U;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    for (i = 0U; i < programmed_length; i += 8U)
    {
        uint64_t data64;

        memcpy(&data64, &padded[i], sizeof(data64));

        status = HAL_FLASH_Program(
            FLASH_TYPEPROGRAM_DOUBLEWORD,
            fw_update.target_address + offset + i,
            data64);

        if (status != HAL_OK)
        {
            break;
        }
    }

    (void)HAL_FLASH_Lock();

    if (status != HAL_OK)
    {
        return 0U;
    }

    if (memcmp((const void *)(fw_update.target_address + offset),
               data,
               length) != 0)
    {
        return 0U;
    }

    fw_update.bytes_received += length;
    return 1U;
}

/* pw_transfer resource 2 reuses the proven inactive-slot writer. */
uint8_t PW_TransferFlash_IsActive(void)
{
    return fw_update.active;
}

uint32_t PW_TransferFlash_ExpectedOffset(void)
{
    return fw_update.bytes_received;
}

uint32_t PW_TransferFlash_ImageSize(void)
{
    return fw_update.image_size;
}

uint8_t PW_TransferFlash_Write(uint32_t offset,
                              const uint8_t *data,
                              uint32_t length)
{
    return Fw_ProgramData(offset, data, length);
}


static uint32_t Fw_TargetCrc32(uint32_t image_size)
{
    return TightenParams_Crc32(
        (const uint8_t *)APP_TARGET_ADDRESS,
        image_size);
}

#if defined(UART_FIRMWARE_TRANSFER)
#include "uart_firmware_transfer_port.inc"
#endif


static void Fw_EnterSafeState(void)
{
    tightening_start_request = 0U;
    tightening_stop_request = 0U;

    MotorControl_SetIdle();

    foc_enable = 0U;
    foc_id_ref_A = 0.0f;
    foc_iq_ref_A = 0.0f;

    PowerStage_Disable();
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
}


static void Fw_DiagSnapshotComms(void)
{
    g_fw_diag_uart_rx_dma_state = UART_RxDma_GetDmaState();
    g_fw_diag_uart_rx_dma_remaining = UART_RxDma_GetDmaRemaining();
    g_fw_diag_uart_rx_state = UART_RxDma_GetUartRxState();
    g_fw_diag_uart_cr3 = UART_RxDma_GetUartCr3();
    g_fw_diag_uart_rx_errors = UART_RxDma_GetErrorCount();
    g_fw_diag_uart_rx_last_error = UART_RxDma_GetLastError();
    g_fw_diag_uart_rx_restarts = UART_RxDma_GetRestartCount();
    g_fw_diag_uart_rx_restart_failures = UART_RxDma_GetRestartFailureCount();
    g_fw_diag_uart_tx_queued = (uint32_t)UART_Async_GetQueuedBytes();
    g_fw_diag_uart_tx_dropped = UART_Async_GetDroppedBytes();
    g_fw_diag_uart_tx_dma_errors = UART_Async_GetDmaErrorCount();

    if ((hlpuart1.hdmarx != NULL) && (hlpuart1.hdmarx->Instance != NULL))
    {
        g_fw_diag_uart_rx_dma_ccr = hlpuart1.hdmarx->Instance->CCR;
    }
    else
    {
        g_fw_diag_uart_rx_dma_ccr = 0U;
    }
}


static void Fw_ResetContext(void)
{
    memset(&fw_update, 0, sizeof(fw_update));
    fw_update.target_slot = APP_TARGET_SLOT;
    fw_update.target_address = APP_TARGET_ADDRESS;
}


static uint8_t BootHealth_IsCurrentTrial(void)
{
    BootMetaV2_t meta;

    if (BootMeta_ReadV3(&meta) == 0U)
    {
        return 0U;
    }

    /*
     * The current APP is a trial only while it is the pending slot and the
     * last confirmed slot is still the opposite image.
     */
    if ((meta.pending_slot == APP_THIS_SLOT) &&
        (meta.confirmed_slot != APP_THIS_SLOT))
    {
        return 1U;
    }

    return 0U;
}


static void Fw_SendStatus(uint32_t request_id)
{
    BootMetaV2_t meta;
    char msg[384];

    if (BootMeta_ReadV3(&meta) != 0U)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK FW CURRENT=%c TARGET=%c ACTIVE=%u RX=%lu SIZE=%lu "
            "EXPECT=0x%08lX CONFIRMED=%c PENDING=%c ATTEMPTS=%lu GEN=%lu "
            "HTRIAL=%u HOK=%u HSTABLE=%lums HELAPSED=%lums\r\n",
            (unsigned long)request_id,
            (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (unsigned int)fw_update.active,
            (unsigned long)fw_update.bytes_received,
            (unsigned long)fw_update.image_size,
            (unsigned long)fw_update.expected_crc32,
            (meta.confirmed_slot == BOOT_SLOT_A) ? 'A' : 'B',
            (meta.pending_slot == BOOT_SLOT_A) ? 'A' :
            (meta.pending_slot == BOOT_SLOT_B) ? 'B' : '-',
            (unsigned long)meta.attempts_left,
            (unsigned long)meta.generation,
            (unsigned int)boot_health_trial_active,
            (unsigned int)boot_health_last_sample_ok,
            (unsigned long)boot_health_stable_ms,
            (unsigned long)boot_health_elapsed_ms);
    }
    else
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK FW CURRENT=%c TARGET=%c ACTIVE=%u RX=%lu SIZE=%lu "
            "EXPECT=0x%08lX META=V1_OR_INVALID\r\n",
            (unsigned long)request_id,
            (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
            (unsigned int)fw_update.active,
            (unsigned long)fw_update.bytes_received,
            (unsigned long)fw_update.image_size,
            (unsigned long)fw_update.expected_crc32);
    }


}

static void TightenParams_PrintAll(uint32_t request_id)
{
    TightenParams_EmitAllFormatted(&recipe_state, request_id, Protocol_SendFormatted);
}


static uint8_t TightenParams_GetOne(
    uint32_t request_id,
    const char *name)
{
    char msg[128];
    uint32_t value = 0U;

    if (TightenParams_TryGet(&recipe_state.params, name, &value) !=
        TIGHTEN_PARAMS_OK)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "UNKNOWN_PARAM");
        return 0U;
    }

    (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK GET %s=%lu\r\n",
             (unsigned long)request_id, name, (unsigned long)value);
    return 1U;
}


static uint8_t TightenParams_SetOne(
    uint32_t request_id,
    const char *name,
    uint32_t value)
{
    char msg[144];
    TightenParamsResult_t result = TightenParams_TrySet(
        &recipe_state.params, name, value,
        ((Tightening_IsBusy() != 0U) ||
         (tightening_start_request != 0U)) ? 1U : 0U);

    if (result == TIGHTEN_PARAMS_BUSY)
    {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        return 0U;
    }
    if (result == TIGHTEN_PARAMS_OUT_OF_RANGE)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "VALUE_OUT_OF_RANGE");
        return 0U;
    }
    if (result != TIGHTEN_PARAMS_OK)
    {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                           "UNKNOWN_PARAM");
        return 0U;
    }

    recipe_state.dirty = 1U;
    (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK SET %s=%lu DIRTY=1\r\n",
             (unsigned long)request_id, name, (unsigned long)value);
    return 1U;
}


#if defined(TIGHTEN_SYNTHETIC_BENCH)
#include "tighten_synthetic_port.inc"
#endif
#if defined(FOC_PREEMPT_COMMIT_PROBE)
/* Cold task-only command dispatch: size codegen ONLY for this diagnostic,
 * no command/protocol behavior changes and no control-kernel option changes. */
__attribute__((optimize("Os")))
#endif
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

#if defined(ZERO_RETEST_BOOT)
    if (ZeroRetest_HandleCommand(request_id, cmd)) return;
#endif
#if defined(UART_FIRMWARE_TRANSFER)
    if (PW_UartFirmwareTransfer_Busy() &&
        (((strncmp(cmd, "FW ", 3U) == 0) && (strcmp(cmd, "FW STATUS") != 0)) ||
         (strncmp(cmd, "RPC ", 4U) == 0) ||
         ((strncmp(cmd, "XFER ", 5U) == 0) && (strncmp(cmd, "XFER ENGINE ", 12U) != 0))))
    {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "OFFICIAL_TRANSFER_OWNS_IAP");
        return;
    }
#endif
    if ((fw_update.active != 0U) &&
        (strncmp(cmd, "FW ", 3U) != 0) &&
        (strncmp(cmd, "RPC ", 4U) != 0) &&
        (strncmp(cmd, "XFER ", 5U) != 0) &&
        (strcmp(cmd, "PING") != 0) &&
        (strcmp(cmd, "STATUS") != 0) &&
        (strcmp(cmd, "SELFTEST STATUS") != 0) &&
        (strcmp(cmd, "EVT STATUS") != 0))
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BUSY,
            "FW_UPDATE_ACTIVE");
        return;
    }

    if (strcmp(cmd, "EVT STATUS") == 0)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK EVT1 PENDING=%lu CREATED=%lu SENT=%lu RETRY=%lu "
            "ACK=%lu GIVEUP=%lu TFULL=%lu NOROUTE=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)Protocol_ReliableEventPendingCount(),
            (unsigned long)g_protocol_reliable_event_created,
            (unsigned long)g_protocol_reliable_event_sent,
            (unsigned long)g_protocol_reliable_event_retried,
            (unsigned long)g_protocol_reliable_event_acked,
            (unsigned long)g_protocol_reliable_event_giveup,
            (unsigned long)g_protocol_reliable_event_table_full,
            (unsigned long)g_protocol_reliable_event_no_route);

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK EVT2 RX=%lu DUPRX=%lu ACKTX=%lu ACKTXFAIL=%lu "
            "BADEVT=%lu BADACK=%lu QDROP=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)g_protocol_reliable_event_rx,
            (unsigned long)g_protocol_reliable_event_rx_duplicate,
            (unsigned long)g_protocol_reliable_event_ack_tx,
            (unsigned long)g_protocol_reliable_event_ack_tx_fail,
            (unsigned long)g_protocol_reliable_event_bad_event,
            (unsigned long)g_protocol_reliable_event_bad_ack,
            (unsigned long)g_protocol_async_event_queue_drop);
    }
    else if (strcmp(cmd, "ESP PING") == 0)
    {
        char ping_payload[24];
        uint16_t router_seq = 0U;

        if ((protocol_esp_ping_uart_local == 0U) ||
            (request_id > 65535U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                               "ESP_PING_COM5_ID_1_65535_ONLY");
        }
        else if (protocol_esp_ping_pending != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "ESP_PING_PENDING");
        }
        else
        {
            snprintf(ping_payload, sizeof(ping_payload),
                     "%lu PING", (unsigned long)request_id);
            protocol_esp_ping_request_id = (uint16_t)request_id;
            protocol_esp_ping_deadline =
                xTaskGetTickCount() + pdMS_TO_TICKS(2000U);
            protocol_esp_ping_pending = 1U;
            if (Router_SendText(2U, ROUTER_PKT_PROTOCOL,
                                ping_payload, &router_seq) == 0U)
            {
                protocol_esp_ping_pending = 0U;
                Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                                   "ESP_NO_ROUTE");
            }
            else
            {
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu OK ESP PING SENT SEQ=%u\r\n",
                         (unsigned long)request_id,
                         (unsigned int)router_seq);
            }
        }
    }
    else if (strcmp(cmd, "ROUTER STATUS") == 0)
    {
        RouterStatus_t status;

        Router_GetStatus(&status);

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER NODE=%u RX=%lu LOCAL=%lu FWD=%lu TX=%lu "
            "DRX=%lu DTX=%lu NOROUTE=%lu TTL=%lu DUP=%lu LOOP=%lu "
            "PARSE=%lu RXQFULL=%lu LOCALQFULL=%lu NAGE=%lu RAGE=%lu "
            "RPLYOK=%lu RPLYFAIL=%lu\r\n",
            (unsigned long)request_id,
            (unsigned int)status.local_node_id,
            (unsigned long)status.rx_packets,
            (unsigned long)status.local_delivered,
            (unsigned long)status.forwarded,
            (unsigned long)status.tx_packets,
            (unsigned long)status.discovery_rx,
            (unsigned long)status.discovery_tx,
            (unsigned long)status.dropped_no_route,
            (unsigned long)status.dropped_ttl,
            (unsigned long)status.dropped_duplicate,
            (unsigned long)status.dropped_self_loop,
            (unsigned long)status.parse_errors,
            (unsigned long)status.rx_queue_full,
            (unsigned long)status.local_queue_full,
            (unsigned long)status.nodes_aged_out,
            (unsigned long)status.routes_aged_out,
            (unsigned long)protocol_reply_route_ok,
            (unsigned long)protocol_reply_route_fail);
    }
    else if (strcmp(cmd, "ROUTER NODES") == 0)
    {
        uint32_t count = Router_GetNodeCount();
        uint32_t idx;

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "OK ROUTER NODES COUNT=%lu" "\r\n",
            (unsigned long)request_id,
            (unsigned long)count);

        for (idx = 0U; idx < count; idx++)
        {
            RouterNodeInfo_t node;

            if (Router_GetNode(idx, &node) != 0U)
            {
                (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "NODE ID=%u PORT=%s AGE_MS=%lu RX=%lu FLAGS=0x%02X" "\r\n",
            (unsigned long)request_id,
            (unsigned int)node.node_id,
            Router_PortName(node.port),
            (unsigned long)node.age_ms,
            (unsigned long)node.rx_packets,
            (unsigned int)node.flags);
            }
        }

        Protocol_SendTaggedLine(request_id, "END ROUTER NODES");
    }
    else if (strcmp(cmd, "ROUTER ROUTES") == 0)
    {
        uint32_t count = Router_GetRouteCount();
        uint32_t idx;

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "OK ROUTER ROUTES COUNT=%lu" "\r\n",
            (unsigned long)request_id,
            (unsigned long)count);

        for (idx = 0U; idx < count; idx++)
        {
            RouterRouteInfo_t route;

            if (Router_GetRoute(idx, &route) != 0U)
            {
                (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "ROUTE DST=%u PORT=%s METRIC=%u AGE_MS=%lu FLAGS=0x%02X" "\r\n",
            (unsigned long)request_id,
            (unsigned int)route.destination,
            Router_PortName(route.port),
            (unsigned int)route.metric,
            (unsigned long)route.age_ms,
            (unsigned int)route.flags);
            }
        }

        Protocol_SendTaggedLine(request_id, "END ROUTER ROUTES");
    }
    else if (strcmp(cmd, "ROUTER DISCOVER") == 0)
    {
        uint16_t router_seq = 0U;

        if (Router_SendHello(&router_seq) == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_NOT_READY,
                "ROUTER_NO_TRANSPORT");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK ROUTER DISCOVER HELLO_SEQ=%u\r\n",
                (unsigned long)request_id,
                (unsigned int)router_seq);
        }
    }
    else if (strcmp(cmd, "ROUTER CONFIG") == 0)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER CONFIG HELLO_MS=%u NODE_TIMEOUT_MS=%u "
            "ROUTE_TIMEOUT_MS=%u DUP_WINDOW_MS=%u\r\n",
            (unsigned long)request_id,
            (unsigned int)ROUTER_DISCOVERY_INTERVAL_MS,
            (unsigned int)ROUTER_NODE_TIMEOUT_MS,
            (unsigned int)ROUTER_ROUTE_TIMEOUT_MS,
            (unsigned int)ROUTER_DUP_WINDOW_MS);
    }
    else if (strcmp(cmd, "ROUTER CLEAR") == 0)
    {
        Router_ClearDynamic();

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER CLEAR DYNAMIC=1\r\n",
            (unsigned long)request_id);
    }
    else if (strncmp(cmd, "ROUTER SEND ", 12U) == 0)
    {
        char *dst_text = cmd + 12U;
        char *dst_end;
        char *payload;
        unsigned long dst_ul;
        uint16_t router_seq = 0U;

        while ((*dst_text == ' ') || (*dst_text == '\t'))
        {
            dst_text++;
        }

        dst_ul = strtoul(dst_text, &dst_end, 10);

        if ((dst_end == dst_text) ||
            (dst_ul == 0UL) ||
            (dst_ul > 0xFFFFUL))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "ROUTER_BAD_DST");
        }
        else
        {
            payload = dst_end;
            while ((*payload == ' ') || (*payload == '\t'))
            {
                payload++;
            }

            if (*payload == '\0')
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "ROUTER_EMPTY_PAYLOAD");
            }
            else if (Router_SendText(
                         (uint16_t)dst_ul,
                         ROUTER_PKT_TEXT,
                         payload,
                         &router_seq) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_NOT_READY,
                    "ROUTER_NO_ROUTE");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK ROUTER SEND DST=%lu SEQ=%u\r\n",
                    (unsigned long)request_id,
                    dst_ul,
                    (unsigned int)router_seq);
            }
        }
    }
    else if ((strcmp(cmd, "MODBUS PROBE") == 0) ||
             (strncmp(cmd, "MODBUS PROBE ", 13U) == 0))
    {
        unsigned long baud = 9600UL;
        unsigned long slave = 255UL;
        unsigned long function = 1UL;
        unsigned long address = 0UL;
        char parity = 'N';
        char extra;
        int fields = 0;
        ModbusJob_t job = {0};

        if (strcmp(cmd, "MODBUS PROBE") != 0)
        {
            fields = sscanf(cmd, "MODBUS PROBE %lu %lu %lu %lu %c %c",
                            &baud, &slave, &function, &address,
                            &parity, &extra);
            if ((fields != 4) && (fields != 5))
            {
                Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                    "MODBUS_USE_PROBE_BAUD_ID_FC_ADDR_[N|E]");
                return;
            }
        }
        if ((baud > 115200UL) || ((slave > 247UL) && (slave != 255UL)) ||
            (function > 4UL) || (address > 65535UL) ||
            ((parity != 'N') && (parity != 'E')))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                "MODBUS_INVALID_ARGUMENT");
            return;
        }
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                "MOTOR_NOT_IDLE");
            return;
        }

        job.request_id = request_id;
        job.type = MODBUS_JOB_READ;
        job.baud = (uint32_t)baud;
        job.slave = (uint8_t)slave;
        job.function = (uint8_t)function;
        job.address = (uint16_t)address;
        job.even_parity = parity == 'E' ? 1U : 0U;
        if (Modbus_Enqueue(&job) == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "MODBUS_QUEUE_FULL");
        }
    }
    else if (strncmp(cmd, "MODBUS RELAY ", 13U) == 0)
    {
        unsigned long relay;
        char action[8];
        char extra;
        uint8_t on;
        ModbusJob_t job = {0};

        if (sscanf(cmd, "MODBUS RELAY %lu %7s %c",
                   &relay, action, &extra) != 2 ||
            (relay < 1UL) || (relay > 4UL) ||
            ((strcmp(action, "ON") != 0) &&
             (strcmp(action, "OFF") != 0)))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                "MODBUS_USE_RELAY_1_TO_4_ON_OR_OFF");
            return;
        }
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                "MOTOR_NOT_IDLE");
            return;
        }
        on = strcmp(action, "ON") == 0 ? 1U : 0U;
        job.request_id = request_id;
        job.type = MODBUS_JOB_RELAY;
        job.relay = (uint8_t)relay;
        job.on = on;
        if (Modbus_Enqueue(&job) == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "MODBUS_QUEUE_FULL");
        }
    }
    else if (strcmp(cmd, "MODBUS STATS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK MODBUS STATS SUB=%lu DONE=%lu FAIL=%lu FULL=%lu TIMEOUT=%lu CRC=%lu RQ=%lu CQ=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)modbus_submitted,
                 (unsigned long)modbus_completed,
                 (unsigned long)modbus_failed,
                 (unsigned long)modbus_queue_full,
                 (unsigned long)modbus_timeout,
                 (unsigned long)modbus_crc_error,
                 (unsigned long)uxQueueMessagesWaiting(modbus_request_queue),
                 (unsigned long)uxQueueMessagesWaiting(modbus_completion_queue));
    }
    else if (strcmp(cmd, "PING") == 0)
    {
        Protocol_SendTaggedLine(request_id, "OK PING PONG");
    }
    else if (strcmp(cmd, "HELP") == 0)
    {
        Protocol_SendTaggedLine(
            request_id,
            "OK HELP VERSION=2 PARAMS=1 KVS=1 RPC=1 ALLOC=1 LOG=1");
        Protocol_SendTaggedLine(request_id, "FORMAT <REQ_ID> <COMMAND>");
        Protocol_SendTaggedLine(request_id, "CMD PING");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS PROBE [BAUD ID FC ADDR [N|E]]");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS RELAY <1..4> <ON|OFF>");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS STATS");
        Protocol_SendTaggedLine(request_id, "CMD STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ENC DIAG");
        Protocol_SendTaggedLine(request_id, "CMD ENC SAMPLE (ANALOG SAFE ONLY)");
        Protocol_SendTaggedLine(request_id, "CMD SELFTEST STATUS");
        Protocol_SendTaggedLine(request_id, "CMD FAULT SNAPSHOT");
        Protocol_SendTaggedLine(request_id, "CMD FAULT FILTER");
#if defined(FOC_CURRENT_TREND4)
        Protocol_SendTaggedLine(request_id, "CMD FAULT SHADOW");
        Protocol_SendTaggedLine(request_id, "CMD FAULT TREND");
        Protocol_SendTaggedLine(request_id, "CMD OC SHADOW STATUS");
        Protocol_SendTaggedLine(request_id, "CMD OC FILTER STATUS");
#endif
        Protocol_SendTaggedLine(request_id, "CMD ANALOG SAFE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG SAFE STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG BOOT");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG LIVE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG VOLT");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG PAIR");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG TRIPLE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG PC5 TRIPLE");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER NODES");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER ROUTES");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER DISCOVER");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER CONFIG");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER CLEAR");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER SEND <DST> <TEXT>");
        Protocol_SendTaggedLine(request_id, "CMD ESP PING (COM5 ONLY)");
        Protocol_SendTaggedLine(request_id, "CMD EVT STATUS");
        Protocol_SendTaggedLine(request_id, "ROUTER TYPE4=EVENT TYPE5=EVENT_ACK");
        Protocol_SendTaggedLine(request_id, "CMD START");
        Protocol_SendTaggedLine(request_id, "CMD STOP");
        Protocol_SendTaggedLine(request_id, "CMD RESULT");
        Protocol_SendTaggedLine(request_id, "CMD GET PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD GET <PARAM>");
        Protocol_SendTaggedLine(request_id, "CMD SET <PARAM> <VALUE>");
        Protocol_SendTaggedLine(request_id, "CMD SAVE PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD LOAD PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD DEFAULT PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD KVS STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ALLOC STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ALLOC TEST");
        Protocol_SendTaggedLine(request_id, "CMD LOG STATUS");
        Protocol_SendTaggedLine(request_id, "CMD LOG DUMP");
        Protocol_SendTaggedLine(request_id, "CMD LOG CLEAR");
        Protocol_SendTaggedLine(request_id, "CMD LOG LEVEL <DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL>");
        Protocol_SendTaggedLine(request_id, "CMD LOG TEST <COUNT>");
        Protocol_SendTaggedLine(request_id, "CMD LOG TOKEN TEST <COUNT>");
        Protocol_SendTaggedLine(request_id, "CMD LOG ROUTER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD LOG SUBSCRIBERS");
        Protocol_SendTaggedLine(request_id, "CMD LOG SUBSCRIBE [NODE] <LEVEL> <SECONDS>");
        Protocol_SendTaggedLine(request_id, "CMD LOG UNSUBSCRIBE [NODE]");
        Protocol_SendTaggedLine(request_id, "CMD RPC INFO");
        Protocol_SendTaggedLine(request_id, "CMD RPC [CALL] <PW_RPC_PACKET_HEX>");
        Protocol_SendTaggedLine(request_id, "CMD XFER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD XFER RESET");
        Protocol_SendTaggedLine(request_id, "CMD BOOT STATUS");
        Protocol_SendTaggedLine(request_id, "CMD BOOT A");
        Protocol_SendTaggedLine(request_id, "CMD BOOT B");
        Protocol_SendTaggedLine(request_id, "CMD FW STATUS");
        Protocol_SendTaggedLine(request_id, "CMD FW CONFIRM");
        Protocol_SendTaggedLine(request_id, "CMD FW BEGIN <SIZE_DEC> <CRC32_HEX>");
        Protocol_SendTaggedLine(request_id, "CMD FW DATA <OFFSET_HEX> <HEX_BYTES>");
        Protocol_SendTaggedLine(request_id, "CMD FW END");
        Protocol_SendTaggedLine(request_id, "CMD FW ABORT");
        Protocol_SendTaggedLine(request_id, "INFO TRIAL=AUTO_CONFIRM_5S FAIL_RESET_12S");
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
        Protocol_SendTaggedLine(request_id, "ERR 109 FW_STATE");
        Protocol_SendTaggedLine(request_id, "ERR 110 FW_CRC");
        Protocol_SendTaggedLine(request_id, "ERR 111 FW_RANGE");
        Protocol_SendTaggedLine(request_id, "ERR 112 FW_SEQUENCE");
        Protocol_SendTaggedLine(request_id, "END HELP");
    }
    else if (strcmp(cmd, "STATUS") == 0)
    {
        Protocol_PrintStatus(request_id);
    }
    else if (strcmp(cmd, "ENC DIAG") == 0)
    {
#if defined(AS5047P_SPI_DMA)
        AsDmaStats dma_stats;
        AS5047P_DmaGetStats(&dma_stats);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DMA READS=%lu FAIL=%lu MAX_US=%lu TIMEOUT=%lu IO=%lu SCHED=%lu STALE=%lu ACTIVE=%lu ST=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_stats.attempts,
                 (unsigned long)dma_stats.failures, (unsigned long)dma_stats.max_elapsed_us,
                 (unsigned long)dma_stats.timeouts, (unsigned long)dma_stats.dma_errors,
                 (unsigned long)dma_stats.schedule_misses, (unsigned long)dma_stats.control_stale,
                 (unsigned long)dma_stats.periodic, (unsigned long)dma_stats.last_status);
        AsDmaFaultSnapshot dma_fault;
        AS5047P_DmaGetFaultSnapshot(&dma_fault);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SNAP VALID=%lu ST=%lu PH=%lu FR=%lu START=%lu NOW=%lu DUE=%lu GUARD=%lu IPSR=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.valid,
                 (unsigned long)dma_fault.status, (unsigned long)dma_fault.phase,
                 (unsigned long)dma_fault.frame, (unsigned long)dma_fault.started_us,
                 (unsigned long)dma_fault.now_us, (unsigned long)dma_fault.deadline_us,
                 (unsigned long)dma_fault.guard_us, (unsigned long)dma_fault.ipsr);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SPI SR=0x%08lX CR1=0x%08lX CR2=0x%08lX TIM_SR=0x%08lX TIM_DIER=0x%08lX\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.spi_sr,
                 (unsigned long)dma_fault.spi_cr1, (unsigned long)dma_fault.spi_cr2,
                 (unsigned long)dma_fault.tim_sr, (unsigned long)dma_fault.tim_dier);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DMAHW ISR=0x%08lX RX_NDTR=%lu TX_NDTR=%lu RX_CCR=0x%08lX TX_CCR=0x%08lX\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.dma_isr,
                 (unsigned long)dma_fault.rx_ndtr, (unsigned long)dma_fault.tx_ndtr,
                 (unsigned long)dma_fault.rx_ccr, (unsigned long)dma_fault.tx_ccr);
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC IRQ VALID=%lu NOW=%lu SR=0x%08lX DIER=0x%08lX CCR2=%lu LATE_US=%lu MAX_LATE_US=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.tim_entry_valid,
                 (unsigned long)dma_fault.tim_entry_us, (unsigned long)dma_fault.tim_entry_sr,
                 (unsigned long)dma_fault.tim_entry_dier, (unsigned long)dma_fault.tim_entry_ccr2,
                 (unsigned long)dma_fault.tim_entry_late_us,
                 (unsigned long)dma_fault.guard_max_late_us);
#endif
#endif
        uint32_t reads, failures, over_1ms, last_cycles, max_cycles;
        uint32_t stack_words, stack_samples;
        uint32_t cycles_per_us = SystemCoreClock / 1000000U;

        taskENTER_CRITICAL();
        reads = encoder_diag_reads;
        failures = encoder_diag_failures;
        over_1ms = encoder_diag_over_1ms;
        last_cycles = encoder_diag_last_cycles;
        max_cycles = encoder_diag_max_cycles;
        stack_words = motor_stack_min_words;
        stack_samples = motor_stack_samples;
        taskEXIT_CRITICAL();

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DIAG DWT=%u READS=%lu FAIL=%lu OVER1MS=%lu LAST_US=%lu MAX_US=%lu SAFE=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned int)encoder_diag_dwt_ready,
                 (unsigned long)reads, (unsigned long)failures,
                 (unsigned long)over_1ms,
                 (unsigned long)((cycles_per_us != 0U) ? last_cycles / cycles_per_us : 0U),
                 (unsigned long)((cycles_per_us != 0U) ? max_cycles / cycles_per_us : 0U),
                 (unsigned int)analog_safe_latched);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC STACK VALID=%u FREE_B=%lu SAMPLES=%lu SAFE_NOW=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned int)(stack_samples != 0U),
                 (unsigned long)((stack_samples != 0U) ? stack_words * sizeof(StackType_t) : 0U),
                 (unsigned long)stack_samples,
                 (unsigned int)analog_safe_latched);
    }
    else if (strcmp(cmd, "ENC SAMPLE") == 0)
    {
        uint16_t raw = 0U;
        HAL_StatusTypeDef status;
        uint32_t cycles_per_us = SystemCoreClock / 1000000U;

        if ((analog_safe_latched == 0U) ||
            (HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) != GPIO_PIN_RESET) ||
            ((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U) ||
            (foc_enable != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                               "ANALOG_SAFE_REQUIRED");
            return;
        }
        if (encoder_diag_dwt_ready == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                               "DWT_UNAVAILABLE");
            return;
        }

        status = AS5047P_ReadAngle(&raw);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SAMPLE HAL=%u RAW=%u US=%lu SAFE=1 SD=0 MOE=0 FOC=0\r\n",
                 (unsigned long)request_id, (unsigned int)status,
                 (unsigned int)raw,
                 (unsigned long)((cycles_per_us != 0U) ? encoder_diag_last_cycles / cycles_per_us : 0U));
    }
#if defined(ESP_NETWORK_OBSERVER)
    else if (strcmp(cmd, "NET STATUS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK NET RUN=%lu SEQ=%lu DROP=%lu CONTROL=LOCKED\r\n",
                 (unsigned long)request_id, (unsigned long)g_network_run,
                 (unsigned long)g_network_seq, (unsigned long)g_network_drop);
    }
#endif
    else if (strcmp(cmd, "SELFTEST STATUS") == 0)
    {
        Protocol_PrintSelftestStatus(request_id);
    }
    else if (strcmp(cmd, "FAULT SNAPSHOT") == 0)
    {
        if (foc_current_trip_snapshot.valid == 0U)
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK FAULT SNAPSHOT VALID=0 REASON=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned long)foc_fault_reason);
        }
        else
        {
            char snapshot_line[ROUTER_MAX_PAYLOAD + 1U];
            int n;
            ProtocolTxBuffer reply = {0};

            if (!ProtocolTxBuffer_Begin(&reply,
                    (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
                     g_uart_async_runtime_enable != 0U),
                    snapshot_line, sizeof(snapshot_line), UART_PROTOCOL_TX_TIMEOUT_MS))
                return; /* Preserve failed-enqueue semantics, no unsafe fallback. */
            __DMB();
            n = snprintf(reply.data, reply.capacity,
                         "%lu OK FAULT SNAPSHOT VALID=1 REASON=1 MS=%lu SEQ=%lu "
                         "UA=%u VA=%u UP=%u VP=%u U0=%u V0=%u "
                         "IU=%ld IV=%ld IW=%ld VB=%u VAGE=%lu VVALID=%u\r\n",
                         (unsigned long)request_id,
                         (unsigned long)foc_current_trip_snapshot.tick_ms,
                         (unsigned long)foc_current_trip_snapshot.adc_seq,
                         (unsigned int)foc_current_trip_snapshot.accepted_u,
                         (unsigned int)foc_current_trip_snapshot.accepted_v,
                         (unsigned int)foc_current_trip_snapshot.physical_u,
                         (unsigned int)foc_current_trip_snapshot.physical_v,
                         (unsigned int)foc_current_trip_snapshot.zero_u,
                         (unsigned int)foc_current_trip_snapshot.zero_v,
                         (long)foc_current_trip_snapshot.iu_mA,
                         (long)foc_current_trip_snapshot.iv_mA,
                         (long)foc_current_trip_snapshot.iw_mA,
                         (unsigned int)foc_current_trip_snapshot.vbus_raw,
                         (unsigned long)foc_current_trip_snapshot.vbus_age_ms,
                         (unsigned int)foc_current_trip_snapshot.vbus_valid);
            if ((n < 0) || (n > (int)ROUTER_MAX_PAYLOAD))
            {
                ProtocolTxBuffer_Cancel(&reply);
                Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG,
                                   "FAULT_SNAPSHOT_TOO_LONG");
            }
            else
            {
                (void)ProtocolTxBuffer_Commit(&reply, n, Protocol_SendString);
            }
        }
    }
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow_protocol.inc"
#endif
    else if (strcmp(cmd, "FAULT FILTER") == 0)
    {
        if (foc_current_trip_snapshot.valid == 0U)
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK FAULT FILTER VALID=0 REASON=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned long)foc_fault_reason);
        }
        else
        {
            char filter_line[ROUTER_MAX_PAYLOAD + 3U];
            int n;
            ProtocolTxBuffer reply = {0};

            if (!ProtocolTxBuffer_Begin(&reply,
                    (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
                     g_uart_async_runtime_enable != 0U),
                    filter_line, sizeof(filter_line), UART_PROTOCOL_TX_TIMEOUT_MS))
                return; /* Preserve failed-enqueue semantics, no unsafe fallback. */
            __DMB();
            n = snprintf(reply.data, reply.capacity,
                     "%lu OK FAULT FILTER VALID=1 ON=%u MC=%u VC=%lu RC=%lu RS=%lu BAD=%ld "
                     "MU0=%u MU1=%u MU2=%u MV0=%u MV1=%u MV2=%u VS=%lu VE=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned int)foc_current_trip_snapshot.filter_on,
                     (unsigned int)foc_current_trip_snapshot.median_count,
                     (unsigned long)foc_current_trip_snapshot.current_valid_count,
                     (unsigned long)foc_current_trip_snapshot.current_reject_count,
                     (unsigned long)foc_current_trip_snapshot.current_reject_streak,
                     (long)foc_current_trip_snapshot.last_rejected_step,
                     (unsigned int)foc_current_trip_snapshot.median_u[0],
                     (unsigned int)foc_current_trip_snapshot.median_u[1],
                     (unsigned int)foc_current_trip_snapshot.median_u[2],
                     (unsigned int)foc_current_trip_snapshot.median_v[0],
                     (unsigned int)foc_current_trip_snapshot.median_v[1],
                     (unsigned int)foc_current_trip_snapshot.median_v[2],
                     (unsigned long)foc_current_trip_snapshot.analog_sample_count,
                     (unsigned long)foc_current_trip_snapshot.analog_error_count);
            if ((n < 0) || (n > (int)ROUTER_MAX_PAYLOAD))
            {
                ProtocolTxBuffer_Cancel(&reply);
                Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG,
                                   "FAULT_FILTER_TOO_LONG");
            }
            else
            {
                (void)ProtocolTxBuffer_Commit(&reply, n, Protocol_SendString);
            }
        }
    }
#if defined(FOC_ADC_WINDOW)
    else if (strcmp(cmd, "ADC TIMING") == 0 || strcmp(cmd, "ADC WINDOW") == 0 || strcmp(cmd, "ADC BUFFER") == 0 || strcmp(cmd, "ADC COMMIT") == 0 ||
             strcmp(cmd, "ADC SPREAD U") == 0 || strcmp(cmd, "ADC SPREAD V") == 0
#if defined(FOC_PWM_BOUNDARY_TRACE) || defined(FOC_PWM_BOUNDARY_LITE)
             || strncmp(cmd, "ADC BOUNDARY", 12U) == 0
#endif
             )
    {
        if (FocAdcTiming_Format(cmd, msg, sizeof(msg)))
            Protocol_SendTaggedLine(request_id, msg);
        else
            Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG, "ADC_DIAG_TOO_LONG");
    }
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    else if (strncmp(cmd,"MOTOR TEST ",11U)==0
#if !defined(FOC_LATEST_ORIGINAL_FSM)
             || strcmp(cmd,"STOP")==0
#endif
             )
    {
        if (protocol_reply_route_active || !protocol_esp_ping_uart_local) {
            Protocol_SendError(request_id,PROTO_ERR_FW_STATE,"LOCAL_CONSOLE_ONLY"); return;
        }
        ProtectedLoop_Command(cmd,msg,sizeof(msg));
        Protocol_SendTaggedLine(request_id,msg);
    }
#endif
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    else if (strncmp(cmd, "BENCH CHAIN ", 12U) == 0)
    {
        if (protocol_reply_route_active || !protocol_esp_ping_uart_local)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "LOCAL_CONSOLE_ONLY");
            return;
        }
        ControlChain_Command(cmd, request_id, msg, sizeof(msg));
        Protocol_SendTaggedLine(request_id, msg);
    }
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    else if (strcmp(cmd, "BENCH RUN") == 0 || strcmp(cmd, "BENCH STOP") == 0 ||
             strcmp(cmd, "BENCH STATUS") == 0 || strcmp(cmd, "BENCH STACK") == 0 ||
             strcmp(cmd, "BENCH ZERO") == 0
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
             || strcmp(cmd, "BENCH PROTECTION") == 0
             || strcmp(cmd, "BENCH PROTECTION TIMING") == 0
             || strcmp(cmd, "BENCH PROTECTION FAULT") == 0
             || strcmp(cmd, "BENCH PROTECTION TEST TIMEOUT") == 0
#endif
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
             || strcmp(cmd, "BENCH ZERO FILTER") == 0
#endif
             )
    {
        if (protocol_reply_route_active != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "LOCAL_CONSOLE_ONLY");
            return;
        }
        if (strcmp(cmd, "BENCH RUN") == 0)
        {
#if defined(TIGHTEN_SYNTHETIC_BENCH)
            if (synthetic_busy != 0U)
            {
                Protocol_SendError(request_id, PROTO_ERR_BUSY, "SIM_BUSY");
                return;
            }
#endif
            if (BootHealth_IsCurrentTrial() != 0U || !IsolatedBench_Start(60000U))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "ISOLATED_BENCH_REJECTED");
                return;
            }
        }
        if (strcmp(cmd, "BENCH STOP") == 0) IsolatedBench_Stop(0U);
        if (strcmp(cmd, "BENCH STACK") == 0) IsolatedBench_Stacks(msg, sizeof(msg));
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        else if (strncmp(cmd, "BENCH PROTECTION", 16U) == 0)
        {
            char protection_message[320];
            if (strcmp(cmd, "BENCH PROTECTION TEST TIMEOUT") == 0) {
                if (BootHealth_IsCurrentTrial() || !FocFeedbackBinding_TestTimeout()) {
                    Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "TIMEOUT_TEST_REJECTED");
                    return;
                }
                Protocol_SendTaggedLine(request_id,
                    "OK BENCH PROTECTION TEST TIMEOUT REQUESTED=1 MOTOR_QUALIFIED=0");
                return;
            }
            if (strcmp(cmd, "BENCH PROTECTION TIMING") == 0)
                FocFeedbackBinding_TimingFormat(protection_message, sizeof(protection_message));
            else if (strcmp(cmd, "BENCH PROTECTION FAULT") == 0)
                FocFeedbackBinding_FaultFormat(protection_message, sizeof(protection_message));
            else FocFeedbackBinding_Format(protection_message, sizeof(protection_message));
            Protocol_SendTaggedLine(request_id, protection_message);
            return;
        }
#endif
        else if (strcmp(cmd, "BENCH ZERO") == 0) IsolatedZero_Format(msg, sizeof(msg));
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
        else if (strcmp(cmd, "BENCH ZERO FILTER") == 0)
        {
            char filter_message[320];
            IsolatedZero_FilterFormat(filter_message, sizeof(filter_message));
            Protocol_SendTaggedLine(request_id, filter_message);
            return;
        }
#endif
        else IsolatedBench_Format(msg, sizeof(msg));
        Protocol_SendTaggedLine(request_id, msg);
    }
#endif
#if defined(TIGHTEN_SYNTHETIC_BENCH)
    else if (strncmp(cmd, "SIM ", 4U) == 0)
    {
        Synthetic_Command(request_id, cmd, msg, sizeof(msg));
    }
#endif
    else if (strcmp(cmd, "ANALOG SAFE STATUS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG SAFE LATCHED=%u SD=%u MOE=%u FOC=%u RESET_TO_EXIT=1\r\n",
                 (unsigned long)request_id,
                 (unsigned int)analog_safe_latched,
                 (unsigned int)(HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port,
                                                DRIVER_SD_Pin) == GPIO_PIN_SET),
                 (unsigned int)((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U),
                 (unsigned int)foc_enable);
    }
    else if (strcmp(cmd, "ANALOG SAFE") == 0)
    {
#if defined(FOC_PROTECTED_CLOSED_LOOP)
        ProtectedLoop_Shutdown();
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedBench_Stop(0U);
#endif
        if (analog_safe_latched == 0U)
        {
            BootMetaV2_t safe_meta;

            if ((BootMeta_ReadV3(&safe_meta) == 0U) ||
                (safe_meta.confirmed_slot != APP_THIS_SLOT) ||
                (BootHealth_IsCurrentTrial() != 0U))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE,
                                   "SLOT_NOT_CONFIRMED");
                return;
            }
            if ((Tightening_IsBusy() != 0U) ||
                (tightening_start_request != 0U) ||
                (motor_control_mode != MOTOR_MODE_IDLE))
            {
                Protocol_SendError(request_id, PROTO_ERR_BUSY,
                                   "MOTOR_BUSY");
                return;
            }
            if ((encoder_valid == 0U) ||
                (!isfinite(encoder_speed_rpm)) ||
                (fabsf(encoder_speed_rpm) >= ANALOG_SAFE_MAX_RPM))
            {
                Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING,
                                   "ROTOR_NOT_STATIONARY");
                return;
            }

            /* Disable the gate before stopping the timer. No ordinary
             * command can clear this latch or re-enable the bridge. */
            PowerStage_Disable();
            foc_enable = 0U;
            analog_safe_latched = 1U;
            MotorControl_SetIdle();
            PWM_StopAll();
            __HAL_TIM_MOE_DISABLE(&htim1);
        }

        if ((HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port,
                              DRIVER_SD_Pin) != GPIO_PIN_RESET) ||
            ((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_FAULT,
                               "SAFE_OUTPUT_VERIFY_FAILED");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1\r\n",
                     (unsigned long)request_id);
        }
    }
    else if (strcmp(cmd, "ANALOG BOOT") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG BOOT VALID=%u PC4_RAW=%u PC5_RAW=%u ADC=ADC2 LIVE=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)analog_boot_valid,
                 (unsigned int)analog_boot_pc4_raw,
                 (unsigned int)analog_boot_pc5_raw);
    }
    else if (strcmp(cmd, "ANALOG LIVE") == 0)
    {
        uint32_t count = analog_live_sample_count;
        uint32_t age_ms = (count != 0U)
                            ? (HAL_GetTick() - analog_live_last_tick_ms)
                            : UINT32_MAX;
        uint8_t fresh = (analog_live_valid != 0U) &&
                        (age_ms <= ANALOG_LIVE_FRESH_MS);

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG LIVE VALID=%u PC4_RAW=%u PC5_RAW=%u AGE_MS=%lu SAMPLES=%lu ERRORS=%lu ADC=ADC2 IDLE_ONLY=1\r\n",
                 (unsigned long)request_id,
                 (unsigned int)fresh,
                 (unsigned int)analog_live_pc4_raw,
                 (unsigned int)analog_live_pc5_raw,
                 (unsigned long)age_ms,
                 (unsigned long)count,
                 (unsigned long)analog_live_error_count);
    }
    else if (strcmp(cmd, "ANALOG VOLT") == 0)
    {
        uint32_t age_ms = (analog_live_sample_count != 0U)
                            ? (HAL_GetTick() - analog_live_last_tick_ms)
                            : UINT32_MAX;
        uint8_t valid = (analog_live_valid != 0U) &&
                        (analog_vdda_boot_valid != 0U) &&
                        (age_ms <= ANALOG_LIVE_FRESH_MS);
        uint32_t vbus_est_mv = 0U;
        uint32_t vtemp_mv = 0U;

        if (valid != 0U)
        {
            vbus_est_mv = (uint32_t)
                (((uint64_t)analog_live_pc4_raw *
                  (uint64_t)analog_vdda_boot_mv *
                  ANALOG_VBUS_DIVIDER + (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
            vtemp_mv = (uint32_t)
                (((uint64_t)analog_live_pc5_raw *
                  (uint64_t)analog_vdda_boot_mv +
                  (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
        }

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG VOLT VALID=%u VBUS_EST_MV=%lu VTEMP_MV=%lu VDDA_BOOT_MV=%u VREF_RAW=%u AGE_MS=%lu DIV=25 PROTECT=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)valid,
                 (unsigned long)vbus_est_mv,
                 (unsigned long)vtemp_mv,
                 (unsigned int)analog_vdda_boot_mv,
                 (unsigned int)analog_vref_boot_raw,
                 (unsigned long)age_ms);
    }
    else if (strcmp(cmd, "ANALOG PAIR") == 0)
    {
        AnalogPairDiag_t pair;

        taskENTER_CRITICAL();
        pair = analog_pair_diag;
        taskEXIT_CRITICAL();
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG PAIR VALID=%u LATCHED=%u LAST1=%u LAST2=%u "
                 "PEAK1=%u PEAK1_2=%u PEAK2=%u PEAK2_1=%u COUNT=%lu ERR=%lu "
                 "ADC=ADC2 PC4=CH5 PROTECT=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)(pair.count != 0U),
                 (unsigned int)analog_safe_latched,
                 (unsigned int)pair.last_first,
                 (unsigned int)pair.last_second,
                 (unsigned int)pair.peak_first,
                 (unsigned int)pair.peak_first_second,
                 (unsigned int)pair.peak_second,
                 (unsigned int)pair.peak_second_first,
                 (unsigned long)pair.count,
                 (unsigned long)pair.errors);
    }
    else if ((strcmp(cmd, "ANALOG TRIPLE") == 0) ||
             (strcmp(cmd, "ANALOG PC5 TRIPLE") == 0))
    {
        AnalogTripleDiag_t triple;
        uint8_t pc5_selected = (strcmp(cmd, "ANALOG PC5 TRIPLE") == 0);
        uint32_t age_ms;
        uint8_t valid;
        uint32_t median_mv = 0U;

        taskENTER_CRITICAL();
        triple = (pc5_selected != 0U) ? analog_pc5_triple_diag : analog_triple_diag;
        taskEXIT_CRITICAL();
        age_ms = (triple.count != 0U)
                     ? (HAL_GetTick() - triple.last_tick_ms)
                     : UINT32_MAX;
        valid = (analog_safe_latched != 0U) &&
                (analog_vdda_boot_valid != 0U) &&
                (triple.count != 0U) &&
                (age_ms <= ANALOG_LIVE_FRESH_MS);
        if (valid != 0U)
        {
            median_mv = (uint32_t)
                (((uint64_t)triple.last_median *
                  (uint64_t)analog_vdda_boot_mv *
                  (pc5_selected != 0U ? 1U : ANALOG_VBUS_DIVIDER) +
                  (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
        }
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG %sTRIPLE V=%u R=%u,%u,%u M=%u MV=%lu "
                 "PR=%u,%u,%u PM=%u,%u,%u SP=%u D=%lu N=%lu E=%lu\r\n",
                 (unsigned long)request_id,
                 (pc5_selected != 0U) ? "PC5 " : "",
                 (unsigned int)valid,
                 (unsigned int)triple.last_first,
                 (unsigned int)triple.last_second,
                 (unsigned int)triple.last_third,
                 (unsigned int)triple.last_median,
                 (unsigned long)median_mv,
                 (unsigned int)triple.peak_raw_first,
                 (unsigned int)triple.peak_raw_second,
                 (unsigned int)triple.peak_raw_third,
                 (unsigned int)triple.peak_median_first,
                 (unsigned int)triple.peak_median_second,
                 (unsigned int)triple.peak_median_third,
                 (unsigned int)triple.max_spread,
                 (unsigned long)triple.disagree_count,
                 (unsigned long)triple.count,
                 (unsigned long)triple.errors);
    }
    else if (strcmp(cmd, "KVS STATUS") == 0)
    {
        PW_KvsDiagnostics_t diagnostics;

        PW_Kvs_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK KVS READY=%lu ENTRIES=%lu TXN=%lu REDUNDANCY=%lu WRITABLE=%lu INUSE=%lu RECLAIM=%lu ERASES=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.initialized,
            (unsigned long)diagnostics.entries,
            (unsigned long)diagnostics.transaction_count,
            (unsigned long)diagnostics.redundancy,
            (unsigned long)diagnostics.writable_bytes,
            (unsigned long)diagnostics.in_use_bytes,
            (unsigned long)diagnostics.reclaimable_bytes,
            (unsigned long)diagnostics.sector_erase_count);
    }
    else if ((strcmp(cmd, "ALLOC STATUS") == 0) ||
             (strcmp(cmd, "ALLOC TEST") == 0))
    {
        PW_AllocatorDiagnostics_t diagnostics;

        if (strcmp(cmd, "ALLOC TEST") == 0)
        {
            (void)PW_Allocator_RunSelfTest();
        }
        PW_Allocator_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ALLOC BACKEND=FREERTOS_HEAP4 FREE=%lu MIN=%lu PASS=%lu ALLOCS=%lu BEFORE=%lu LOW=%lu AFTER=%lu ISR=FORBIDDEN HYBRID=%lu LIVE=%lu OBJECTS=%lu PEAK=%lu FAIL=%lu CTX=%lu UART=%lu LOGINDEX=%lu TEMP=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.free_bytes,
            (unsigned long)diagnostics.minimum_ever_free_bytes,
            (unsigned long)diagnostics.last_test_passed,
            (unsigned long)diagnostics.last_test_allocations,
            (unsigned long)diagnostics.last_test_before_bytes,
            (unsigned long)diagnostics.last_test_low_bytes,
            (unsigned long)diagnostics.last_test_after_bytes,
            (unsigned long)diagnostics.hybrid_enabled,
            (unsigned long)diagnostics.managed.live_bytes,
            (unsigned long)diagnostics.managed.live_objects,
            (unsigned long)diagnostics.managed.peak_bytes,
            (unsigned long)diagnostics.managed.allocation_failures,
            (unsigned long)diagnostics.managed.context_rejections,
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_UART],
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_LOG_SNAPSHOT],
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_TEMP]);
    }
    else if (strcmp(cmd, "LOG STATUS") == 0)
    {
        PW_LogDiagnostics_t diagnostics;

        PW_Log_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK LOG READY=%lu LEVEL=%s QUEUED=%lu CAP=%lu HIST=%lu SEQ=%lu ENQ=%lu SENT=%lu DROP_FULL=%lu DROP_UART=%lu DROP_ISR=%lu FILTERED=%lu HIGH_WATER=%lu TOK=%lu TBIN=%lu TB64=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.ready,
            PW_Log_LevelName((int)diagnostics.level),
            (unsigned long)diagnostics.queued,
            (unsigned long)diagnostics.capacity,
            (unsigned long)diagnostics.history_count,
            (unsigned long)diagnostics.sequence,
            (unsigned long)diagnostics.enqueued,
            (unsigned long)diagnostics.sent,
            (unsigned long)diagnostics.dropped_full,
            (unsigned long)diagnostics.dropped_uart,
            (unsigned long)diagnostics.dropped_isr,
            (unsigned long)diagnostics.filtered,
            (unsigned long)diagnostics.high_water,
            (unsigned long)diagnostics.tokenized,
            (unsigned long)diagnostics.token_binary_bytes,
            (unsigned long)diagnostics.token_base64_bytes);
    }
    else if (strcmp(cmd, "LOG ROUTER STATUS") == 0)
    {
        PW_LogRouterDiagnostics_t diagnostics;

        PW_LogRouter_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(msg,
                 sizeof(msg),
                 "%lu OK LOG ROUTER READY=%lu SUBS=%lu QUEUED=%lu CAP=%lu CAPTURED=%lu DROP=%lu SENT=%lu ROUTE_FAIL=%lu LEVEL_FILTER=%lu EXPIRED=%lu REMOTE_RX=%lu TYPE=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned long)diagnostics.ready,
                 (unsigned long)diagnostics.subscribers,
                 (unsigned long)diagnostics.queued,
                 (unsigned long)diagnostics.queue_capacity,
                 (unsigned long)diagnostics.captured,
                 (unsigned long)diagnostics.queue_dropped,
                 (unsigned long)diagnostics.routed_sent,
                 (unsigned long)diagnostics.route_failed,
                 (unsigned long)diagnostics.level_filtered,
                 (unsigned long)diagnostics.expired,
                 (unsigned long)diagnostics.remote_received,
                 (unsigned int)PW_LOG_ROUTER_PACKET_TYPE);
    }
    else if (strcmp(cmd, "LOG SUBSCRIBERS") == 0)
    {
        PW_LogRouterDiagnostics_t diagnostics;
        uint32_t i;

        PW_LogRouter_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK LOG SUBSCRIBERS COUNT=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)diagnostics.subscribers);
        for (i = 0U; i < diagnostics.subscribers; i++)
        {
            PW_LogRouterSubscriber_t subscriber;
            if (PW_LogRouter_GetSubscriber(i, &subscriber) != 0)
            {
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu LOG SUB NODE=%u LEVEL=%s REMAIN_MS=%lu\r\n",
                         (unsigned long)request_id,
                         (unsigned int)subscriber.node_id,
                         PW_Log_LevelName((int)subscriber.min_level),
                         (unsigned long)subscriber.remaining_ms);
            }
        }
        Protocol_SendTaggedLine(request_id, "OK LOG SUBSCRIBERS END");
    }
    else if (strncmp(cmd, "LOG SUBSCRIBE ", 14U) == 0)
    {
        unsigned long node = 0UL;
        unsigned long seconds = 0UL;
        char level_text[16] = {0};
        char extra;
        int fields;
        int level = 0;

        if (protocol_reply_route_active != 0U)
        {
            node = protocol_reply_route_dst;
            fields = sscanf(cmd + 14U, "%15s %lu %c",
                            level_text, &seconds, &extra);
            fields = (fields == 2) ? 3 : 0;
        }
        else
        {
            fields = sscanf(cmd + 14U, "%lu %15s %lu %c",
                            &node, level_text, &seconds, &extra);
        }

        if (strcmp(level_text, "DEBUG") == 0) level = PW_LOG_RUNTIME_DEBUG;
        else if (strcmp(level_text, "INFO") == 0) level = PW_LOG_RUNTIME_INFO;
        else if (strcmp(level_text, "WARN") == 0) level = PW_LOG_RUNTIME_WARN;
        else if (strcmp(level_text, "ERROR") == 0) level = PW_LOG_RUNTIME_ERROR;
        else if (strcmp(level_text, "CRITICAL") == 0) level = PW_LOG_RUNTIME_CRITICAL;
        else if (strcmp(level_text, "FATAL") == 0) level = PW_LOG_RUNTIME_FATAL;

        if ((fields != 3) || (node > 0xFFFEUL) ||
            (level == 0) || (seconds == 0UL) || (seconds > 3600UL) ||
            (PW_LogRouter_Subscribe((uint16_t)node, level,
                                    (uint32_t)seconds) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_SUBSCRIBE");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK LOG SUBSCRIBE NODE=%lu LEVEL=%s TTL=%lus TYPE=%u\r\n",
                     (unsigned long)request_id,
                     node,
                     PW_Log_LevelName(level),
                     seconds,
                     (unsigned int)PW_LOG_ROUTER_PACKET_TYPE);
        }
    }
    else if ((strcmp(cmd, "LOG UNSUBSCRIBE") == 0) ||
             (strncmp(cmd, "LOG UNSUBSCRIBE ", 16U) == 0))
    {
        unsigned long node = 0UL;
        char extra;
        int valid = 0;

        if ((protocol_reply_route_active != 0U) &&
            (strcmp(cmd, "LOG UNSUBSCRIBE") == 0))
        {
            node = protocol_reply_route_dst;
            valid = 1;
        }
        else if ((protocol_reply_route_active == 0U) &&
                 (sscanf(cmd + 16U, "%lu %c", &node, &extra) == 1) &&
                 (node <= 0xFFFEUL))
        {
            valid = 1;
        }

        if ((valid == 0) || (PW_LogRouter_Unsubscribe((uint16_t)node) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_UNSUBSCRIBE");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK LOG UNSUBSCRIBE NODE=%lu\r\n",
                     (unsigned long)request_id, node);
        }
    }
    else if (strcmp(cmd, "LOG DUMP") == 0)
    {
        uint32_t dumped;

        Protocol_SendTaggedLine(request_id, "OK LOG DUMP BEGIN");
        dumped = PW_Log_Dump();
        (void)Protocol_SendFormatted(msg,
                 sizeof(msg),
                 "%lu OK LOG DUMP END SENT=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)dumped);
    }
    else if (strcmp(cmd, "LOG CLEAR") == 0)
    {
        PW_Log_Clear();
        Protocol_SendTaggedLine(request_id, "OK LOG CLEARED");
    }
    else if (strncmp(cmd, "LOG LEVEL ", 10U) == 0)
    {
        int level = 0;
        const char *level_text = cmd + 10U;

        if (strcmp(level_text, "DEBUG") == 0) level = PW_LOG_RUNTIME_DEBUG;
        else if (strcmp(level_text, "INFO") == 0) level = PW_LOG_RUNTIME_INFO;
        else if (strcmp(level_text, "WARN") == 0) level = PW_LOG_RUNTIME_WARN;
        else if (strcmp(level_text, "ERROR") == 0) level = PW_LOG_RUNTIME_ERROR;
        else if (strcmp(level_text, "CRITICAL") == 0) level = PW_LOG_RUNTIME_CRITICAL;
        else if (strcmp(level_text, "FATAL") == 0) level = PW_LOG_RUNTIME_FATAL;

        if ((level == 0) || (PW_Log_SetLevel(level) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_LEVEL");
        }
        else
        {
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG LEVEL=%s\r\n",
                     (unsigned long)request_id,
                     PW_Log_LevelName(level));
        }
    }
    else if (strncmp(cmd, "LOG TEST ", 9U) == 0)
    {
        char *test_end;
        unsigned long requested = strtoul(cmd + 9U, &test_end, 10);

        if ((test_end == (cmd + 9U)) || (*test_end != '\0') ||
            (requested == 0UL) || (requested > 1000UL))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_TEST_COUNT");
        }
        else
        {
            uint32_t accepted = PW_Log_TestBurst((uint32_t)requested);
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG TEST REQUESTED=%lu ACCEPTED=%lu NOT_ENQUEUED=%lu\r\n",
                     (unsigned long)request_id,
                     requested,
                     (unsigned long)accepted,
                     (unsigned long)((uint32_t)requested - accepted));
        }
    }
    else if (strncmp(cmd, "LOG TOKEN TEST ", 15U) == 0)
    {
        char *test_end;
        unsigned long requested = strtoul(cmd + 15U, &test_end, 10);

        if ((test_end == (cmd + 15U)) || (*test_end != '\0') ||
            (requested == 0UL) || (requested > 1000UL))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_TOKEN_COUNT");
        }
        else
        {
            uint32_t accepted = PW_Log_TokenizedTestBurst((uint32_t)requested);
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG TOKEN TEST REQUESTED=%lu ACCEPTED=%lu NOT_ENQUEUED=%lu FORMAT=PWT_BASE64\r\n",
                     (unsigned long)request_id,
                     requested,
                     (unsigned long)accepted,
                     (unsigned long)((uint32_t)requested - accepted));
        }
    }
    else if (strncmp(cmd, "RPC ", 4U) == 0)
    {
        PW_Rpc_HandleCommand(request_id, cmd + 4U);
    }
    else if (strncmp(cmd, "XFER ", 5U) == 0)
    {
#if defined(UART_FIRMWARE_TRANSFER)
        if (strncmp(cmd, "XFER ENGINE ", 12U) == 0)
            UartFirmwareTransfer_Command(request_id, cmd + 12U);
        else
#endif
        PW_Transfer_HandleCommand(request_id, cmd + 5U);
    }
    else if (strcmp(cmd, "BOOT STATUS") == 0)
    {
        BootMetaV2_t meta;

        if (BootMeta_ReadV3(&meta) != 0U)
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK BOOT V=3 CONFIRMED=%c PENDING=%c ATTEMPTS=%lu GEN=%lu\r\n",
                (unsigned long)request_id,
                (meta.confirmed_slot == BOOT_SLOT_A) ? 'A' : 'B',
                (meta.pending_slot == BOOT_SLOT_A) ? 'A' :
                (meta.pending_slot == BOOT_SLOT_B) ? 'B' : '-',
                (unsigned long)meta.attempts_left,
                (unsigned long)meta.generation);
        }
        else
        {
            BootMetaV1_t old_meta;

            if (BootMeta_ReadV1(&old_meta) != 0U)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK BOOT V=1 ACTIVE=%c\r\n",
                    (unsigned long)request_id,
                    (old_meta.active_slot == BOOT_SLOT_A) ? 'A' : 'B');
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK BOOT META_VALID=0 DEFAULT=A\r\n",
                    (unsigned long)request_id);
            }
        }
    }
    else if ((strcmp(cmd, "BOOT A") == 0) ||
             (strcmp(cmd, "BOOT B") == 0))
    {
        uint32_t slot =
            (strcmp(cmd, "BOOT A") == 0) ?
            BOOT_SLOT_A :
            BOOT_SLOT_B;

        if (BootHealth_IsCurrentTrial() != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "TRIAL_NOT_CONFIRMED");
        }
        else if ((fw_update.active != 0U) ||
                 (Tightening_IsBusy() != 0U) ||
                 (tightening_start_request != 0U) ||
                 (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BUSY,
                "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_ROTOR_MOVING,
                "ROTOR_MOVING");
        }
        else if (BootMeta_SaveSlot(slot) == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FLASH,
                "MAILBOX_ERROR");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK BOOT SLOT=%c REQUESTED RESETTING\r\n",
                (unsigned long)request_id,
                (slot == BOOT_SLOT_A) ? 'A' : 'B');

            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
    }
    else if (strcmp(cmd, "FW STATUS") == 0)
    {
        Fw_SendStatus(request_id);
    }
    else if (strcmp(cmd, "FW CONFIRM") == 0)
    {
        if (fw_update.active != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_UPDATE_ACTIVE");
        }
        else if (BootMeta_ConfirmCurrent() == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FLASH,
                "MAILBOX_ERROR");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK FW CONFIRM REQUESTED SLOT=%c RESETTING\r\n",
                (unsigned long)request_id,
                (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B');

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
    }
    else if (strncmp(cmd, "FW BEGIN ", 9U) == 0)
    {
#if defined(TIGHTEN_SYNTHETIC_BENCH)
        if (synthetic_busy != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "SIM_BUSY");
            return;
        }
#endif
        char *size_text;
        char *crc_text;
        char *end_size;
        char *end_crc;
        unsigned long image_size_ul;
        unsigned long image_crc_ul;
        BootMetaV2_t meta;
        uint8_t ack_queued;

        g_fw_diag_stage = 10U;
        g_fw_diag_ack_queued = 0U;
        g_fw_diag_hal_status = 0U;
        g_fw_diag_lock_status = 0U;
        g_fw_diag_page_error = 0xFFFFFFFFUL;
        g_fw_diag_flash_error = 0U;
        g_fw_diag_flash_sr = FLASH->SR;
        g_fw_diag_flash_cr = FLASH->CR;
        Fw_DiagSnapshotComms();

        if (BootHealth_IsCurrentTrial() != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "TRIAL_NOT_CONFIRMED");
        }
        else if ((fw_update.active != 0U) ||
                 (Tightening_IsBusy() != 0U) ||
                 (tightening_start_request != 0U) ||
                 (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING, "ROTOR_MOVING");
        }
        else if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_FAULT, "FAULT");
        }
        else
        {
            size_text = cmd + 9U;
            while ((*size_text == ' ') || (*size_text == '\t'))
            {
                size_text++;
            }

            image_size_ul = strtoul(size_text, &end_size, 10);

            while ((*end_size == ' ') || (*end_size == '\t'))
            {
                end_size++;
            }

            crc_text = end_size;
            image_crc_ul = strtoul(crc_text, &end_crc, 16);

            while ((*end_crc == ' ') || (*end_crc == '\t'))
            {
                end_crc++;
            }

            if ((size_text == end_size) ||
                (crc_text == end_crc) ||
                (*end_crc != '\0') ||
                (image_size_ul < 8UL) ||
                (image_size_ul > FW_SLOT_SIZE) ||
                (image_crc_ul > 0xFFFFFFFFUL))
            {
                Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "BAD_FW_BEGIN");
            }
            else if ((BootMeta_ReadV3(&meta) != 0U) &&
                     (meta.pending_slot == APP_THIS_SLOT) &&
                     (meta.confirmed_slot != APP_THIS_SLOT))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "CURRENT_SLOT_NOT_CONFIRMED");
            }
            else
            {
                g_fw_diag_stage = 20U;
                Fw_DiagSnapshotComms();

                g_fw_diag_stage = 30U;
                Fw_EnterSafeState();
                g_fw_diag_stage = 40U;

                /* Build the update context while keeping ACTIVE=0 until the
                   target slot has actually been erased successfully. */
                Fw_ResetContext();
                fw_update.image_size = (uint32_t)image_size_ul;
                fw_update.expected_crc32 = (uint32_t)image_crc_ul;

                if (Fw_EraseTarget(fw_update.image_size) == 0U)
                {
                    Fw_ResetContext();
                    Protocol_SendError(request_id, PROTO_ERR_FLASH, "ERASE_FAILED");
                }
                else
                {
                    fw_update.active = 1U;
                    g_fw_diag_stage = 100U;
                    Fw_DiagSnapshotComms();

                    ack_queued = Protocol_SendFormatted(
                        msg,
                        sizeof(msg),
                        "%lu OK FW BEGIN TARGET=%c SIZE=%lu CRC32=0x%08lX\r\n",
                        (unsigned long)request_id,
                        (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
                        (unsigned long)fw_update.image_size,
                        (unsigned long)fw_update.expected_crc32);
                    g_fw_diag_ack_queued = (uint32_t)ack_queued;

                    if (ack_queued != 0U)
                    {
                        g_fw_diag_stage = 110U;
                    }
                    else
                    {
                        /* Erase succeeded, but the host was not told. Leave
                           no ACTIVE half-session; a later BEGIN may safely
                           erase the inactive slot again and restart. */
                        Fw_ResetContext();
                    }

                    g_fw_diag_stage = 120U;
                    Fw_DiagSnapshotComms();
                }
            }
        }
    }
    else if (strncmp(cmd, "FW DATA ", 8U) == 0)
    {
        char *offset_text;
        char *hex_text;
        char *end_offset;
        unsigned long offset_ul;
        uint8_t data[FW_DATA_MAX_BYTES];
        uint32_t data_len = 0U;

        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else
        {
            offset_text = cmd + 8U;
            while ((*offset_text == ' ') || (*offset_text == '\t'))
            {
                offset_text++;
            }

            offset_ul = strtoul(offset_text, &end_offset, 16);

            while ((*end_offset == ' ') || (*end_offset == '\t'))
            {
                end_offset++;
            }

            hex_text = end_offset;

            if ((offset_text == end_offset) ||
                (offset_ul > 0xFFFFFFFFUL) ||
                (Fw_ParseHexBytes(hex_text, data, &data_len) == 0U))
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "BAD_FW_DATA");
            }
            else if ((uint32_t)offset_ul != fw_update.bytes_received)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu ERR %u FW_SEQUENCE EXPECT_OFFSET=%08lX\r\n",
                    (unsigned long)request_id,
                    (unsigned int)PROTO_ERR_FW_SEQUENCE,
                    (unsigned long)fw_update.bytes_received);
            }
            else if (Fw_ProgramData(
                         (uint32_t)offset_ul,
                         data,
                         data_len) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_FLASH,
                    "PROGRAM_FAILED");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK FW DATA OFFSET=%08lX LEN=%lu RX=%lu/%lu\r\n",
                    (unsigned long)request_id,
                    (unsigned long)offset_ul,
                    (unsigned long)data_len,
                    (unsigned long)fw_update.bytes_received,
                    (unsigned long)fw_update.image_size);
            }
        }
    }
    else if (strcmp(cmd, "FW END") == 0)
    {
        uint32_t actual_crc;
        BootMetaV2_t meta;

        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else if (fw_update.bytes_received != fw_update.image_size)
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu ERR %u FW_INCOMPLETE RX=%lu SIZE=%lu\r\n",
                (unsigned long)request_id,
                (unsigned int)PROTO_ERR_FW_SEQUENCE,
                (unsigned long)fw_update.bytes_received,
                (unsigned long)fw_update.image_size);
        }
        else if (Fw_TargetVectorValid() == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_RANGE,
                "BAD_TARGET_VECTOR");
        }
        else
        {
            actual_crc = Fw_TargetCrc32(fw_update.image_size);

            if (actual_crc != fw_update.expected_crc32)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu ERR %u FW_CRC EXPECT=0x%08lX ACTUAL=0x%08lX\r\n",
                    (unsigned long)request_id,
                    (unsigned int)PROTO_ERR_FW_CRC,
                    (unsigned long)fw_update.expected_crc32,
                    (unsigned long)actual_crc);
            }
            else if (BootMailbox_RequestStartTrial(
                         APP_TARGET_SLOT,
                         fw_update.image_size,
                         actual_crc) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_FLASH,
                    "MAILBOX_ERROR");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK FW END TARGET=%c SIZE=%lu CRC32=0x%08lX "
                    "COMMIT=BOOTLOADER ATTEMPTS=%lu RESETTING\r\n",
                    (unsigned long)request_id,
                    (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
                    (unsigned long)fw_update.image_size,
                    (unsigned long)actual_crc,
                    (unsigned long)FW_TRIAL_ATTEMPTS);

                Fw_EnterSafeState();
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
        }
    }
    else if (strcmp(cmd, "FW ABORT") == 0)
    {
        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else
        {
            Fw_ResetContext();

            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK FW ABORTED RESETTING\r\n",
                (unsigned long)request_id);

            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
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
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK SAVE PARAMS CRC32=0x%08lX\r\n",
                     (unsigned long)request_id,
                     (unsigned long)recipe_state.last_crc32);
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
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu OK LOAD PARAMS CRC32=0x%08lX\r\n",
                         (unsigned long)request_id,
                         (unsigned long)recipe_state.last_crc32);
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
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK DEFAULT PARAMS DIRTY=1\r\n",
                     (unsigned long)request_id);
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
        MotorJob_HandleUartStart(request_id);
    }
    else if (strcmp(cmd, "STOP") == 0)
    {
        MotorJob_QueueStop(request_id);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
            "%lu OK STOP QUEUED\r\n", (unsigned long)request_id);
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

            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK RESULT QUEUED\r\n",
                (unsigned long)request_id);
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

static void Router_RxLine(const char *line, void *context)
{
    (void)context;
    if (Router_SubmitAsciiLine(ROUTER_PORT_UART1, line) == 0U)
        UART_SendLiteral("EVT ROUTER RX_DROP OR PARSE_ERROR\r\n");
}

static void Router_RxByte(uint8_t byte, void *context)
{
    if (UartLineParser_Byte((UartLineParser *)context, byte,
                            Router_RxLine, NULL) < 0)
        UART_SendLiteral("EVT ROUTER LINE_TOO_LONG\r\n");
}

static void Router_RxGap(void *context)
{
    UartLineParser_Gap((UartLineParser *)context);
}

static void RouterTask(void *argument)
{
#if defined(FOC_ISOLATED_CONCURRENCY)
    isolated_router_task = xTaskGetCurrentTaskHandle();
#endif
    TickType_t last_wake_time;
    UartLineParser parser;
    (void)argument;
    UartLineParser_Init(&parser);
    last_wake_time = xTaskGetTickCount();
    UART_SendLiteral(
        "\r\nRouterTask: DMA1_CH2 circular -> direct parser\r\n"
        "Legacy Protocol V2 lines remain locally compatible\r\n"
        "Loss/overflow: discard partial line to next delimiter\r\n"
        "Local node ID: 1\r\n\r\n");
    for (;;) {
        (void)UART_RxDma_Drain(Router_RxByte, Router_RxGap, &parser, 1024U);
        Router_Service(8U);
        Router_Maintenance();
        vTaskDelayUntil(&last_wake_time,
                       pdMS_TO_TICKS(UART_ROUTER_POLL_MS));
    }
}


static void ProtocolTask(void *argument)
{
#if defined(FOC_ISOLATED_CONCURRENCY)
    isolated_protocol_task = xTaskGetCurrentTaskHandle();
#endif
    TickType_t last_wake_time;
    char line[ROUTER_MAX_PAYLOAD + 1U];

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendLiteral(
        "\r\n"
        "ProtocolTask Stage 4.3 started @ 5ms\r\n"
        "Input: Router LOCAL packet queue -> Protocol / EVT / EVT_ACK handlers\r\n"
        "Legacy UART request -> raw UART reply\r\n"
        "Routed PROTOCOL request -> routed synchronous reply\r\n"
        "Stage 4.3: async EVT uses EID + ACK + 500ms bounded retry\r\n"
        "Protocol V2 + IAP unchanged: <REQ_ID> <COMMAND>\r\n"
        "Router commands: STATUS / NODES / ROUTES / DISCOVER / CONFIG / CLEAR / SEND\r\n"
        "Device is IDLE until START is received\r\n\r\n");

    for (;;)
    {
        uint32_t processed = 0U;
        RouterPacket_t packet;

        /*
         * Stage 4.3 keeps all application-event transport/retry work in
         * ProtocolTask. TighteningTask only enqueues immutable event records.
         */
        Protocol_AsyncEventService(4U);
#if defined(UART_FIRMWARE_TRANSFER)
        PW_UartFirmwareTransfer_Service();
#endif
        PW_LogRouter_Service(4U);
#if defined(CAN_RPC_READ_ONLY)
        PW_CanRpc_ProtocolService();
#endif
#if !defined(ZERO_RETEST_BOOT)
        Modbus_ServiceCompletions(4U);
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
        PW_RouterTransfer_Tick(HAL_GetTick());
#endif
        Protocol_EspPingService();

        while ((processed < 8U) &&
               (Router_LocalReadPacket(&packet) != 0U))
        {
            size_t len = packet.length;

            if (len > ROUTER_MAX_PAYLOAD)
            {
                len = ROUTER_MAX_PAYLOAD;
            }

            memcpy(line, packet.payload, len);
            line[len] = '\0';

#if defined(ROUTER_READ_ONLY_TRANSFER)
            if (packet.type == RN_TRANSFER_TYPE)
            {
                (void)PW_RouterTransfer_Process(&packet, HAL_GetTick());
                processed++;
                continue;
            }
#endif
#if defined(ROUTER_READ_ONLY_RPC)
            /* Dedicated typed endpoint: never send RPC bytes to the console.
             * ProtocolTask is the sole owner of synchronous unary RPC calls. */
            if (packet.type == RN_RPC_TYPE)
            {
                (void)PW_RouterRpc_Process(&packet, HAL_GetTick());
                processed++;
                continue;
            }
#endif
            if (packet.ingress_port == ROUTER_PORT_ESP32)
            {
                /* The ESP UART can deliver only a matched diagnostic PONG.
                 * Never pass ESP payloads into Protocol_HandleLine(). */
                Protocol_ClearReplyRoute();
                Protocol_EspPingHandlePacket(&packet);
            }
            else if (packet.type == PROTOCOL_ROUTER_TYPE_EVENT)
            {
                /* Reliable async event plane: deliver once, ACK every copy. */
                Protocol_ClearReplyRoute();
                Protocol_ReliableEventHandleEventPacket(&packet);
            }
            else if (packet.type == PROTOCOL_ROUTER_TYPE_EVENT_ACK)
            {
                /* ACK is router/application control traffic, not Protocol V2. */
                Protocol_ClearReplyRoute();
                Protocol_ReliableEventHandleAckPacket(&packet);
            }
            else if (packet.type == PW_LOG_ROUTER_PACKET_TYPE)
            {
                Protocol_ClearReplyRoute();
                PW_LogRouter_HandleRemote(&packet);
            }
            else
            {
                /*
                 * src=0 is Stage1/2 legacy UART compatibility.
                 * A real routed Protocol request remembers its source node so
                 * synchronous Protocol V2 replies can take the reverse route.
                 */
                if ((packet.type == ROUTER_PKT_PROTOCOL) &&
                    (packet.src != 0U) &&
                    (packet.src != ROUTER_LOCAL_NODE_ID) &&
                    (packet.src != ROUTER_BROADCAST_NODE))
                {
                    Protocol_SetReplyRoute(packet.src);
                }
                else
                {
                    Protocol_ClearReplyRoute();
                }

                protocol_esp_ping_uart_local =
                    ((packet.src == 0U) &&
                     (packet.ingress_port == ROUTER_PORT_UART1)) ? 1U : 0U;
                Protocol_HandleLine(line);
                protocol_esp_ping_uart_local = 0U;
                Protocol_ClearReplyRoute();
            }

            processed++;
        }

        /* Incoming ACK packets above can clear slots before this retry pass. */
        Protocol_ReliableEventService(4U);
#if !defined(ZERO_RETEST_BOOT)
        Modbus_ServiceCompletions(4U);
#endif

        vTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(5U));
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

    UART_SendLiteral(
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
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
        ControlChain_TaskService();
#endif
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

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STOPPED START_REQ=%lu\r\n",
                    (unsigned long)stop_request_id,
                    (unsigned long)tightening_cycle_request_id);

                Protocol_SendCycleEvent("COMPLETE", "STOPPED");

                UART_SendLiteral(
                    "TIGHTEN: STOP command -> IDLE\r\n");

                if (tightening_result_printed == 0U)
                {
                    tightening_result_printed = 1U;
                    TighteningResult_PrintSummary("STOPPED");
                }
            }
            else
            {
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu ALREADY_IDLE\r\n",
                    (unsigned long)stop_request_id);

                UART_SendLiteral(
                    "TIGHTEN: STOP command -> already IDLE\r\n");
            }
        }

        if (tightening_start_request != 0U)
        {
            uint32_t start_request_id;
            uint8_t start_request_routed;
            uint16_t start_request_source_node;
            char proto_msg[160];

            /*
             * The producer publishes tightening_start_request last.  After
             * observing it, acquire the associated correlation/route fields.
             */
            __DMB();
            start_request_id = tightening_start_request_id;
            start_request_routed = tightening_start_request_routed;
            start_request_source_node =
                tightening_start_request_source_node;

            tightening_start_request = 0U;
            tightening_start_request_id = 0U;
            tightening_start_request_routed = 0U;
            tightening_start_request_source_node = 0U;

            if ((adc_fault != 0U) || (foc_fault != 0U))
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "FAULT");
            }
            else if (Tightening_IsBusy() != 0U)
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "BUSY");
            }
            else if (fabsf(encoder_speed_rpm) >
                     TIGHTEN_REPEAT_RESTART_MAX_RPM)
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "ROTOR_MOVING");
            }
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
            else if (!ControlChain_StartReady(start_request_id) &&
                     SystemPreflight_FailMask() != 0U)
#else
            else if (SystemPreflight_FailMask() != 0U)
#endif
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "PREFLIGHT_NOT_READY");
            }
#if defined(FOC_LATEST_ORIGINAL_FSM)
            else if (start_request_routed || !LatestOriginal_Admit())
            {
                Protocol_SendDeferredStartError(
                    start_request_routed, start_request_source_node,
                    start_request_id, "LATEST_BACKEND_NOT_READY");
            }
#endif
            else
            {
                memset(tightening_cycle_summary,
                       0,
                       sizeof(tightening_cycle_summary));

                tightening_cycle_number = 1U;
                tightening_cycle_ok_count = 0U;
                tightening_last_outcome = TIGHTEN_OUTCOME_NONE;
                tightening_cycle_request_id = start_request_id;

                /*
                 * Stage 4.1: this is the point where the START has really
                 * become a tightening cycle, so make its origin persistent.
                 */
                TighteningSession_Begin(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id);

                TighteningRepeat_ResetCurrentCycle();

                tightening_start_position_deg =
                    encoder_position_deg;
                tightening_travel_deg = 0.0f;
                stop_confirm_ms = 0U;

                MotorControl_SetSpeed(
                    TIGHTEN_DIRECTION *
                    (float)recipe_state.params.rundown_rpm);

                tightening_test_stage =
                    TIGHTEN_STATE_RUNDOWN;
                stage_start = now;
                tightening_test_elapsed_ms = 0U;
                tightening_travel_deg = 0.0f;
                tightening_post_contact_travel_deg = 0.0f;

                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STARTED MODE=RUNDOWN TARGET=%lurpm",
                    (unsigned long)tightening_cycle_request_id,
                    (unsigned long)recipe_state.params.rundown_rpm);
                if (Protocol_AsyncEventEnqueue(
                        g_tightening_session_routed,
                        g_tightening_session_owner_node,
                        proto_msg) == 0U)
                {
                    UART_SendLiteral("EVT ASYNC QUEUE FULL: STARTED LOST\r\n");
                }

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT SESSION ACTIVE=1 ROUTED=%u OWNER=%u START_REQ=%lu\r\n",
                    (unsigned int)g_tightening_session_routed,
                    (unsigned int)g_tightening_session_owner_node,
                    (unsigned long)g_tightening_session_request_id);

                UART_SendLiteral(
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
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT NONE START_REQ=0\r\n",
                    (unsigned long)result_request_id);
            }
            else
            {
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT DATA START_REQ=%lu OUTCOME=%s CONTACT=%u\r\n",
                    (unsigned long)result_request_id,
                    (unsigned long)tightening_cycle_request_id,
                    TighteningOutcome_Name(tightening_last_outcome),
                    (unsigned int)tightening_contact_confirmed);

                TighteningResult_PrintSummary(
                    TighteningOutcome_Name(
                        tightening_last_outcome));

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu END RESULT\r\n",
                    (unsigned long)result_request_id);
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

                UART_SendLiteral(
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
                     (float)recipe_state.params.contact_rpm) &&
                    (drive_iqref >=
                     ((float)recipe_state.params.contact_iq_mA / 1000.0f)))
                {
                    contact_now = 1U;
                }

                tightening_contact_condition = contact_now;

                if (contact_now != 0U)
                {
                    if (tightening_contact_candidate_ms <
                        recipe_state.params.contact_ms)
                    {
                        tightening_contact_candidate_ms += 10U;
                    }
                }
                else
                {
                    tightening_contact_candidate_ms = 0U;
                }

                if (tightening_contact_candidate_ms >=
                    recipe_state.params.contact_ms)
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

                    UART_SendLiteral(
                        "TIGHTEN: CONTACT CONFIRMED -> IDLE stop\r\n");
                }
                else if ((elapsed_ms >=
                          recipe_state.params.rundown_timeout_ms) ||
                         (travel >=
                          (float)recipe_state.params.max_travel_deg))
                {
                    PowerStage_Disable();
                    FaultDiag_Capture(FOC_DIAG_PROCESS,TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT,
                        elapsed_ms>=recipe_state.params.rundown_timeout_ms ? FOC_TO_RUNDOWN : FOC_TO_NONE,
                        elapsed_ms,recipe_state.params.rundown_timeout_ms);
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

                    UART_SendLiteral(
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
                        ((float)recipe_state.params.seating_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.seating_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_SEATING_IQ;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;

                    UART_SendLiteral(
                        "TIGHTEN: SEATING started\r\n");
                }
                else if (elapsed_ms >=
                         TIGHTEN_STOP_TIMEOUT_MS)
                {
                    PowerStage_Disable();
                    FaultDiag_Capture(FOC_DIAG_PROCESS,TIGHTEN_OUTCOME_STOP_TIMEOUT,
                        FOC_TO_STOP_SETTLE,elapsed_ms,TIGHTEN_STOP_TIMEOUT_MS);
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

                    UART_SendLiteral(
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
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
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

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.seating_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_010,
                        ((float)recipe_state.params.t1_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t1_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_010;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #1\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_010:
                TighteningResult_Sample(&tighten_result_010);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
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

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t1_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_012,
                        ((float)recipe_state.params.t2_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t2_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_012;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #2\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_012:
                TighteningResult_Sample(&tighten_result_012);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
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

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t2_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_015,
                        ((float)recipe_state.params.t3_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t3_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_015;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #3\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_015:
                TighteningResult_Sample(&tighten_result_015);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
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

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t3_ms)
                {
                    /*
                     * HOLD keeps the same +0.15 A command; only the state/time
                     * changes so the log clearly separates final hold.
                     */
                    TighteningResult_Reset(
                        &tighten_result_hold,
                        ((float)recipe_state.params.hold_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.hold_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_HOLD;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: HOLD started\r\n");
                }
                break;

            case TIGHTEN_STATE_HOLD:
                TighteningResult_Sample(&tighten_result_hold);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
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

                    UART_SendLiteral(
                        "TIGHTEN: HOLD speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.hold_ms)
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

                    UART_SendLiteral(
                        "TIGHTEN: COMPLETE -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("OK");
                        TighteningRepeat_StoreCurrentCycle();
                    }

                    UART_SendLiteral(
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

#if defined(FOC_LATEST_ORIGINAL_FSM)
        LatestOriginal_FsmService();
#endif
        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
    }
}


static void BootHealthTask(void *argument)
{
    TickType_t last_wake_time;
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    boot_health_trial_active = 0U;
    boot_health_last_sample_ok = 0U;
    boot_health_stable_ms = 0U;
    boot_health_elapsed_ms = 0U;

    /*
     * StartupTask creates this task only after ADC/FOC, UART RX/TX and the
     * main application tasks have all been initialized. Give the just-created
     * peer tasks one scheduling interval before examining the trial state.
     */
    vTaskDelay(pdMS_TO_TICKS(BOOT_HEALTH_CHECK_MS));

    if (BootHealth_IsCurrentTrial() == 0U)
    {
        UART_SendLiteral(
            "BOOT HEALTH: current slot is already confirmed; auto-confirm task idle\r\n");
        vTaskDelete(NULL);
        return;
    }

    boot_health_trial_active = 1U;

    UART_SendLiteral(
        "BOOT HEALTH: TRIAL slot detected -> require 5s continuous healthy window\r\n"
        "BOOT HEALTH: START/FW BEGIN/BOOT switch locked until confirmation\r\n");

    last_wake_time = xTaskGetTickCount();
    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;

    for (;;)
    {
        uint32_t adc_now;
        uint32_t foc_now;
        uint32_t adc_delta;
        uint32_t foc_delta;
        uint8_t sample_ok;
        BootMetaV2_t meta;

        vTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(BOOT_HEALTH_CHECK_MS));

        /*
         * Manual FW CONFIRM is still supported. If another task already
         * confirmed this APP, there is nothing left for auto-confirm to do.
         */
        if ((BootMeta_ReadV3(&meta) != 0U) &&
            (meta.pending_slot != APP_THIS_SLOT))
        {
            boot_health_trial_active = 0U;
            boot_health_last_sample_ok = 1U;
            UART_SendLiteral(
                "BOOT HEALTH: trial state cleared externally -> task complete\r\n");
            vTaskDelete(NULL);
            return;
        }

        adc_now = injected_seq_count;
        foc_now = foc_control_count;

        adc_delta = adc_now - last_adc_count;
        foc_delta = foc_now - last_foc_count;

        last_adc_count = adc_now;
        last_foc_count = foc_now;

        boot_health_elapsed_ms += BOOT_HEALTH_CHECK_MS;

        sample_ok = 1U;

        if (BOOT_HEALTH_FORCE_FAIL_TEST != 0U)
        {
            sample_ok = 0U;
        }

#if defined(FOC_ISOLATED_CONCURRENCY)
        if (adc_fault != 0U || foc_fault != 0U || encoder_valid == 0U ||
            !IsolatedBench_Active() || !IsolatedBench_Locked())
#else
        if ((adc_fault != 0U) ||
            (foc_fault != 0U) ||
            (encoder_valid == 0U) ||
            (foc_enable == 0U))
#endif
        {
            sample_ok = 0U;
        }

        if (UART_Async_IsReady() == 0U)
        {
            sample_ok = 0U;
        }

        /*
         * In 500 ms a healthy 20 kHz chain should produce about 10,000
         * injected/current-loop executions. 9,000 leaves reasonable margin
         * while still detecting a badly stalled real-time chain.
         */
        if ((adc_delta < BOOT_HEALTH_MIN_ADC_DELTA) ||
            (foc_delta < BOOT_HEALTH_MIN_FOC_DELTA))
        {
            sample_ok = 0U;
        }

        /*
         * Trial firmware is intentionally kept in a non-working service state
         * until confirmation. This protects the known-good opposite slot from
         * being overwritten and prevents a tightening cycle during trial.
         */
        if ((fw_update.active != 0U) ||
            (Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U) ||
            (motor_control_mode != MOTOR_MODE_IDLE) ||
            (fabsf(encoder_speed_rpm) > 2.0f))
        {
            sample_ok = 0U;
        }

        boot_health_last_sample_ok = sample_ok;

        if (sample_ok != 0U)
        {
            boot_health_stable_ms += BOOT_HEALTH_CHECK_MS;
        }
        else
        {
            boot_health_stable_ms = 0U;
        }

        if (boot_health_stable_ms >=
            BOOT_HEALTH_STABLE_REQUIRED_MS)
        {
            /*
             * Enter a quiet hardware state before handing confirmation to the
             * bootloader. The APP itself no longer erases/programs Metadata V3.
             */
            UART_SendLiteral(
                "BOOT HEALTH: PASS 5s -> requesting bootloader confirmation\r\n");

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(20U));

            if (BootMeta_ConfirmCurrent() != 0U)
            {
                char msg[128];

                UART_SendFormatted(
                    msg,
                    sizeof(msg),
                    "BOOT HEALTH: CONFIRM REQUESTED SLOT=%c -> RESETTING\r\n",
                    (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B');

                boot_health_trial_active = 0U;
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
            else
            {
                UART_SendLiteral(
                    "BOOT HEALTH: SRAM mailbox confirm request FAILED -> RESET for retry/rollback\r\n");
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
        }

        /*
         * A trial that never establishes a healthy window must not remain
         * running forever. Reset without confirming; Bootloader V3 consumes
         * the next attempt and eventually returns to confirmed_slot.
         */
        if (boot_health_elapsed_ms >=
            BOOT_HEALTH_FAIL_RESET_MS)
        {
            UART_SendLiteral(
                "BOOT HEALTH: FAIL timeout -> NOT CONFIRMED -> RESET for rollback\r\n");

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(150U));
            NVIC_SystemReset();
        }
    }
}


#if defined(FOC_FAST_CURRENT_REJECT)
/* Task-only formatting: reserve Flash for the O2 realtime chain. */
__attribute__((optimize("Os")))
#endif
static void MonitorTask(void *argument)
{
    TickType_t last_sample_tick;
    TickType_t analog_wake_tick;
    TickType_t last_stack_tick;
#if defined(FOC_FAST_CURRENT_REJECT)
    TickType_t last_current_stats_tick=0U;
#endif
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    last_sample_tick = xTaskGetTickCount();
    analog_wake_tick = last_sample_tick;
    last_stack_tick = last_sample_tick;
    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;

#if defined(CAN_STATUS_TELEMETRY)
    /* A failed CAN interface does not change the motor-control path. */
    (void)CAN_StatusTx_Init();
#endif

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
         * Wake at 10 Hz for IDLE-only analog diagnostics. Keep the existing
         * human-readable UART monitor rate at 3 s IDLE / 1 s active.
         * This low-priority task never calls HAL_ADC_Stop() on ADC2.
         */
        monitor_period_ms =
            (Tightening_IsBusy() != 0U) ? 1000U : 3000U;

        vTaskDelayUntil(&analog_wake_tick,
                        pdMS_TO_TICKS(ANALOG_LIVE_PERIOD_MS));

        FaultDiag_Monitor(); /* Task-only, immutable first-fault evidence. */

#if defined(CAN_STATUS_TELEMETRY)
        CAN_StatusTx_Service(HAL_GetTick());
        {
            uint8_t flags = 0U;
            if (foc_enable != 0U) flags |= CAN_STATUS_FLAG_FOC_ENABLED;
            if (foc_fault != 0U) flags |= CAN_STATUS_FLAG_FAULT_LATCHED;
            if (encoder_valid != 0U) flags |= CAN_STATUS_FLAG_ENCODER_VALID;
            if (HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) == GPIO_PIN_SET)
                flags |= CAN_STATUS_FLAG_DRIVER_SD_HIGH;
            CAN_StatusTx_Publish((uint8_t)motor_control_mode, flags,
                                 (uint16_t)foc_fault_reason);
        }
#endif

        if ((motor_control_mode == MOTOR_MODE_IDLE) &&
            (Tightening_IsBusy() == 0U))
        {
            (void)ADC_AnalogLiveSample();
        }
        else
        {
            analog_live_valid = 0U;
        }

#if defined(CAN_STATUS_TELEMETRY)
        {
            uint32_t vbus_mv = 0U;
            uint8_t vbus_ok = 0U;
            if ((analog_live_valid != 0U) &&
                (analog_vdda_boot_valid != 0U) &&
                (analog_live_sample_count != 0U) &&
                ((HAL_GetTick() - analog_live_last_tick_ms) <= ANALOG_LIVE_FRESH_MS))
            {
                vbus_mv = (uint32_t)
                    (((uint64_t)analog_live_pc4_raw *
                      (uint64_t)analog_vdda_boot_mv *
                      ANALOG_VBUS_DIVIDER + (ADC_FULL_SCALE / 2U)) /
                     ADC_FULL_SCALE);
                vbus_ok = 1U;
            }
            CAN_StatusTx_PublishMotor(encoder_position_deg, foc_iq_A,
                                      encoder_valid,
                                      (foc_enable != 0U) && (foc_fault == 0U) &&
                                      (encoder_valid != 0U) &&
                                      (analog_safe_latched == 0U));
            CAN_StatusTx_PublishElectrical(vbus_mv, encoder_speed_rpm,
                                           vbus_ok, encoder_valid);
        }
#endif

#if defined(CAN_LOG_STREAM) || defined(CAN_RPC_READ_ONLY)
        /* Give the three telemetry frames time to leave the hardware FIFO.
           MonitorTask remains the only FDCAN owner; producers never wait. */
        vTaskDelay(pdMS_TO_TICKS(5U));
#if defined(CAN_RPC_READ_ONLY)
        PW_CanRpc_MonitorService(HAL_GetTick());
#endif
#if defined(CAN_LOG_STREAM)
        PW_CanLog_Service(HAL_GetTick());
#endif
#endif

#if defined(ESP_NETWORK_OBSERVER)
        {
            static uint32_t last_network_ms;
            uint32_t network_ms = HAL_GetTick();
            if ((uint32_t)(network_ms - last_network_ms) >= 1000U) {
                last_network_ms = network_ms;
                NetworkObserver_Publish(NET_KIND_SAMPLE);
            }
        }
#endif
        now_tick = xTaskGetTickCount();

        /* Scan MotorCtrl stack only from this lower-priority task. */
        if ((motor_control_task_handle != NULL) &&
            ((now_tick - last_stack_tick) >= pdMS_TO_TICKS(1000U)))
        {
            uint32_t free_words = (uint32_t)
                uxTaskGetStackHighWaterMark(motor_control_task_handle);
            if (free_words < motor_stack_min_words)
            {
                motor_stack_min_words = free_words;
            }
            motor_stack_samples++;
            last_stack_tick = now_tick;
        }

        if ((now_tick - last_sample_tick) <
            pdMS_TO_TICKS(monitor_period_ms))
        {
            continue;
        }

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
#if defined(FOC_FAST_CURRENT_REJECT)
        if ((TickType_t)(now_tick-last_current_stats_tick)>=pdMS_TO_TICKS(5000U)) {
            last_current_stats_tick=now_tick;
            ProtectedLoop_CurrentMonitor();
        }
#endif
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

        UART_SendFormatted(
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
#if defined(CAN_STATUS_TELEMETRY)
        {
            CAN_StatusTx_Health can_health;
            CAN_StatusTx_GetHealth(&can_health);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN HEALTH READY=%u HALT=%u INIT=%lu FAIL=%lu RECOVER=%lu "
                     "BO=%lu FIFO_STALL=%lu ENQ=%lu DONE=%lu EVT_LOST=%lu "
                     "FULL=%lu ADD_FAIL=%lu "
                     "TEC=%lu REC=%lu LEC=%lu FREE=%lu\r\n",
                     (unsigned int)can_health.ready,
                     (unsigned int)can_health.recovery_exhausted,
                     (unsigned long)can_health.init_attempts,
                     (unsigned long)can_health.init_failures,
                     (unsigned long)can_health.recoveries,
                     (unsigned long)can_health.bus_off_events,
                     (unsigned long)can_health.fifo_stalls,
                     (unsigned long)can_health.tx_enqueued,
                     (unsigned long)can_health.tx_completed,
                     (unsigned long)can_health.tx_event_lost,
                     (unsigned long)can_health.tx_fifo_full,
                     (unsigned long)can_health.tx_add_failures,
                     (unsigned long)can_health.tx_error_count,
                     (unsigned long)can_health.rx_error_count,
                     (unsigned long)can_health.last_error_code,
                     (unsigned long)can_health.fifo_free);
        }
#if defined(CAN_SHADOW_DIAG)
        {
            CAN_ShadowHealth shadow;
            CAN_StatusTx_GetShadowHealth(&shadow);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN SHADOW RX=%lu BAD=%lu REPLY=%lu DROP=%lu "
                     "TIMEOUT=%lu STOP_TEST=%lu RANGE=%lu OVERRUN=%lu "
                     "NO_MOTOR_ACTION=1\r\n",
                     (unsigned long)shadow.received,
                     (unsigned long)shadow.invalid_frames,
                     (unsigned long)shadow.replies_queued,
                     (unsigned long)shadow.replies_dropped,
                     (unsigned long)shadow.probe_timeouts,
                     (unsigned long)shadow.stop_tests,
                     (unsigned long)shadow.range_rejects,
                     (unsigned long)shadow.fifo_overruns);
        }
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
        {
            CAN_ControlRejectHealth control;
            CAN_StatusTx_GetControlRejectHealth(&control);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN CONTROL RX=%lu BAD=%lu REJECT=%lu REPLY=%lu "
                     "DROP=%lu OVERRUN=%lu EXEC_DISABLED=1\r\n",
                     (unsigned long)control.received,
                     (unsigned long)control.invalid_frames,
                     (unsigned long)control.rejected,
                     (unsigned long)control.replies_queued,
                     (unsigned long)control.replies_dropped,
                     (unsigned long)control.fifo_overruns);
        }
#endif
#endif
    }
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
static int AS5047P_TransferAdapter(void *context, uint16_t tx,
                                    uint16_t *rx)
{
    (void)context;
    return (int)AS5047P_Transfer16(tx, rx);
}

/* The two-frame sequence is shared with the host fake-device tests. */
static HAL_StatusTypeDef AS5047P_ReadRegisterFrame(uint16_t reg,
                                                   uint16_t *response)
{
#if defined(AS5047P_SPI_DMA)
    return AS5047P_DmaReadOne(reg, response) == AS_DMA_OK ? HAL_OK : HAL_ERROR;
#else
    AS5047P_TransactionTrace_t trace = {0};
    int status = AS5047P_ReadRegisterVia(AS5047P_TransferAdapter, NULL,
                                          reg, response, &trace);
    if ((status != 0) && (as5047p_diag_verbose != 0U))
    {
        char msg[180];
        UART_SendFormatted(msg, sizeof(msg),
                 "ENC FAIL: REG=0x%04X PHASE=%u STAGE=%u HAL=%d "
                 "SPI_ERR=0x%08lX RX=0x%04X\r\n",
                 (unsigned int)trace.reg, (unsigned int)trace.phase,
                 (unsigned int)trace.failure, status,
                 (unsigned long)HAL_SPI_GetError(&hspi1),
                 (unsigned int)trace.response);
    }
    return (HAL_StatusTypeDef)status;
#endif
}
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

    f = AS5047P_ErrorFlags(rsp);
    as5047p_last_errfl = f;

    if (flags != NULL)
    {
        *flags = f;
    }

    if (as5047p_diag_verbose != 0U)
    {
        char msg[220];

        UART_SendFormatted(msg,
                 sizeof(msg),
                 "ENC ERRFL: RAW=0x%04X FLAGS=0x%X "
                 "PARERR=%u INVCOMM=%u FRERR=%u EF=%u\r\n",
                 (unsigned int)rsp,
                 (unsigned int)f,
                 (unsigned int)((f & AS5047P_ERRFL_PARERR) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_INVCOMM) != 0U),
                 (unsigned int)((f & AS5047P_ERRFL_FRERR) != 0U),
                 (unsigned int)((rsp & 0x4000U) != 0U));
    }

    return HAL_OK;
}


static HAL_StatusTypeDef AS5047P_ReadAngle(uint16_t *raw)
{
#if defined(AS5047P_SPI_DMA)
    uint16_t response = 0U;
    AsDmaStatus status = AS5047P_DmaReadOne(0x3FFFU, &response);
    if (status == AS_DMA_OK && raw != NULL) *raw = response & 0x3FFFU;
    return status == AS_DMA_OK ? HAL_OK : HAL_ERROR;
#else
    AS5047P_TransactionTrace_t trace = {0};
    uint32_t start_cycles = DWT->CYCCNT;
    int status = AS5047P_ReadAngleVia(AS5047P_TransferAdapter, NULL,
                                       raw, &trace);
    if (encoder_diag_dwt_ready != 0U)
    {
        uint32_t elapsed_cycles = DWT->CYCCNT - start_cycles;
        encoder_diag_last_cycles = elapsed_cycles;
        if (elapsed_cycles > encoder_diag_max_cycles)
        {
            encoder_diag_max_cycles = elapsed_cycles;
        }
        if (elapsed_cycles >= (SystemCoreClock / 1000U))
        {
            encoder_diag_over_1ms++;
        }
        encoder_diag_reads++;
        if (status != 0) { encoder_diag_failures++; }
    }
    if (trace.errfl_valid != 0U)
    {
        as5047p_last_errfl = trace.errfl;
    }
    if (as5047p_diag_verbose != 0U)
    {
        char msg[200];
        if (status != 0)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ENC FAIL: PHASE=%u STAGE=%u HAL=%d "
                     "REG=0x%04X RX=0x%04X ERRFL=0x%X\r\n",
                     (unsigned int)trace.phase,
                     (unsigned int)trace.failure, status,
                     (unsigned int)trace.reg,
                     (unsigned int)trace.response,
                     (unsigned int)trace.errfl);
        }
        else if (trace.recovered != 0U)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ENC RECOVERED: ERRFL=0x%X ANGLE_RX=0x%04X\r\n",
                     (unsigned int)trace.errfl,
                     (unsigned int)trace.response);
        }
    }
    return (HAL_StatusTypeDef)status;
#endif
}

static void EncoderDiag_InitCycleCounter(void)
{
    uint32_t before;

    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0U;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    before = DWT->CYCCNT;
    __NOP(); __NOP(); __NOP(); __NOP();
    encoder_diag_dwt_ready =
        (uint8_t)(((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U) &&
                  (DWT->CYCCNT != before));
}

static float Encoder_ElectricalAngleRad(uint16_t raw)
{
    return AS5047P_ElectricalAngleRad(raw, ELECTRICAL_ZERO_RAW,
                                     POLE_PAIRS, ENCODER_DIRECTION);
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
        UART_SendFormatted(msg,
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
    }
    else
    {
        UART_SendLiteral(
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

    UART_SendFormatted(msg,
             sizeof(msg),
             "AS5047P startup: OK=%lu/20 RAW=%u ELEC=%ludeg "
             "ERR=%lu LAST_ERRFL=0x%X\r\n",
             (unsigned long)ok,
             (unsigned int)encoder_raw,
             (unsigned long)(encoder_theta_e * 180.0f / PI_F),
             (unsigned long)encoder_error_count,
             (unsigned int)as5047p_last_errfl);

    return (ok >= 15U) ? HAL_OK : HAL_ERROR;
}


static uint16_t Median3_U16(uint16_t a, uint16_t b, uint16_t c)
{
    return FocMedian3_U16(a, b, c);
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

static uint8_t Router_Uart1Tx(const RouterPacket_t *packet)
{
    char frame[ROUTER_MAX_PAYLOAD + 96U];
    if (packet == NULL || packet->length > ROUTER_MAX_PAYLOAD) return 0U;
    if (g_rtos_started != 0U && g_uart_async_runtime_enable != 0U)
        return RouterUartTx_Queue(packet, UART_PROTOCOL_TX_TIMEOUT_MS);
    /* Pre-scheduler fallback remains synchronous and never uses the heap. */
    frame[0] = '\r'; frame[1] = '\n';
    size_t len = Router_EncodeAsciiFrame(packet, frame + 2U, sizeof(frame) - 2U);
    if (len == 0U || len + 4U >= sizeof(frame)) return 0U;
    len += 2U;
    frame[len++] = '\r'; frame[len++] = '\n'; frame[len] = '\0';
    return UART_SendReliableString(frame);
}


static void PowerStage_Disable(void)
{
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
}

static void PowerStage_Enable(void)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    /* Only the bounded task-owned transaction in ProtectedLoop can enable. */
    PowerStage_Disable();
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    PowerStage_Disable();
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    PowerStage_Disable();
    return;
#endif
#if defined(FOC_ADC_WINDOW)
    if (!FocAdcTiming_CanStart() || adc_fault != 0U)
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }
#endif
#if defined(SAFETY_LOCKED_BOOT)
    /* Build-level gate: no software command can energize this profile. */
    PowerStage_Disable();
    return;
#else
    if (analog_safe_latched != 0U)
    {
        PowerStage_Disable();
        return;
    }
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_SET);
#endif
}

static void PWM_SetDuty(float du, float dv, float dw)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_SetDuty(du,dv,dw);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    (void)du; (void)dv; (void)dw;
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    /* Compute-only acceptance: never publish FOC duties to timer outputs. */
    (void)du; (void)dv; (void)dw;
    return;
#endif
#if defined(FOC_ADC_WINDOW)
    if (FocAdcTiming_Commit(du, dv, dw) != FOC_WINDOW_OK)
    {
        adc_fault = 1U;
        foc_enable = 0U;
        foc_fault = 1U;
        foc_fault_reason = FOC_FAULT_ADC_WINDOW;
        DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        __DSB();
        FaultDiag_Motor(FOC_FAULT_ADC_WINDOW);
    }
    return;
#else
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
#endif
}

static float ClampFloat(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

static void FOC_ResetController(void)
{
#if defined(FOC_SPEED_BRAKE_TRACK)
    SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    ProtectedLoop_PwmInvalidate();
#endif
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
FOC_HOT_PATH
static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,
                                uint16_t u_physical, uint16_t v_physical)
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

#if defined(FOC_ISOLATED_CONCURRENCY)
    if (!IsolatedBench_Active() || encoder_valid == 0U)
#else
    if ((foc_enable == 0U) || (encoder_valid == 0U))
#endif
    {
        PWM_SetDuty(0.5f, 0.5f, 0.5f);
        return;
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    (void)count_to_A; (void)u_raw; (void)v_raw; (void)u_physical; (void)v_physical;
    iu_A=cl_frame.iu_A; iv_A=cl_frame.iv_A; iw_A=cl_frame.iw_A;
    (void)iw_A;
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    /* The ADC binding already checked, selected and consumed this exact frame.
     * No legacy immediate amplitude gate in this hard-off candidate profile. */
    (void)count_to_A; (void)u_raw; (void)v_raw; (void)u_physical; (void)v_physical;
    iu_A = foc_feedback_control_frame.iu_A;
    iv_A = foc_feedback_control_frame.iv_A;
    iw_A = foc_feedback_control_frame.iw_A;
    (void)iw_A; /* Already reconstructed/checked by the guardian; Clarke uses U/V. */
#else
    iu_A = ((float)((int32_t)iu_zero_raw - (int32_t)u_raw)) * count_to_A;
    iv_A = ((float)((int32_t)iv_zero_raw - (int32_t)v_raw)) * count_to_A;
    iw_A = -(iu_A + iv_A);

#if defined(FOC_CURRENT_TREND4)
    /* Default policy: raw overload wins immediately at the unchanged limit.
     * The explicitly hard-off observation fixture keeps raw/feedback separate;
     * it cannot enable a physical power stage or qualify motor operation. */
    float filtered_u_A=iu_A, filtered_v_A=iv_A, filtered_w_A=iw_A;
    float physical_u_A = ((float)((int32_t)iu_zero_raw - u_physical)) * count_to_A;
    float physical_v_A = ((float)((int32_t)iv_zero_raw - v_physical)) * count_to_A;
    float physical_w_A = -(physical_u_A + physical_v_A);
    int physical_trip = FocTrend4_RawTrip(u_physical, v_physical,
        iu_zero_raw, iv_zero_raw, count_to_A, FOC_CURRENT_TRIP_A);
#if !defined(FOC_RAW_OBSERVE_ONLY)
    if (physical_trip) {
        iu_A = physical_u_A; iv_A = physical_v_A; iw_A = physical_w_A;
    }
#endif
#endif
    /*
     * Independent software phase-current trip, NOT an output-current command.
     * The requested 4 A threshold does not qualify the analog sensing chain
     * or resolve the previously observed fault at zero speed/torque command.
     */
    if (
#if defined(FOC_CURRENT_TREND4)
#if defined(FOC_RAW_OBSERVE_ONLY)
        /* Compile-time diagnostic ONLY: keep raw samples in the observer,
         * but never let a raw-only hit stop hard-off arithmetic. Invalid
         * data or a lost output lock still fail closed. Filtered overload
         * remains a stop unless separately opted into hard-off observation. */
        FocRawObserve_StopRequired(u_physical, v_physical, count_to_A,
            filtered_u_A, filtered_v_A, filtered_w_A, FOC_CURRENT_TRIP_A,
            IsolatedBench_Locked()) ||
#else
        physical_trip ||
#endif
#endif
#if defined(FOC_FILTERED_OBSERVE_ONLY)
        0 /* hard-off only; finite filtered overrange is observed below */
#else
        (fabsf(iu_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iv_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iw_A) > FOC_CURRENT_TRIP_A)
#endif
       )
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
        FaultDiag_Motor(1U);
        PWM_SetDuty(0.5f, 0.5f, 0.5f);

#if defined(FOC_CURRENT_TREND4)
        /* This stop is unconditional once its profile-specific gate fires.
         * Shadow classification never takes over the stop decision. */
        FocOcShadow_Push(&foc_oc_shadow, injected_seq_count,
            FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,FOC_CURRENT_TRIP_A),
            u_physical<=ADC_FULL_SCALE && v_physical<=ADC_FULL_SCALE);
#endif
        if (foc_current_trip_snapshot.valid == 0U)
        {
            uint32_t now_ms = HAL_GetTick();
            uint32_t vbus_age_ms = (analog_live_sample_count != 0U)
                                     ? (now_ms - analog_live_last_tick_ms)
                                     : UINT32_MAX;

            foc_current_trip_snapshot.tick_ms = now_ms;
            foc_current_trip_snapshot.adc_seq = injected_seq_count;
            foc_current_trip_snapshot.accepted_u = u_raw;
            foc_current_trip_snapshot.accepted_v = v_raw;
            foc_current_trip_snapshot.physical_u = u_physical;
            foc_current_trip_snapshot.physical_v = v_physical;
            foc_current_trip_snapshot.zero_u = iu_zero_raw;
            foc_current_trip_snapshot.zero_v = iv_zero_raw;
            foc_current_trip_snapshot.iu_mA = foc_trip_iu_mA;
            foc_current_trip_snapshot.iv_mA = foc_trip_iv_mA;
            foc_current_trip_snapshot.iw_mA = foc_trip_iw_mA;
            foc_current_trip_snapshot.filter_on = current_filter_enable;
            foc_current_trip_snapshot.median_count = current_med_count;
            foc_current_trip_snapshot.current_valid_count = current_valid_count;
            foc_current_trip_snapshot.current_reject_count = current_reject_count;
            foc_current_trip_snapshot.current_reject_streak = current_reject_streak;
            foc_current_trip_snapshot.last_rejected_step =
                current_last_rejected_sum_counts;
            foc_current_trip_snapshot.median_u[0] = current_med_u[0];
            foc_current_trip_snapshot.median_u[1] = current_med_u[1];
            foc_current_trip_snapshot.median_u[2] = current_med_u[2];
            foc_current_trip_snapshot.median_v[0] = current_med_v[0];
            foc_current_trip_snapshot.median_v[1] = current_med_v[1];
            foc_current_trip_snapshot.median_v[2] = current_med_v[2];
            foc_current_trip_snapshot.vbus_raw = analog_live_pc4_raw;
            foc_current_trip_snapshot.vbus_age_ms = vbus_age_ms;
            foc_current_trip_snapshot.analog_sample_count = analog_live_sample_count;
            foc_current_trip_snapshot.analog_error_count = analog_live_error_count;
            foc_current_trip_snapshot.vbus_valid =
                ((analog_live_valid != 0U) &&
                 (vbus_age_ms <= ANALOG_LIVE_FRESH_MS)) ? 1U : 0U;
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow_capture.inc"
#endif
            __DMB();
            foc_current_trip_snapshot.valid = 1U;
        }
        return;
    }

#if defined(FOC_CURRENT_TREND4)
    FocOcShadow_Push(&foc_oc_shadow, injected_seq_count,
        FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,FOC_CURRENT_TRIP_A),
        u_physical<=ADC_FULL_SCALE && v_physical<=ADC_FULL_SCALE);
#if defined(FOC_FILTERED_OBSERVE_ONLY)
    /* Available-output sequence, delayed one physical pair. No result here
     * authorizes PWM, and this observer never participates in a stop gate. */
    FocOcShadow_Push(&foc_filtered_oc_shadow, injected_seq_count,
        FocOcShadow_Mask(filtered_u_A,filtered_v_A,filtered_w_A,FOC_CURRENT_TRIP_A),1U);
#endif
#endif
#endif /* FOC_FEEDBACK_SAFETY_BINDING: legacy policy remains unchanged otherwise */
    FocProfile_Mark(FOC_PROF_OTHER);
    i_alpha = iu_A;
    i_beta = (iu_A + 2.0f * iv_A) * 0.57735026919f;

    theta = encoder_theta_e_pred;
#if defined(FOC_CURRENT_TREND4)
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    theta=cl_frame.measurement_angle;
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    theta = foc_feedback_control_frame.measurement_angle;
#else
    /* Park uses the angle estimate stored with the delayed center sample. */
    theta = current_trend4_angle.center;
#endif
#endif
#if defined(FOC_FAST_MATH)
    if (!FocFast_SinCos(theta,&s,&c)) {
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;
    }
#else
    s = sinf(theta);
    c = cosf(theta);
#endif

    id_A =  i_alpha * c + i_beta * s;
    iq_A = -i_alpha * s + i_beta * c;
    FocProfile_Mark(FOC_PROF_TRANSFORM);

    err_d = foc_id_ref_A - id_A;
    err_q = foc_iq_ref_A - iq_A;

    /*
     * PI controller:
     *   Kp ~= L*w_c = 0.08 V/A
     *   Ki ~= R*w_c = 188 V/(A*s)
     * for roughly 300 Hz initial current-loop bandwidth using the present
     * R ~= 0.10 ohm and L ~= 42.3 uH motor estimates.
     */
#if FOC_CURRENT_FAULT_TRACE_ENABLE
    FocCurrentTrace_Pi(); /* Diagnostic only: actual PI-update reachability. */
#endif
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

    FocProfile_Mark(FOC_PROF_PI);
    /* Inverse Park. */
#if defined(FOC_CURRENT_TREND4) && !defined(FOC_FAST_CURRENT_REJECT)
    /* Historical delayed feedback needs a second angle. Fast reject uses
     * this physical pair and the SAME angle, so reuse its checked sin/cos. */
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#if defined(FOC_FAST_MATH)
    if (!FocFast_SinCos(cl_frame.actuation_angle,&s,&c)) {
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;
    }
#else
    s=sinf(cl_frame.actuation_angle); c=cosf(cl_frame.actuation_angle);
#endif
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    s = sinf(foc_feedback_control_frame.actuation_angle);
    c = cosf(foc_feedback_control_frame.actuation_angle);
#else
    s = sinf(encoder_theta_e_pred);
    c = cosf(encoder_theta_e_pred);
#endif
#endif
    v_alpha = vd * c - vq * s;
    v_beta  = vd * s + vq * c;
    FocProfile_Mark(FOC_PROF_INVERSE);

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

    FocProfile_Mark(FOC_PROF_SVPWM);
    PWM_SetDuty(du, dv, dw);
    FocProfile_Mark(FOC_PROF_DUTY);

    foc_id_A = id_A;
    foc_iq_A = iq_A;
    foc_vd_V = vd;
    foc_vq_V = vq;

    foc_duty_u = du;
    foc_duty_v = dv;
    foc_duty_w = dw;

    /* Predict electrical angle at the 20 kHz current-loop rate. */
#if defined(FOC_FAST_CURRENT_REJECT)
    ProtectedLoop_AdvanceAngle();
#else
    encoder_theta_e_pred += encoder_omega_e_rad_s * FOC_TS_S;
    while (encoder_theta_e_pred >= TWO_PI_F) encoder_theta_e_pred -= TWO_PI_F;
    while (encoder_theta_e_pred < 0.0f) encoder_theta_e_pred += TWO_PI_F;
#endif

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

#if defined(AS5047P_SPI_DMA)
    AsDmaSample sample;
    uint32_t dt_us;
    if (!AS5047P_DmaGetSample(&sample)) return HAL_BUSY;
    uint32_t consume_now=AS5047P_DmaNowUs();
    int consumed = AsDma_Consume(&encoder_dma_cursor, &sample,consume_now,&dt_us);
    if (consumed == 0) return HAL_BUSY;
    if (consumed < 0)
    {
        encoder_error_count++;
        encoder_timeout_reason=FocEncoder_TimeoutReason(&encoder_dma_cursor,&sample,consume_now);
        EncoderDma_FaultFromISR();
        return HAL_ERROR;
    }
    raw = sample.raw;
    if (sample.errfl_valid) as5047p_last_errfl = sample.errfl;
    dt_s = (float)dt_us * 0.000001f;
    encoder_speed_dt_accum_s += dt_s;
#else
    if ((dt_s <= 0.0f) || (dt_s > 0.100f))
        dt_s = 0.001f;

    encoder_speed_dt_accum_s += dt_s;

    if (AS5047P_ReadAngle(&raw) != HAL_OK)
    {
        encoder_error_count++;
        encoder_valid = 0U;
        foc_fault_reason = 2U;
        foc_fault = 1U;
        PowerStage_Disable();
        FaultDiag_Motor(2U);
        return HAL_ERROR;
    }
#endif

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

        d_raw = AS5047P_Delta14(raw, encoder_prev_raw);

        if (dt_meas <= 0.0f)
            dt_meas = 0.001f;

        rpm_inst = AS5047P_InstantRpm(d_raw, ENCODER_DIRECTION, dt_meas);

        encoder_rpm_instant = rpm_inst;

        /*
         * Reject one impossible encoder jump without publishing it into the
         * control angle or speed estimator.
         */
        if (fabsf(rpm_inst) > SPEED_INSTANT_PLAUSIBLE_RPM)
        {
#if defined(FOC_SPEED_BRAKE_TRACK)
            SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
            encoder_speed_glitch_count++;
            encoder_speed_glitch_streak++;

            if (encoder_speed_glitch_streak >= SPEED_GLITCH_STREAK_LIMIT)
            {
                foc_fault_reason = 2U;
                foc_fault = 1U;
                encoder_valid = 0U;
                PowerStage_Disable();
                FaultDiag_Motor(2U);
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
            FaultDiag_Motor(3U);
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
#if defined(FOC_SPEED_BRAKE_TRACK)
            SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
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
#if defined(FOC_SPEED_BRAKE_TRACK)
        if (mode != MOTOR_MODE_SPEED) SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
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
#if defined(FOC_SPEED_BUMPLESS)
            /* Capture AFTER mode-change reset, BEFORE the legacy bleed can
             * mutate speed_integrator_A. SB2 must not subtract both bleeds. */
            float sb2_previous_A=speed_integrator_A;
#endif
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

#if defined(FOC_SPEED_STARTUP_BRAKE)
            if (mode == MOTOR_MODE_SPEED)
            {
#if defined(FOC_SPEED_BUMPLESS)
                SpeedStartupBrakeResult guarded=SpeedBumpless_Apply(
                    sb2_previous_A,i_candidate,speed_ref_rpm,encoder_speed_rpm,
                    dt_meas,SPEED_OVERSPEED_BLEED_ERR_RPM,SPEED_OVERSPEED_BLEED_MIN_SPD_RPM);
                i_candidate=guarded.integral_A;
                if (guarded.flags & SPEED_BUMPLESS_UNLOAD)
                    speed_overspeed_bleed_active=1U;
#else
                SpeedStartupBrakeResult guarded=SpeedStartupBrake_Apply(
                    speed_integrator_A,i_candidate,speed_ref_rpm,encoder_speed_rpm,
                    dt_meas,SPEED_OVERSPEED_BLEED_ERR_RPM,SPEED_OVERSPEED_BLEED_MIN_SPD_RPM);
                i_candidate=guarded.integral_A;
                if (guarded.flags & SPEED_STARTUP_I_BRAKE_RESET)
                    speed_overspeed_bleed_active=1U;
#endif
            }
#endif
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

#if defined(FOC_SPEED_BRAKE_TRACK)
            if (mode == MOTOR_MODE_SPEED) {
                SpeedBrakeTrackResult brake=SpeedBrakeTrack_Apply(&speed_brake_track,
                    speed_ref_rpm,encoder_speed_rpm,rpm_inst,p_term,speed_integrator_A,
                    iq_cmd,SPEED_KP_A_PER_RPM,SPEED_OVERSPEED_BLEED_ERR_RPM,
                    SPEED_OVERSPEED_BLEED_MIN_SPD_RPM,speed_iq_limit_A,SPEED_INT_LIMIT_A);
                if (brake.limited) {
                    speed_integrator_A=brake.integral_A;
                    speed_overspeed_bleed_active=1U;
                }
                iq_cmd=brake.current_A;
            }
#endif
            /* Publish once, after the SPEED-only ceiling, so an ADC IRQ
             * cannot consume the pre-limiter driving command in between. */
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
                    PowerStage_Disable(); /* Closure before diagnostic copies. */
                    FaultDiag_Capture(FOC_DIAG_MOTOR,4U,
                        mode==MOTOR_MODE_SPEED ? FOC_TO_STALL_SPEED : FOC_TO_STALL_POSITION,
                        tightening_test_elapsed_ms,0U);
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
#if defined(AS5047P_SPI_DMA)
    /* A timer fault can preempt publication. Never resurrect a failed sample. */
    if (foc_fault != 0U) { encoder_valid = 0U; return HAL_ERROR; }
    uint32_t sample_age_us = AS5047P_DmaNowUs() - sample.sample_us;
    if (sample_age_us > AS_DMA_SAMPLE_MAX_AGE_US)
    {
        EncoderDma_FaultFromISR();
        return HAL_ERROR;
    }
    /* Background DMA samples can be one task period old. Compensate their
     * age instead of resetting the 20 kHz predictor to a stale angle.
     * Existing 600 rpm / 10 pole-pair limit makes at most one wrap sufficient. */
    float predicted = theta_e + encoder_omega_e_rad_s * (float)sample_age_us * 0.000001f;
    if (!isfinite(predicted)) { EncoderDma_FaultFromISR(); return HAL_ERROR; }
    if (predicted >= TWO_PI_F) predicted -= TWO_PI_F;
    if (predicted < 0.0f) predicted += TWO_PI_F;
    encoder_theta_e_pred = predicted;
    encoder_valid = 1U;
    AS5047P_DmaAcknowledgeControl();
#else
    encoder_theta_e_pred = theta_e;
    encoder_valid = 1U;

#endif
    return HAL_OK;
}


static void PWM_StartAll(void)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    PowerStage_Disable(); TIM1->CCER=0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    PowerStage_Disable();
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    /* Internal CH4 trigger is started only by the bounded fixture. */
    PowerStage_Disable();
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    return;
#endif
    if (analog_safe_latched != 0U)
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }

#if defined(FOC_ADC_WINDOW)
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    if (adc_fault != 0U || !FocAdcTiming_CanStart())
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }
#else
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_2, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_3, PWM_HALF);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_4, ADC_TRIGGER_CCR4);
#endif

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
        UART_SendFormatted(dbg, sizeof(dbg),
                 "ZERO DBG %s: HAL_ADC_Stop st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    /* Internal VREFINT needs a longer acquisition window than GPIO inputs. */
    cfg.SamplingTime = (channel == ADC_CHANNEL_VREFINT)
                         ? ADC_SAMPLETIME_640CYCLES_5
                         : ADC_SAMPLETIME_47CYCLES_5;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0;

    st = HAL_ADC_ConfigChannel(hadc, &cfg);
    if (st != HAL_OK)
    {
        UART_SendFormatted(dbg, sizeof(dbg),
                 "ZERO DBG %s: ConfigChannel FAIL st=%d state=0x%08lX err=0x%08lX\r\n",
                 adc_name, (int)st,
                 (unsigned long)HAL_ADC_GetState(hadc),
                 (unsigned long)HAL_ADC_GetError(hadc));
        return HAL_ERROR;
    }

    for (uint32_t i = 0U; i < ADC_MEDIAN_SAMPLES; i++)
    {
        st = HAL_ADC_Start(hadc);
        if (st != HAL_OK)
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Start FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
            return HAL_ERROR;
        }

        st = HAL_ADC_PollForConversion(hadc, 10U);
        if (st != HAL_OK)
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Poll FAIL sub=%lu st=%d state=0x%08lX err=0x%08lX tick=%lu\r\n",
                     adc_name, (unsigned long)i, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc),
                     (unsigned long)HAL_GetTick());
            HAL_ADC_Stop(hadc);
            return HAL_ERROR;
        }

        x[i] = (uint16_t)HAL_ADC_GetValue(hadc);

        st = HAL_ADC_Stop(hadc);
        if ((st != HAL_OK) && (st != HAL_ERROR))
        {
            UART_SendFormatted(dbg, sizeof(dbg),
                     "ZERO DBG %s: Stop-after-read st=%d state=0x%08lX err=0x%08lX\r\n",
                     adc_name, (int)st,
                     (unsigned long)HAL_ADC_GetState(hadc),
                     (unsigned long)HAL_ADC_GetError(hadc));
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

    UART_SendLiteral(
        "\r\nTWO-PHASE CURRENT ZERO CALIBRATION\r\n"
        "CTRL_SD=LOW, PWM=OFF, PD6010B 12V must be ON\r\n"
        "AMP_IU->PA0/ADC1, AMP_IV->PA1/ADC2, PC3 unused\r\n");

    UART_SendLiteral("ZERO DBG: settling 1000 ms...\r\n");
    HAL_Delay(1000U);
    UART_SendLiteral("ZERO DBG: settle complete, starting ADC reads\r\n");

    for (uint32_t i = 0U; i < ADC_ZERO_CAL_SAMPLES; i++)
    {
        if (ADC_ReadRegularMedian(&hadc1, ADC_CHANNEL_1, &u) != HAL_OK)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG: ADC1 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            return HAL_ERROR;
        }

        if (ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_2, &v) != HAL_OK)
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG: ADC2 read failed at sample=%lu\r\n",
                     (unsigned long)i);
            return HAL_ERROR;
        }

        su += u;
        sv += v;

        if ((i == 0U) || (i == 99U) || (i == 249U) || (i == 499U))
        {
            UART_SendFormatted(msg, sizeof(msg),
                     "ZERO DBG sample=%lu U=%u V=%u tick=%lu\r\n",
                     (unsigned long)i,
                     (unsigned int)u,
                     (unsigned int)v,
                     (unsigned long)HAL_GetTick());
        }

        HAL_Delay(1U);
    }

    iu_zero_raw = (uint16_t)(su / ADC_ZERO_CAL_SAMPLES);
    iv_zero_raw = (uint16_t)(sv / ADC_ZERO_CAL_SAMPLES);

    UART_SendFormatted(msg, sizeof(msg),
             "ZERO DBG AVG: U=%u V=%u valid-range=1000..2200\r\n",
             (unsigned int)iu_zero_raw,
             (unsigned int)iv_zero_raw);

    /*
     * W is reconstructed, so this is only a numerical center for pseudo-raw W.
     * It is NOT a measurement from PC3.
     */
    iw_zero_raw = 2048U;

    if ((iu_zero_raw < 1000U) || (iu_zero_raw > 2200U) ||
        (iv_zero_raw < 1000U) || (iv_zero_raw > 2200U))
    {
        UART_SendLiteral(
            "ZERO DBG: average OUT OF RANGE. Check PD6010B 12V/current-sense outputs.\r\n");
        return HAL_ERROR;
    }

    UART_SendFormatted(msg, sizeof(msg),
             "ZERO CAL DONE\r\n"
             "U_ZERO_RAW=%u\r\n"
             "V_ZERO_RAW=%u\r\n"
             "W is reconstructed; PC3/AMP_IW is not used\r\n",
             iu_zero_raw,
             iv_zero_raw);
    return HAL_OK;
}

/*
 * Diagnostic only: ADC2 regular conversions run before the 20 kHz injected
 * IV conversion is armed.  ADC_ReadRegularMedian() stops ADC2 after each
 * reading, so it MUST NOT be called after injected sampling has started.
 * Report by MCU pin until the physical VBUS/VTEMP wire order is confirmed.
 */
static void ADC_AnalogBootSnapshot(void)
{
    GPIO_InitTypeDef gpio = {0};
    uint16_t pc4 = 0U;
    uint16_t pc5 = 0U;

    gpio.Pin = GPIO_PIN_4 | GPIO_PIN_5;
    gpio.Mode = GPIO_MODE_ANALOG;
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOC, &gpio);

    if ((ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_5, &pc4) == HAL_OK) &&
        (ADC_ReadRegularMedian(&hadc2, ADC_CHANNEL_11, &pc5) == HAL_OK))
    {
        analog_boot_pc4_raw = pc4;
        analog_boot_pc5_raw = pc5;
        __DMB();
        analog_boot_valid = 1U;
    }
    else
    {
        analog_boot_valid = 0U;
        UART_SendLiteral("ANALOG BOOT: ADC2 one-shot read unavailable\r\n");
    }
}

/*
 * ADC2 cannot sample VREFINT on STM32G474.  Read it once through ADC1 before
 * either ADC's 20 kHz injected conversion is armed.  The factory constant
 * estimates the board's VREF+/VDDA; this is display calibration only.
 */
static void ADC_VrefBootSnapshot(void)
{
    uint16_t raw = 0U;
    uint32_t vdda_mv = 0U;
    uint16_t factory_cal = *VREFINT_CAL_ADDR;

    if ((factory_cal == 0U) || (factory_cal == UINT16_MAX) ||
        (ADC_ReadRegularMedian(&hadc1, ADC_CHANNEL_VREFINT, &raw) != HAL_OK) ||
        (raw == 0U) || (raw >= ADC_FULL_SCALE))
    {
        analog_vdda_boot_valid = 0U;
        UART_SendLiteral("ANALOG VREF: calibration unavailable\r\n");
        return;
    }

    vdda_mv = __HAL_ADC_CALC_VREFANALOG_VOLTAGE(raw,
                                                ADC_RESOLUTION_12B);
    if ((vdda_mv < ANALOG_VDDA_MIN_MV) ||
        (vdda_mv > ANALOG_VDDA_MAX_MV))
    {
        analog_vdda_boot_valid = 0U;
        UART_SendLiteral("ANALOG VREF: VDDA estimate out of range\r\n");
        return;
    }

    analog_vref_boot_raw = raw;
    analog_vdda_boot_mv = (uint16_t)vdda_mv;
    analog_vdda_boot_valid = 1U;
}

/*
 * Regular ADC2 measurements may run while the independent injected channel
 * is armed.  Configure only SQR rank 1 here: HAL permits that when ADSTART
 * is clear even if JADSTART is set.  PC4/PC5 sampling times were configured
 * by ADC_AnalogBootSnapshot() before injected conversion started, because
 * sampling-time registers cannot be changed while JADSTART is active.
 *
 * Never call HAL_ADC_Stop() here: it also stops the injected IV conversion.
 * This is diagnostic only, not a motor-protection input.
 */
static HAL_StatusTypeDef ADC_AnalogLiveReadChannel(uint32_t channel,
                                                    uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};

    if ((ADC2->CR & ADC_CR_ADSTART) != 0U)
    {
        return HAL_BUSY;
    }

    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    cfg.SamplingTime = ADC_SAMPLETIME_47CYCLES_5;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    cfg.Offset = 0U;

    if (HAL_ADC_ConfigChannel(&hadc2, &cfg) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_Start(&hadc2) != HAL_OK)
    {
        return HAL_ERROR;
    }
    if (HAL_ADC_PollForConversion(&hadc2, 2U) != HAL_OK)
    {
        /* No Stop: leave injected IV sampling armed for the 20 kHz loop. */
        return HAL_TIMEOUT;
    }

    *raw = (uint16_t)HAL_ADC_GetValue(&hadc2);
    return HAL_OK;
}

static void ADC_AnalogTripleRecord(volatile AnalogTripleDiag_t *diag,
                                   uint16_t first, uint16_t second,
                                   uint16_t third)
{
    uint16_t lo = first;
    uint16_t mid = second;
    uint16_t hi = third;
    uint16_t tmp;

    if (lo > mid) { tmp = lo; lo = mid; mid = tmp; }
    if (mid > hi) { tmp = mid; mid = hi; hi = tmp; }
    if (lo > mid) { tmp = lo; lo = mid; mid = tmp; }

    taskENTER_CRITICAL();
    diag->last_first = first;
    diag->last_second = second;
    diag->last_third = third;
    diag->last_median = mid;
    if ((diag->count == 0U) || (hi > diag->peak_raw_value))
    {
        diag->peak_raw_value = hi;
        diag->peak_raw_first = first;
        diag->peak_raw_second = second;
        diag->peak_raw_third = third;
    }
    if ((diag->count == 0U) || (mid > diag->peak_median_value))
    {
        diag->peak_median_value = mid;
        diag->peak_median_first = first;
        diag->peak_median_second = second;
        diag->peak_median_third = third;
    }
    if ((hi - lo) > diag->max_spread) { diag->max_spread = hi - lo; }
    if ((hi - lo) > ANALOG_TRIPLE_DISAGREE_COUNTS) { diag->disagree_count++; }
    diag->last_tick_ms = HAL_GetTick();
    diag->count++;
    taskEXIT_CRITICAL();
}

static HAL_StatusTypeDef ADC_AnalogLiveSample(void)
{
    uint16_t pc4;
    uint16_t pc4_second = 0U;
    uint16_t pc4_third = 0U;
    uint16_t pc5;
    uint16_t pc5_second = 0U;
    uint16_t pc5_third = 0U;
    uint8_t pair_valid = 0U;
    uint8_t triple_valid = 0U;
    uint8_t pc5_triple_valid = 0U;

    if ((analog_boot_valid == 0U) ||
        (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4) != HAL_OK))
    {
        analog_live_valid = 0U;
        analog_live_error_count++;
        return HAL_ERROR;
    }

    /* Repeat PC4 without changing the mux while the gate is safely off.
     * Retain all raw values; the median is only diagnostic and does not
     * replace ANALOG VOLT or feed any motor-protection decision. */
    if (analog_safe_latched != 0U)
    {
        if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4_second) == HAL_OK)
        {
            pair_valid = 1U;
            if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_5, &pc4_third) == HAL_OK)
            {
                triple_valid = 1U;
            }
            else
            {
                taskENTER_CRITICAL();
                analog_triple_diag.errors++;
                taskEXIT_CRITICAL();
            }
        }
        else
        {
            taskENTER_CRITICAL();
            analog_pair_diag.errors++;
            analog_triple_diag.errors++;
            taskEXIT_CRITICAL();
        }
    }

    if (ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5) != HAL_OK)
    {
        analog_live_valid = 0U;
        analog_live_error_count++;
        if (analog_safe_latched != 0U) { analog_pc5_triple_diag.errors++; }
        return HAL_ERROR;
    }

    /* PC5 is the same-ADC control channel. Extra reads are SAFE-only;
     * keep the original first PC5 sample for ANALOG LIVE/VOLT. */
    if (analog_safe_latched != 0U)
    {
        if ((ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5_second) == HAL_OK) &&
            (ADC_AnalogLiveReadChannel(ADC_CHANNEL_11, &pc5_third) == HAL_OK))
        {
            pc5_triple_valid = 1U;
        }
        else
        {
            analog_pc5_triple_diag.errors++;
        }
    }

    if (pair_valid != 0U)
    {
        taskENTER_CRITICAL();
        analog_pair_diag.last_first = pc4;
        analog_pair_diag.last_second = pc4_second;
        if ((analog_pair_diag.count == 0U) ||
            (pc4 > analog_pair_diag.peak_first))
        {
            analog_pair_diag.peak_first = pc4;
            analog_pair_diag.peak_first_second = pc4_second;
        }
        if ((analog_pair_diag.count == 0U) ||
            (pc4_second > analog_pair_diag.peak_second))
        {
            analog_pair_diag.peak_second = pc4_second;
            analog_pair_diag.peak_second_first = pc4;
        }
        analog_pair_diag.count++;
        taskEXIT_CRITICAL();
    }

    if (triple_valid != 0U)
    {
        ADC_AnalogTripleRecord(&analog_triple_diag, pc4, pc4_second, pc4_third);
    }
    if (pc5_triple_valid != 0U)
    {
        ADC_AnalogTripleRecord(&analog_pc5_triple_diag, pc5, pc5_second, pc5_third);
    }

    analog_live_pc4_raw = pc4;
    analog_live_pc5_raw = pc5;
    analog_live_last_tick_ms = HAL_GetTick();
    analog_live_sample_count++;
    analog_live_valid = 1U;
    return HAL_OK;
}

static HAL_StatusTypeDef ADC_ConfigIndependentSameTrigger(void)
{
    ADC_MultiModeTypeDef multimode = {0};
    ADC_InjectionConfTypeDef inj = {0};

    /*
     * Use ADC1 and ADC2 independently, but arm both from the SAME
     * TIM1 TRGO2 rising edge.
     *
     * Both ADCs use the same asynchronous SYSCLK/4 ADC clock (42.5 MHz)
     * and the same 12.5-cycle
     * sample time, so IU and IV are sampled concurrently without relying on
     * the ADC dual-mode master/slave state machine.
     */
    if (!FocAdcClock_IsExpected())
        return HAL_ERROR;

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

    UART_SendLiteral(
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
        FocCurrentMedian_Begin(&run_zero_median);
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
            FaultDiag_Capture(FOC_DIAG_STARTUP,FOC_FAULT_STARTUP_ZERO_CAL,
                FOC_TO_STARTUP_ZERO,HAL_GetTick()-start_tick,RUN_ZERO_TIMEOUT_MS);
            run_zero_cal_active = 0U;
            UART_SendLiteral("TWO ADC RUN ZERO CAL TIMEOUT\r\n");
            return HAL_TIMEOUT;
        }
    }

    valid = run_zero_valid_count;
    rejected = run_zero_reject_count;
    sum_u = run_zero_sum_u;
    sum_v = run_zero_sum_v;

    if (valid == 0U)
        return HAL_ERROR;

    /* Validate candidate offsets before publishing either channel. */
    uint16_t candidate_u = (uint16_t)(sum_u / valid);
    uint16_t candidate_v = (uint16_t)(sum_v / valid);
    if ((candidate_u < 1000U) || (candidate_u > 2200U) ||
        (candidate_v < 1000U) || (candidate_v > 2200U))
    {
        UART_SendLiteral("TWO ADC RUN ZERO CAL INVALID\r\n");
        return HAL_ERROR;
    }
    {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        iu_zero_raw = candidate_u;
        iv_zero_raw = candidate_v;
        __DMB();
        __set_PRIMASK(mask);
    }

    UART_SendFormatted(
        msg,
        sizeof(msg),
        "TWO ADC RUN ZERO CAL DONE\r\n"
        "STATIC ZERO : U=%u V=%u\r\n"
        "RUN ZERO    : U=%u V=%u\r\n"
        "SHIFT(count): U=%ld V=%ld\r\n"
        "VALID=%lu REJECTED=%lu\r\n"
        "ZERO FILTER: " FOC_CURRENT_FILTER_NAME "; raw deviation gate unchanged\r\n"
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
#if defined(FOC_CURRENT_SPIKE_ONLY)
        FocCurrentMedian_Begin(&current_spike_filter);
#endif

        current_filter_enable = 1U;

        if (primask == 0U)
            __enable_irq();
    }

    UART_SendLiteral(
        "Two-ADC step filter ON: |dIU| or |dIV| > about 0.40A => hold last valid frame\r\n");

    return HAL_OK;
}


#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_adc_irq.inc"
#endif
void HAL_ADCEx_InjectedConvCpltCallback(ADC_HandleTypeDef *hadc)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    /* This profile has a separate early-ack entry. Unexpected HAL dispatch
     * must fail closed, not create a second filtering/completion owner. */
    (void)hadc;
    ProtectedLoop_EmergencyOff(CL_BAD_ADC);
    adc_fault=1U;
    __HAL_ADC_DISABLE_IT(&hadc1, ADC_IT_JEOS | ADC_IT_JEOC);
    __HAL_ADC_DISABLE_IT(&hadc2, ADC_IT_JEOS | ADC_IT_JEOC);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    if (hadc->Instance == ADC1) ZeroRetest_InjectedPair();
    return; /* Never reach current filters, encoder, or FOC in this profile. */
#endif
    /*
     * ADC1 owns the interrupt callback. ADC1 and ADC2 are independent ADCs,
     * but both are armed by the same TIM1 TRGO2 edge with identical sampling
     * time, so ADC2 JDR1 belongs to the same PWM sampling event.
     */
    if (hadc->Instance == ADC1)
    {
#if defined(FOC_ADC_WINDOW)
        if (!FocAdcTiming_PairReady())
        {
#if defined(FOC_PROTECTED_CLOSED_LOOP)
            ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
            FocFeedbackBinding_EmergencyOff(FOC_FP_ADC_INVALID);
#endif
            adc_fault = 1U;
            foc_enable = 0U;
            foc_fault = 1U;
            foc_fault_reason = FOC_FAULT_ADC_WINDOW;
            DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
            TIM1->BDTR &= ~TIM_BDTR_MOE;
            FaultDiag_Motor(FOC_FAULT_ADC_WINDOW);
            __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
            /* A late ADC2 completion must not masquerade as next cycle's
             * result. Latch off the completion chain until a fresh boot. */
            __HAL_ADC_DISABLE_IT(&hadc1, ADC_IT_JEOS | ADC_IT_JEOC);
            __DSB();
            return;
        }
#endif
        uint16_t u = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc1, ADC_INJECTED_RANK_1);

        uint16_t v = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc2, ADC_INJECTED_RANK_1);

        /*
         * ADC2 is intentionally used without an ADC2 interrupt. Reading JDR1
         * consumes its JEOC result; clear JEOS as housekeeping after the read.
         */
        __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
#if defined(FOC_ADC_WINDOW)
        FocAdcTiming_RecordRaw(u, v); /* before median/step filtering */
#endif

        injected_seq_count++;
#if defined(FOC_ISOLATED_CONCURRENCY)
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        if (!FocFeedbackBinding_PhysicalSeen(u, v)) return;
#endif
        if (IsolatedZero_Feed(u, v)) return;
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        /* Single filtering/protection owner; never also run the legacy filter. */
        uint32_t feedback_start_us = foc_feedback_last_us;
        if (FocFeedbackBinding_Control(u, v)) {
            iu_inj_raw = foc_feedback_control_frame.u;
            iv_inj_raw = foc_feedback_control_frame.v;
            current_valid_count++;
            FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v);
        }
        FocFeedbackBinding_WorkEnd(feedback_start_us);
        return;
#endif

        /*
         * PWM-on zero calibration uses only the two physically measured
         * simultaneous currents.
         */
        if (run_zero_cal_active != 0U)
        {
            uint16_t filtered_u = 0U, filtered_v = 0U;
            int admission = FocRunZeroMedian_Push(&run_zero_median, u, v,
                iu_zero_raw, iv_zero_raw, RUN_ZERO_MAX_DELTA_COUNTS,
                &filtered_u, &filtered_v);
            if (admission > 0)
            {
                run_zero_sum_u += filtered_u;
                run_zero_sum_v += filtered_v;
                run_zero_valid_count++;

                if (run_zero_valid_count >= RUN_ZERO_CAL_SAMPLES)
                {
                    run_zero_cal_active = 0U;
                    run_zero_cal_done = 1U;
                }
            }
            else if (admission < 0)
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

#if defined(FOC_CURRENT_SPIKE_ONLY)
#if defined(FOC_CURRENT_TREND4)
                FocTrend4Angle_Push(&current_trend4_angle, encoder_theta_e_pred);
#endif
#include "foc_current_spike_runtime.inc"
#if defined(FOC_CURRENT_TREND4)
                if (spike_ready && spike_u<=ADC_FULL_SCALE &&
                    spike_v<=ADC_FULL_SCALE && adc_fault==0U) {
                    foc_trend_pairs=FocOcShadow_Inc(foc_trend_pairs);
                    if (current_spike_filter.last_spike_mask) foc_trend_changed=FocOcShadow_Inc(foc_trend_changed);
                    if (current_spike_filter.last_spike_mask & 1U) foc_trend_u_changed=FocOcShadow_Inc(foc_trend_u_changed);
                    if (current_spike_filter.last_spike_mask & 2U) foc_trend_v_changed=FocOcShadow_Inc(foc_trend_v_changed);
                }
#endif
#else
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
#endif
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
#if defined(FOC_ISOLATED_CONCURRENCY)
            if (IsolatedBench_Active() && (run_zero_cal_active == 0U))
#else
            if ((foc_enable != 0U) && (run_zero_cal_active == 0U))
#endif
            {
#if defined(FOC_CURRENT_TREND4)
                /* No PI update on the three startup history pairs. */
                if (current_spike_filter.count < FOC_CURRENT_HISTORY_PAIRS ||
                    adc_fault != 0U) return;
#endif
                FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v);
            }
        }
    }
}


void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FP_ADC_INVALID);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    SwitchFeedback_EmergencyOff(8U);
#endif
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    AdcDmaDiag_Error(hadc);
#endif
    if ((hadc->Instance == ADC1) || (hadc->Instance == ADC2))
    {
        adc_fault = 1U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                          DRIVER_SD_Pin,
                          GPIO_PIN_RESET);
        FaultDiag_Motor(FOC_FAULT_ADC_CHAIN_STALE);
    }
}
/* USER CODE END 0 */

#if defined(CAN_STATUS_TELEMETRY)
/*
 * The current-sense amplifiers can be unpowered while the MCU remains on.
 * A failed zero calibration must prevent motor start, but it must not make
 * the upper computer mistake a safe, diagnosed fault for a broken CAN wire.
 * This task never starts PWM, the motor tasks, or the command protocol.
 * Restoring the amplifier supply requires a fresh boot and calibration.
 */
static void StartupZeroCalFaultCommsLoop(void)
{
    PowerStage_Disable();
    PWM_StopAll();
    foc_enable = 0U;
    foc_fault = 1U;
    foc_fault_reason = FOC_FAULT_STARTUP_ZERO_CAL;
    FaultDiag_Capture(FOC_DIAG_STARTUP,FOC_FAULT_STARTUP_ZERO_CAL,FOC_TO_NONE,
        tightening_test_elapsed_ms,0U);
    adc_fault = 1U;
    motor_control_mode = MOTOR_MODE_IDLE;

    (void)CAN_StatusTx_Init();
    for (;;)
    {
        PowerStage_Disable();
        FaultDiag_Monitor(); /* No MonitorTask is created on this failure path. */
        CAN_StatusTx_Service(HAL_GetTick());
        CAN_StatusTx_Publish(MOTOR_MODE_IDLE,
                             CAN_STATUS_FLAG_FAULT_LATCHED,
                             FOC_FAULT_STARTUP_ZERO_CAL);
        CAN_StatusTx_PublishMotor(0.0f, 0.0f, 0U, 0U);
        CAN_StatusTx_PublishElectrical(0U, 0.0f, 0U, 0U);
        vTaskDelay(pdMS_TO_TICKS(100U));
    }
}
#endif


#if defined(ZERO_RETEST_BOOT)
#include "zero_retest_boot.inc"
#endif
#if defined(SAFETY_LOCKED_BOOT)
#include "safety_locked_boot.inc"
#endif

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
    g_uart_async_runtime_enable = 0U;
#if defined(ZERO_RETEST_BOOT)
    ZeroRetest_RunForever();
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    analog_safe_latched = 1U;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    PowerStage_Disable();
#endif
#if defined(SAFETY_LOCKED_BOOT)
    /* Before KVS migration, encoder checks, PWM, calibration or command tasks. */
    SafetyLockedBoot_RunForever();
#endif

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
    FaultDiag_Clear();
    adc_fault = 0U;

    UART_SendLiteral(
        "\r\n"
        "==========================================\r\n"
        "FreeRTOS generic motor-control API + TighteningTask test\r\n"
        "APP SLOT: B @ 0x08040000\r\n"
        "IAP FW V4 build: bootloader-owned metadata commit + V3 dual-copy\r\n"
        "StartupTask active\r\n"
        "Power stage starts DISABLED\r\n"
        "==========================================\r\n");

    {
        TightenParamsFlashLoadStatus_t param_load_status;
        char param_msg[160];

        recipe_state.kvs_ready =
            (PW_Kvs_Init() == PW_KVS_RESULT_OK) ? 1U : 0U;
        param_load_status = TightenParams_LoadFromFlash();

        if (param_load_status == PARAM_FLASH_LOAD_OK)
        {
            UART_SendFormatted(
                param_msg,
                sizeof(param_msg),
                "PARAM KVS: LOADED CRC32=0x%08lX RUNDOWN_RPM=%lu MIGRATED=%u\r\n",
                (unsigned long)recipe_state.last_crc32,
                (unsigned long)recipe_state.params.rundown_rpm,
                (unsigned int)recipe_state.kvs_migrated);
        }
        else
        {
            TightenParams_ResetDefaults(&recipe_state.params);
            recipe_state.flash_valid = 0U;
            recipe_state.dirty = 0U;
            recipe_state.last_crc32 = 0U;

            UART_SendFormatted(
                param_msg,
                sizeof(param_msg),
                "PARAM KVS: NO VALID RECORD -> DEFAULTS RUNDOWN_RPM=%lu\r\n",
                (unsigned long)recipe_state.params.rundown_rpm);
        }

    }

    /*
     * 1) ADC hardware calibration.
     */
    if (HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendLiteral("ADC1 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_Calibration_Start(&hadc2, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendLiteral("ADC2 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    /*
     * 2) Static current zero with bridge disabled / PWM stopped.
     */
#if defined(FOC_ISOLATED_CONCURRENCY) || defined(FOC_PROTECTED_CLOSED_LOOP)
    /* No regular-ADC baseline: qualify zero using the actual injected chain. */
#else
    if (ADC_CurrentZeroCalibrate() != HAL_OK)
    {
        UART_SendLiteral("STATIC CURRENT ZERO CAL FAILED\r\n");
#if defined(CAN_STATUS_TELEMETRY)
        UART_SendLiteral("MOTOR LOCKED; CAN fault telemetry active until reboot\r\n");
        StartupZeroCalFaultCommsLoop();
#endif
        Error_Handler();
    }
#endif

    ADC_AnalogBootSnapshot();
    ADC_VrefBootSnapshot();

    /*
     * 3) Encoder sanity check.
     */
    if (AS5047P_StartupCheck() != HAL_OK)
    {
        UART_SendLiteral(
            "AS5047P STARTUP CHECK FAILED - POWER STAGE STAYS OFF\r\n");
        PowerStage_Disable();
        Error_Handler();
    }

    /*
     * 4) Configure and arm the 20 kHz injected ADC chain.
     */
    if (ADC_ConfigIndependentSameTrigger() != HAL_OK)
    {
        UART_SendLiteral("ADC1/ADC2 SAME-TRIGGER CONFIG ERROR\r\n");
        Error_Handler();
    }

    UART_SendLiteral(
        "ADC1/ADC2 independent same-trigger mode configured\r\n"
        "Both injected groups use TIM1 TRGO2 rising edge\r\n");

#if defined(FOC_ADC_WINDOW)
    if (!FocAdcStatisticsTask_Start())
    {
        PowerStage_Disable();
        PWM_StopAll();
        UART_SendLiteral("ADC statistics static task CREATE FAILED\r\n");
        Error_Handler();
    }
#endif
    if (HAL_ADCEx_InjectedStart(&hadc2) != HAL_OK)
    {
        UART_SendLiteral("ADC2 INDEPENDENT INJECTED ARM ERROR\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_InjectedStart_IT(&hadc1) != HAL_OK)
    {
        UART_SendLiteral("ADC1 INDEPENDENT INJECTED START ERROR\r\n");
        Error_Handler();
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    if (!ProtectedLoop_Init()) {
        UART_SendLiteral("PROTECTED MOTOR ZERO FAILED: output locked; no retry\r\n");
        ProtectedLoop_EmergencyOff(CL_BAD_ZERO);
    }
#elif defined(FOC_ISOLATED_CONCURRENCY)
    if (!IsolatedBench_Start(30000U))
    {
        UART_SendLiteral("ISOLATED BENCH START FAILED\r\n");
        IsolatedZero_Fail(FOC_ZERO_BAD_CONFIG);
    }
#else
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PWM_StartAll();
#endif

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    UART_SendLiteral("PROTECTED MOTOR: boot outputs OFF; internal trigger only\r\n");
#elif defined(FOC_ISOLATED_CONCURRENCY)
    UART_SendLiteral("Internal trigger only; physical outputs remain disabled\r\n");
#else
    UART_SendLiteral(
        "PWM started at 50/50/50\r\n"
        "Checking 20kHz ADC injected chain...\r\n");
#endif

    seq_start = injected_seq_count;
    vTaskDelay(pdMS_TO_TICKS(100U));
    seq_delta = injected_seq_count - seq_start;

    UART_SendFormatted(msg, sizeof(msg),
             "Injected IRQ count/100ms=%lu\r\n",
             (unsigned long)seq_delta);

#if defined(FOC_ISOLATED_CONCURRENCY) || defined(FOC_PROTECTED_CLOSED_LOOP)
    /* 100 ms should contain 2000 pairs; do not qualify a much slower chain. */
    if (seq_delta < 1800U || seq_delta > 2200U)
#else
    if (seq_delta < 500U)
#endif
    {
        UART_SendLiteral("ERROR: injected trigger/IRQ count too low\r\n");
        PowerStage_Disable();
        PWM_StopAll();
#if defined(FOC_PROTECTED_CLOSED_LOOP)
        /* Keep the faulted read-only console available; boot health refuses
         * confirmation and uses the existing bounded rollback path. */
        ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#elif defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedZero_Fail(FOC_ZERO_RATE);
#else
        Error_Handler();
#endif
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    UART_SendLiteral(cl_session.state==CL_READY ?
#if defined(FOC_LATEST_ORIGINAL_FSM)
        "LATEST BACKEND / ORIGINAL FSM: explicit local START; 20 rpm / 400 ms qualification envelope; no boot actuation\r\n" :
#else
        "PROTECTED MOTOR READY: local MOTOR TEST SPEED only; 20 rpm / 400 ms; no boot actuation\r\n" :
#endif
        "PROTECTED MOTOR LOCKED: startup failed, no power admission\r\n");
#elif defined(FOC_ISOLATED_CONCURRENCY)
    IsolatedZero_Wait();
    UART_SendLiteral("ISOLATED CONCURRENCY: compute only; SD=MOE=CCER=0; 30s boot fixture\r\n");
#else
    /*
     * 5) Enable the bridge ONLY with all three PWM duties at 50%.
     *    Equal phase commands mean zero commanded line-line voltage.
     */
    foc_enable = 0U;
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PowerStage_Enable();

    UART_SendLiteral(
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
        UART_SendLiteral("PWM-ON RUN ZERO CAL ERROR\r\n");
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
            UART_SendLiteral("ENCODER READ FAILED BEFORE FOC ENABLE\r\n");
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
    FaultDiag_Clear();
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

    UART_SendLiteral(
        "\r\n"
        "==========================================\r\n"
        "GENERIC MOTOR-CONTROL API ENABLED\r\n"
        "Current loop    : ADC ISR @ 20kHz\r\n"
        "Motor control   : MotorControlTask @ 1kHz\r\n"
        "Application     : TighteningTask @ 100Hz, command-driven\r\n"
        "Router          : Stage3 dynamic RouterTask @ 5ms, LOCAL + UART1\r\n"
        "Discovery       : HELLO/ANNOUNCE 5s + node/route aging 15s\r\n"
        "Loop guard      : TTL + duplicate cache + reflected-self suppression\r\n"
        "Reply routing   : routed Protocol request -> routed synchronous reply\r\n"
        "Protocol        : Router LOCAL packet queue -> ProtocolTask @ 5ms\r\n"
        "Monitor         : 3s IDLE / 1s ACTIVE\r\n"
        "UART TX runtime : DMA1_CH1 + 8KiB ring\r\n"
        "UART RX runtime : DMA1_CH2 circular + 512B RX ring\r\n"
        "Protocol V2     : <REQ_ID> <COMMAND>, correlated replies\r\n"
        "Parameters      : GET/SET + pw_kvs dual-copy wear leveling + CRC\r\n"
        "IAP FW          : inactive-slot write + CRC32 + pending trial\r\n"
        "Boot health     : 5s continuous gate + auto confirm + fail reset\r\n"
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
        "Phase trip      : 4.0A; powered validation pending\r\n"
        "==========================================\r\n");

#endif
#if defined(FOC_ORIGINAL_CLOSED_LOOP_UPDATED)
    {
        static char profile[256];
        OriginalClosedLoop_FormatProfile(profile, sizeof(profile),
            (uint32_t)(FOC_CURRENT_TRIP_A * 1000.0f + 0.5f), RUN_ZERO_MAX_DELTA_COUNTS,
            (uint32_t)(FOC_TS_S * 1000000.0f + 0.5f),
            (uint32_t)(MOTOR_SPEED_IQ_LIMIT_A * 1000.0f + 0.5f),
            (uint32_t)(MOTOR_DIRECT_IQ_LIMIT_A * 1000.0f + 0.5f),
            (uint32_t)(FOC_VOLTAGE_LIMIT_V * 1000.0f + 0.5f));
        UART_SendString(profile);
    }
#endif
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

            UART_SendLiteral(
                "UART ASYNC TX: initialized; runtime gate opens after StartupTask exits\r\n");
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
        UART_SendLiteral(
            "WARNING: UART RX DMA init failed; commands unavailable\r\n");
    }
    else
    {
        UART_SendLiteral(
            "UART RX DMA: DMA1_CH2 circular + RX ring READY\r\n");
    }

    /*
     * Router Core owns transport ingress. ProtocolTask now consumes only the
     * LOCAL endpoint queue, so legacy commands remain compatible while routed
     * packets can later arrive from UART/USB/Socket adapters.
     */
    if (Router_Init(ROUTER_LOCAL_NODE_ID) == 0U)
    {
        UART_SendLiteral("Router_Init FAILED\r\n");
        Error_Handler();
    }

    Router_RegisterPortTx(
        ROUTER_PORT_UART1,
        Router_Uart1Tx);

    /* Optional, independent ESP32-S3 discovery link. USART1 PA9/PA10 does
     * not share COM5, the RS485 relay UART, or the 20 kHz FOC interrupt. */
    if (EspLink_Init() != 0U)
    {
        if (xTaskCreate(EspLink_Task,
                        "EspLink",
                        512U,
                        NULL,
                        1U,
                        NULL) == pdPASS)
        {
            Router_RegisterPortTx(ROUTER_PORT_ESP32,
                                  EspLink_RouterTx);
            UART_SendLiteral(
                "ESP32 LINK: USART1 PA9/PA10 115200 8N1, discovery-only READY\r\n");
        }
        else
        {
            EspLink_Deinit();
            UART_SendLiteral("ESP32 LINK: task unavailable; link disabled\r\n");
        }
    }
    else
    {
        UART_SendLiteral("ESP32 LINK: init unavailable; link disabled\r\n");
    }

    protocol_async_event_queue = xQueueCreate(
        PROTOCOL_ASYNC_EVENT_QUEUE_DEPTH,
        sizeof(ProtocolAsyncEvent_t));

    if (protocol_async_event_queue == NULL)
    {
        UART_SendLiteral("Protocol async event queue CREATE FAILED\r\n");
        Error_Handler();
    }

    modbus_request_queue = xQueueCreate(MODBUS_QUEUE_DEPTH,
                                         sizeof(ModbusJob_t));
    modbus_completion_queue = xQueueCreate(MODBUS_QUEUE_DEPTH,
                                            sizeof(ModbusCompletion_t));
    if ((modbus_request_queue == NULL) || (modbus_completion_queue == NULL))
    {
        UART_SendLiteral("Modbus queues CREATE FAILED\r\n");
        Error_Handler();
    }

    memset(protocol_reliable_events, 0, sizeof(protocol_reliable_events));
    memset(protocol_reliable_rx_cache, 0, sizeof(protocol_reliable_rx_cache));
    protocol_reliable_next_eid = 1U;
    protocol_reliable_rx_cache_cursor = 0U;

    UART_SendLiteral(
        "ROUTER CORE STAGE3 + RELIABLE ASYNC EVT STAGE4.3: NODE=1 LOCAL,UART1 READY\r\n");

    /*
     * High-priority deterministic motor-control task.
     */
    if (xTaskCreate(MotorControlTask,
                    "MotorCtrl",
                    768U,
                    NULL,
                    4U,
                    &motor_control_task_handle) != pdPASS)
    {
        UART_SendLiteral("MotorControlTask CREATE FAILED\r\n");
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
        UART_SendLiteral("TighteningTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Transport ingress and packet forwarding. RouterTask owns UART RX DMA
     * consumption; ProtocolTask no longer reads the UART ring directly.
     */
    if (xTaskCreate(RouterTask,
                    "Router",
#if defined(ROUTER_READ_ONLY_NETWORK)
                    /* Hardware acceptance: 2 KiB overflowed while formatting
                     * a diagnostic reply plus R1 TX. Cortex-M4 units = words.
                     * Reserve 4 KiB; measure the stack margin under live load. */
                    1024U,
#else
                    512U,
#endif
                    NULL,
                    2U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("RouterTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Local protocol endpoint. Same priority as Router/UartTx and below the
     * application and motor-control tasks.
     */
    if (xTaskCreate(ProtocolTask,
                    "Protocol",
                    1024U,
                    NULL,
                    2U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("ProtocolTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

#if defined(TIGHTEN_SYNTHETIC_BENCH)
    synthetic_task_handle = xTaskCreateStatic(SyntheticTask, "Synthetic", 1024U,
                    NULL, 1U, synthetic_task_stack, &synthetic_task_tcb);
    if (synthetic_task_handle == NULL)
    {
        UART_SendLiteral("SyntheticTask CREATE FAILED\r\n");
        IsolatedBench_Stop(3U);
        Error_Handler();
    }
    UART_SendLiteral("SYNTHETIC FIXTURE READY: local SIM commands; MODEL ONLY; no motor output\r\n");
#endif
    /* Low-priority owner of USART3; only results return to ProtocolTask. */
    if (xTaskCreate(ModbusTask,
                    "Modbus",
                    512U,
                    NULL,
                    0U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("ModbusTask CREATE FAILED\r\n");
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
        UART_SendLiteral("MonitorTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Pending/trial firmware gets a continuous health window before it may
     * become confirmed.
     */
    if (xTaskCreate(BootHealthTask,
                    "BootHealth",
                    512U,
                    NULL,
                    1U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("BootHealthTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Still use blocking UART for this final StartupTask line. Only after it
     * has been emitted do we arm the runtime async path, then immediately
     * delete this priority-5 task so the lower-priority UART TX service can
     * actually run.
     */
    UART_SendLiteral(
        "StartupTask complete -> MotorControlTask + TighteningTask + RouterTask + ProtocolTask + MonitorTask + BootHealthTask + PwLogTask running\r\n");

    if (PW_Log_Init() == 0)
    {
        UART_SendLiteral("PW LOG INIT FAILED\r\n");
    }
    else if (PW_LogRouter_Init() == 0)
    {
        UART_SendLiteral("PW LOG ROUTER INIT FAILED\r\n");
    }
    g_uart_async_runtime_enable = 1U;
#if defined(CAN_LOG_STREAM)
    if (PW_CanLog_Init() == 0U) UART_SendLiteral("PW CAN LOG INIT FAILED\r\n");
#endif
    PW_SmokeTest();
    (void)PW_Allocator_RunSelfTest();
    PW_UnitTestsRun();
    PW_ThreadSmokeStart();
    PW_Rpc_Init();
#if defined(UART_FIRMWARE_TRANSFER)
    PW_UartFirmwareTransfer_Init();
#endif
#if defined(CAN_RPC_READ_ONLY)
    if (!PW_CanRpc_Init()) UART_SendLiteral("CAN READONLY RPC INIT FAILED\r\n");
#endif
    vTaskDelete(NULL);
}

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */
  EncoderDiag_InitCycleCounter();
  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
  AdcControlPins_InitLow(); /* Diagnostic only, before ADC/tasks; never restore AF. */
#endif
  MX_SPI1_Init();
#if defined(AS5047P_SPI_DMA)
  if (!AS5047P_DmaInit(EncoderDma_FaultFromISR))
  {
      PowerStage_Disable();
      Error_Handler();
  }
#endif
  MX_LPUART1_UART_Init();
  MX_ADC1_Init();
  MX_ADC2_Init();
  /* USER CODE BEGIN 2 */

#if defined(CAN_LINK_PROBE_ONLY)
    /* This build never starts TIM1 PWM, ADC injected conversions, FreeRTOS,
     * motor-control tasks or the bridge. PC6 is forced low before CAN runs. */
    PowerStage_Disable();
    CAN_LinkProbe_RunForever(&hlpuart1);
#endif

    /*
     * Start FreeRTOS BEFORE running any startup helper that uses HAL_Delay().
     * StartupTask performs ADC calibration, encoder check, TIM1/ADC bring-up,
     * and then creates MotorControlTask, TighteningTask and MonitorTask.
     */
    PowerStage_Disable();

    UART_SendLiteral(
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
        UART_SendLiteral("StartupTask CREATE FAILED\r\n");
        Error_Handler();
    }

    UART_SendLiteral("Starting scheduler...\r\n");

    vTaskStartScheduler();

    /* A correctly running scheduler never returns here. */
    UART_SendLiteral("ERROR: scheduler returned\r\n");
    PowerStage_Disable();
    PWM_StopAll();
    Error_Handler();

    /* No legacy motor demo after scheduler failure. */
  /* USER CODE END 2 */

  /* Fail-closed fallback if Error_Handler is ever changed to return. */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */
    /* USER CODE BEGIN 3 */
  }
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
  hadc1.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;
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
  hadc2.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;
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
  hlpuart1.Init.BaudRate = UART_LOG_BAUD;
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
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_CORE_FAULT);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    SwitchFeedback_EmergencyOff(9U);
#endif
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

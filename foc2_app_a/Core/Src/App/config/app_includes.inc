/* App A config/app_includes.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
#include "main.h"
#include "foc_fast_path_profile.h"
#if defined(FOC_BEMF_CANDIDATE)
#include "foc_bemf_feedforward.h"
static volatile uint8_t bemf_enabled=FOC_BEMF_ENABLED_DEFAULT;
#if defined(FOC_BEMF_GAIN_DIAG)
static volatile uint32_t bemf_gain_percent=0U;
#endif
static volatile FocBemfFrame bemf_frame;
static uint8_t Bemf_Command(const char *cmd,char *out,size_t size);
#if defined(FOC_PSI_IDENT_DIAG)
#include "psi_ke_identification.h"
static PsiIdentification psi_ident;
static uint8_t PsiIdent_Command(const char *cmd,char *out,size_t size);
#endif
#endif
#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
#include "foc_dq_decoupling.h"
static volatile uint8_t dq_decoupling_enabled=FOC_DQ_DECOUPLING_ENABLED_DEFAULT;
static volatile FocDqDecouplingFrame dq_decoupling_frame;
static uint8_t DqDecoupling_Command(const char *cmd,char *out,size_t size);
#if defined(FOC_DQ_AUDIT_ENABLE)
#include "foc_dq_audit.h"
static volatile FocDqAudit dq_audit;
static void DqAudit_Monitor(void);
#endif
#endif
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
#include "speed_scurve.h"
static SpeedScurve speed_scurve;
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
#include "speed_accel_feedforward.h"
static uint8_t speed_accel_ff_enabled=FOC_ACCEL_FF_ENABLED_DEFAULT;
static SpeedAccelFfFrame speed_accel_ff_frame;
static SpeedAccelFfStats speed_accel_ff_stats;
#if defined(FOC_MECHANICAL_IDENT_DIAG)
#include "mechanical_identification.h"
static volatile MechanicalCurrent mechanical_current;
static MechanicalCapture mechanical_capture;
#if defined(FOC_MECHANICAL_DOB_SHADOW)
#include "mechanical_dob_monitor.h"
static MechanicalDobMonitor mechanical_dob_monitor;
#if defined(FOC_DOB_REAL_TRACE)
#include "dob_real_trace.h"
#endif
#if defined(FOC_DOB_TREND_SHADOW)
#if defined(FOC_DOB_TREND_CONTINUOUS)
#include "dob_trend_continuous.h"
#if defined(FOC_DOB_RECOVERY_TIMING)
#include "dob_recovery_timing.h"
#endif
#else
#include "dob_trend_shadow.h"
#endif
#endif
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
#if defined(FOC_DOB_GAIN_AB_DIAG)
static float dob_gain_ab=.25f; /* RAM only; task changes with every output OFF. */
#undef DOB_FB_GAIN
#define DOB_FB_GAIN dob_gain_ab
#endif
#include "dob_feedback_candidate.h"
#if defined(FOC_DOB_NORMAL_CONTROL)
#include "dob_normal_control.h"
#if defined(FOC_DOB_REAL_TRACE) || defined(FOC_DOB_TREND_SHADOW)
static DobFeedbackCandidate dob_feedback; /* Passive acquisition: default OFF. */
#else
static DobFeedbackCandidate dob_feedback={.enabled=1U}; /* No motor auto-start. */
#endif
#else
static DobFeedbackCandidate dob_feedback; /* Runtime OFF until guarded command. */
#endif
#endif
#if defined(FOC_DOB_ID_TRACE)
#include "dob_id_trace.h"
#endif
#if defined(FOC_ID_STEADY_STATS)
#include "id_steady_stats.h"
static IdSteadyStats id_steady_stats;
#endif
#endif
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
#include "outer_completion_trace.h"
static OuterCompletionTrace outer_completion_trace;
static struct {
    MechanicalCurrent current;
    uint32_t observed_us,sample_us,dt_us;
    int32_t delta;
    float dt_s,omega_rad_s,friction_a;
    uint8_t pending,valid,saturated;
} outer_observation;
static void OuterObservation_Flush(void);
#endif
#endif
#if defined(FOC_KA_SYNC_DIAG) || defined(FOC_KA_FULL_DIAG)
#include "ka_sync_diagnostic.h"
static volatile KaSyncCurrent ka_sync_current;
#if defined(FOC_KA_FULL_DIAG)
#include "ka_full_diagnostic.h"
static KaFullDiagnostic ka_full_diagnostic;
#else
static KaSyncDiagnostic ka_sync_diagnostic;
#endif
#endif
#if defined(FOC_KA_IDENT_DIAG)
#include "ka_identification.h"
static KaIdentification ka_identification;
#endif
#if defined(FOC_ACCEL_FF_AUDIT)
#include "speed_accel_audit.h"
static SpeedAccelAudit speed_accel_audit;
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
#include "startup_timestamps.h"
static StartupTimestamps startup_timestamps;
#endif
static float speed_accel_audit_ka=SPEED_ACCEL_FF_KA_A_PER_RPM_S;
#define SPEED_ACCEL_EFFECTIVE_KA speed_accel_audit_ka
#else
#define SPEED_ACCEL_EFFECTIVE_KA SPEED_ACCEL_FF_KA_A_PER_RPM_S
#endif
static void SpeedAccelFf_Reset(void);
static void SpeedAccelFf_Monitor(void);
static uint8_t SpeedAccelFf_Command(const char *cmd,char *out,size_t size);
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
#include "speed_friction_compensation.h"
static uint8_t speed_friction_enabled=FOC_FRICTION_ENABLED_DEFAULT;
static SpeedFrictionFrame speed_friction_frame;
static SpeedFrictionStats speed_friction_stats;
static void SpeedFriction_Reset(void);
#if !defined(FOC_ACCEL_FF_AUDIT) && !defined(FOC_KA_IDENT_DIAG) && !defined(FOC_KA_SYNC_DIAG) && !defined(FOC_KA_FULL_DIAG)
static void SpeedFriction_Monitor(void);
#endif
static uint8_t SpeedFriction_Command(const char *cmd,char *out,size_t size);
#endif
#if defined(FOC_FRICTION_CALIBRATION_DIAG)
#include "friction_calibration.h"
static FrictionCalibration friction_calibration;
static uint8_t FrictionCalibration_Command(const char *cmd,char *out,size_t size);
static void FrictionCalibration_Observe(float dt);
#endif
#if defined(FOC_MOTOR_IDENTIFICATION_DIAG)
#include "motor_identification.h"
static MotorIdentification motor_ident;
static uint8_t MotorIdent_Command(const char *cmd,char *out,size_t size);
static uint8_t MotorIdent_Ref(float id,float iq);
static void MotorIdent_Capture(void);
#endif
#if defined(FOC_CURRENT_STEP_AB_DIAG)
#include "current_step_ab.h"
static CurrentStepAB current_step_ab;
unsigned current_step_pi_new=1U;
static float current_step_out_d,current_step_out_q;
static uint8_t current_step_saturated;
static uint8_t CurrentStep_Command(const char *cmd,char *out,size_t size);
static uint8_t CurrentStep_FocReference(void);
static void CurrentStep_Capture(void);
#endif
#if defined(FOC_SPEED_STARTUP_BRAKE)
#include "speed_startup_brake.h"
#endif
#if defined(FOC_SPEED_BUMPLESS)
#include "speed_bumpless.h"
#if defined(FOC_SPEED_BRAKE_TRACK)
#include "speed_brake_track.h"
#if defined(FOC_SPEED_PI_ANTI_WINDUP)
#include "speed_pi_anti_windup.h"
#endif
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
#include "router.h"
#include "router_uart_tx.h"
#include "esp_link.h"
#include "esp_ping.h"
#if defined(ESP_NETWORK_OBSERVER)
#include "network_v1.h"
#endif
#include "pw_kvs_params.h"
#if defined(UART_FIRMWARE_TRANSFER)
#include "uart_firmware_transfer.h"
#endif
#include "tighten_params_storage.h"
#if defined(FOC_INTENT_FSM_CANDIDATE)
#include "tightening_intent_fsm.h"
static TighteningFsm intent_fsm;
#if defined(FOC_DOB_LOAD_SPEED)
#include "dob_load_speed_candidate.h"
#endif
static uint8_t TighteningIntent_PrecheckOnly(void);
static void TighteningIntent_PrintStatus(uint32_t request_id);
#endif
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


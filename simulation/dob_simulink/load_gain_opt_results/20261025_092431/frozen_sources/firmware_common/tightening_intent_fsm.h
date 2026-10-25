#ifndef TIGHTENING_INTENT_FSM_H
#define TIGHTENING_INTENT_FSM_H
#include "control_intent.h"
#include "tighten_params.h"
#include "tightening_rundown_guard.h"

#define TIGHTEN_FSM_PRECHECK_TIMEOUT_MS 1000U
#define TIGHTEN_FSM_CONTACT_SPEED_HYST_RPM 2.0f
#define TIGHTEN_FSM_CONTACT_IQ_HYST_A 0.03f
#define TIGHTEN_FSM_CONTACT_DROP_RATIO 0.70f
#define TIGHTEN_FSM_MAX_OBSERVATION_GAP_MS 30U
typedef enum {
    TF_IDLE,TF_PRECHECK,TF_RUNDOWN_START,TF_RUNDOWN,TF_CONTACT_CONFIRM,
    TF_TIGHTEN,TF_HOLD,TF_DONE,TF_NO_ROTATION,TF_TIMEOUT,TF_FAULT
} TighteningFsmState;
typedef enum {
    TF_REASON_NONE,TF_REASON_NO_ROTATION,TF_REASON_OVERSPEED,
    TF_REASON_OVERCURRENT,TF_REASON_CURRENT_INVALID,TF_REASON_ENCODER_FAULT,
    TF_REASON_TIMEOUT,TF_REASON_FAULT,TF_REASON_PRECHECK,
    TF_REASON_TRAVEL,TF_REASON_STOP_TIMEOUT,TF_REASON_INTENT_REJECTED,
    TF_REASON_ADC_HEALTH /* Append: existing diagnostic values stay stable. */
} TighteningFsmReason;
typedef enum { TF_OUT_NONE,TF_OUT_OK,TF_OUT_STOPPED,TF_OUT_FAILED } TighteningFsmOutcome;
typedef struct {
    TightenParams_t recipe; /* Freeze at START, persistent ABI unchanged. */
    float direction, speed_iq_limit_a, direct_iq_limit_a, hard_speed_limit_rpm;
    float stop_max_rpm;
    uint32_t stop_confirm_ms,stop_timeout_ms,session_timeout_ms;
} TighteningFsmConfig;
typedef struct {
    uint32_t now_ms;
    float position_deg,speed_ctrl_rpm,speed_detect_rpm,iq_demand_a;
    uint8_t start,stop,precheck_ready,encoder_valid;
    TighteningFsmReason protection_fault;
} TighteningFsmInput;
typedef struct {
    TighteningFsmConfig cfg;
    ControlIntent intent;
    TightenRundownGuard motion;
    TighteningFsmState state,previous_state;
    TighteningFsmReason fault_reason;
    TighteningFsmOutcome outcome;
    uint32_t entered_ms,last_ms,cycle_ms,rundown_ms,phase_ms;
    uint32_t contact_since_ms,settle_since_ms,contact_confirmed_ms;
    uint32_t contact_pending_ms,transition_count;
    float start_position,contact_position,motion_travel_deg,rundown_peak_speed_rpm;
    uint8_t rundown_armed,contact_pending,contact_confirmed,tightening_completed;
    uint8_t contact_timer,settle_timer,phase;
} TighteningFsm;
void TighteningFsm_Init(TighteningFsm *,TighteningFsmConfig,uint32_t now_ms);
void TighteningFsm_Step(TighteningFsm *,TighteningFsmInput);
void TighteningFsm_Reject(TighteningFsm *,TighteningFsmReason,uint32_t now_ms);
uint8_t TighteningFsm_Busy(const TighteningFsm *);
uint8_t TighteningFsm_IsFault(const TighteningFsm *);
const char *TighteningFsm_StateName(TighteningFsmState);
const char *TighteningFsm_ReasonName(TighteningFsmReason);
const char *TighteningFsm_OutcomeName(TighteningFsmOutcome);
#endif

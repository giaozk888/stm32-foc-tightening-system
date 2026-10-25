#ifndef TIGHTEN_SYNTHETIC_BENCH_H
#define TIGHTEN_SYNTHETIC_BENCH_H

#include <stddef.h>
#include <stdint.h>
#include "tighten_params.h"

/* CPU-only synthetic fixture. No hardware callbacks, commands, Flash or heap.
 * An outcome is MODEL evidence only, NEVER an actuator/torque qualification. */
#define TIGHTSIM_CASES 12U
#define TIGHTSIM_CONTEXT_BYTES 4096U

typedef enum {
    TIGHTSIM_RUNNING = 0,
    TIGHTSIM_PROCESS_OK,
    TIGHTSIM_MODEL_OK,
    TIGHTSIM_RUNDOWN_TIMEOUT,
    TIGHTSIM_STOP_TIMEOUT,
    TIGHTSIM_ABORT,
    TIGHTSIM_OVERTORQUE,
    TIGHTSIM_ANGLE_REJECT,
    TIGHTSIM_TORQUE_TIMEOUT,
    TIGHTSIM_FEEDBACK_STALE,
    TIGHTSIM_FAULT_INJECTED,
    TIGHTSIM_STOPPED,
    TIGHTSIM_TARGET_UNREACHABLE,
    TIGHTSIM_SIMULATION_TIMEOUT,
    TIGHTSIM_INVALID
} TightSimOutcome;

typedef struct {
    TightenParams_t recipe;
    float speed_kp, speed_ki, speed_iq_limit, direct_iq_limit;
    float stop_max_rpm;
    uint32_t stop_confirm_ms, stop_timeout_ms;
} TightSimConfig;

typedef union {
    uint64_t alignment;
    uint8_t bytes[TIGHTSIM_CONTEXT_BYTES];
} TightSimContext;

typedef struct {
    uint32_t case_id, feedback, outcome, elapsed_ms;
    uint32_t final_nnm, peak_nnm, target_nnm, max_command_ma;
    uint32_t truth_in_demo_band, stripped, model_only;
    uint32_t state_transitions, steps, terminal_command_zero;
} TightSimResult;

#ifdef __cplusplus
extern "C" {
#endif
TightSimConfig TightSim_DefaultConfig(void);
int TightSim_Begin(TightSimContext *context, const TightSimConfig *config, uint32_t case_id,
                   uint32_t feedback);
/* At most budget model steps; 0=running, 1=finished, -1=invalid input. */
int TightSim_Advance(TightSimContext *context, uint32_t budget);
int TightSim_Result(const TightSimContext *context, TightSimResult *result);
const char *TightSim_OutcomeName(uint32_t outcome);
#ifdef __cplusplus
}
#endif
#endif

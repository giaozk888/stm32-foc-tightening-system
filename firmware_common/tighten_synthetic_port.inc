/* Local-only CPU fixture. This file is included AFTER protocol helpers and
 * the hard-locked isolated bench. Never link it into normal motor firmware. */
#if !defined(FOC_ISOLATED_CONCURRENCY)
#error Synthetic fixture requires the non-actuating isolated profile
#endif
#include "tighten_synthetic_bench.h"

static TightSimContext synthetic_context;
static TightSimResult synthetic_results[TIGHTSIM_CASES * 2U];
static TaskHandle_t synthetic_task_handle;
/* Keep the existing heap budget available to BootHealth/Protocol/logging.
 * This test task owns a statically reserved stack and TCB, released by reset. */
static StackType_t synthetic_task_stack[1024U] __attribute__((aligned(8)));
static StaticTask_t synthetic_task_tcb;
static volatile uint32_t synthetic_busy, synthetic_cancel, synthetic_done;
static volatile uint32_t synthetic_passed, synthetic_failure, synthetic_runs;
static uint32_t synthetic_start_ms, synthetic_elapsed_ms;

static int Synthetic_LockedStopped(void) {
    return IsolatedBench_Locked() && isolated_running == 0U && (TIM1->CR1 & TIM_CR1_CEN) == 0U &&
           fw_update.active == 0U && BootHealth_IsCurrentTrial() == 0U && adc_fault == 0U &&
           foc_fault == 0U && motor_control_mode == MOTOR_MODE_IDLE && Tightening_IsBusy() == 0U &&
           tightening_start_request == 0U;
}

static int Synthetic_CheckResult(const TightSimResult *r) {
    static const uint32_t expected[TIGHTSIM_CASES][2] = {
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
        {TIGHTSIM_RUNDOWN_TIMEOUT, TIGHTSIM_RUNDOWN_TIMEOUT},
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_OVERTORQUE},
        {TIGHTSIM_RUNDOWN_TIMEOUT, TIGHTSIM_TORQUE_TIMEOUT},
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_MODEL_OK},
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_TORQUE_TIMEOUT},
        {TIGHTSIM_FEEDBACK_STALE, TIGHTSIM_FEEDBACK_STALE},
        {TIGHTSIM_FEEDBACK_STALE, TIGHTSIM_FEEDBACK_STALE},
        {TIGHTSIM_FAULT_INJECTED, TIGHTSIM_FAULT_INJECTED},
        {TIGHTSIM_STOPPED, TIGHTSIM_STOPPED},
        {TIGHTSIM_PROCESS_OK, TIGHTSIM_TARGET_UNREACHABLE}};
    return r->case_id < TIGHTSIM_CASES && r->feedback < 2U &&
           r->outcome == expected[r->case_id][r->feedback] && r->model_only == 1U &&
           r->terminal_command_zero == 1U && r->max_command_ma <= 400U && r->steps <= 32501U &&
           (!(r->feedback && r->case_id < 2U) || r->truth_in_demo_band == 1U) &&
           (r->case_id != 5U || r->truth_in_demo_band == 0U) &&
           (r->case_id != 11U || r->feedback == 0U || r->max_command_ma == 0U);
}

static void SyntheticTask(void *argument) {
    (void)argument;
    for (;;) {
        if (synthetic_busy == 0U) {
            vTaskDelay(pdMS_TO_TICKS(10U));
            continue;
        }
        /* Fixed SOURCE defaults, not a live/persisted motor recipe. Constants
         * are taken from this APP. These values never reach an actuator. */
        TightSimConfig config = TightSim_DefaultConfig();
        config.speed_kp = SPEED_KP_A_PER_RPM;
        config.speed_ki = SPEED_KI_A_PER_RPM_S;
        config.speed_iq_limit = MOTOR_SPEED_IQ_LIMIT_A;
        config.direct_iq_limit = MOTOR_DIRECT_IQ_LIMIT_A;
        config.stop_max_rpm = TIGHTEN_STOP_MAX_RPM;
        config.stop_confirm_ms = TIGHTEN_STOP_CONFIRM_MS;
        config.stop_timeout_ms = TIGHTEN_STOP_TIMEOUT_MS;
        uint32_t failure = 0U;
        for (uint32_t index = 0U; index < TIGHTSIM_CASES * 2U && failure == 0U; ++index) {
            if (!Synthetic_LockedStopped() || synthetic_cancel != 0U) {
                failure = 1U;
                break;
            }
            if (!TightSim_Begin(&synthetic_context, &config, index / 2U, index % 2U)) {
                failure = 3U;
                break;
            }
            int done;
            do {
                if (!Synthetic_LockedStopped() || synthetic_cancel != 0U) {
                    failure = 1U;
                    break;
                }
                if (HAL_GetTick() - synthetic_start_ms > 120000U) {
                    failure = 2U;
                    break;
                }
                done = TightSim_Advance(&synthetic_context, 128U);
                if (done < 0)
                    failure = 4U;
                /* Bounded CPU chunk; protocol, safety and watchdog run first. */
                vTaskDelay(pdMS_TO_TICKS(1U));
            } while (done == 0 && failure == 0U);
            TightSimResult result;
            if (failure == 0U && !TightSim_Result(&synthetic_context, &result))
                failure = 4U;
            if (failure != 0U)
                break;
            int passed = Synthetic_CheckResult(&result);
            taskENTER_CRITICAL();
            synthetic_results[index] = result;
            synthetic_done = index + 1U;
            synthetic_passed += passed != 0;
            taskEXIT_CRITICAL();
            if (!passed)
                failure = 5U;
        }
        if (!Synthetic_LockedStopped()) {
            IsolatedBench_Stop(3U); /* Fail closed; never enable any output. */
            failure = 1U;
        }
        taskENTER_CRITICAL();
        synthetic_failure = failure;
        synthetic_elapsed_ms = HAL_GetTick() - synthetic_start_ms;
        synthetic_busy = 0U;
        taskEXIT_CRITICAL();
    }
}

static void Synthetic_Command(uint32_t request_id, const char *cmd, char *msg, size_t capacity) {
    if (protocol_reply_route_active != 0U) {
        Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "LOCAL_CONSOLE_ONLY");
        return;
    }
    if (strcmp(cmd, "SIM RUN") == 0) {
        if (synthetic_busy != 0U || synthetic_task_handle == NULL || !Synthetic_LockedStopped()) {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE,
                               "SIM_REQUIRES_CONFIRMED_STOPPED_ISOLATION");
            return;
        }
        taskENTER_CRITICAL();
        synthetic_done = synthetic_passed = synthetic_failure = synthetic_cancel = 0U;
        synthetic_start_ms = HAL_GetTick();
        synthetic_elapsed_ms = 0U;
        ++synthetic_runs;
        synthetic_busy = 1U;
        taskEXIT_CRITICAL();
    } else if (strcmp(cmd, "SIM STOP") == 0) {
        synthetic_cancel = 1U; /* Only cancel the CPU model, not a motor command. */
    } else if (strncmp(cmd, "SIM RESULT ", 11U) == 0) {
        unsigned long id, mode;
        char extra;
        if (sscanf(cmd + 11U, "%lu %lu %c", &id, &mode, &extra) != 2 || id >= TIGHTSIM_CASES ||
            mode >= 2U) {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "SIM_CASE_0_11_MODE_0_1");
            return;
        }
        TightSimResult r;
        taskENTER_CRITICAL();
        uint32_t valid = id * 2U + mode < synthetic_done;
        if (valid)
            r = synthetic_results[id * 2U + mode];
        taskEXIT_CRITICAL();
        if (!valid) {
            Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "SIM_RESULT_NOT_READY");
            return;
        }
        snprintf(msg, capacity,
                 "OK SIM CASE=%lu MODE=%lu OUT=%s MS=%lu FINAL=%lu PEAK=%lu TARGET=%lu MAXMA=%lu "
                 "TRUTH=%lu STEPS=%lu TRANS=%lu OFF=%lu MODEL=1",
                 id, mode, TightSim_OutcomeName(r.outcome), (unsigned long)r.elapsed_ms,
                 (unsigned long)r.final_nnm, (unsigned long)r.peak_nnm, (unsigned long)r.target_nnm,
                 (unsigned long)r.max_command_ma, (unsigned long)r.truth_in_demo_band,
                 (unsigned long)r.steps, (unsigned long)r.state_transitions,
                 (unsigned long)r.terminal_command_zero);
        Protocol_SendTaggedLine(request_id, msg);
        return;
    } else if (strcmp(cmd, "SIM STATUS") != 0) {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "SIM_LOCAL_COMMAND");
        return;
    }
    uint32_t busy, done, passed, failure, elapsed, runs;
    taskENTER_CRITICAL();
    busy = synthetic_busy;
    done = synthetic_done;
    passed = synthetic_passed;
    failure = synthetic_failure;
    runs = synthetic_runs;
    elapsed = busy ? HAL_GetTick() - synthetic_start_ms : synthetic_elapsed_ms;
    taskEXIT_CRITICAL();
    snprintf(
        msg, capacity,
        "OK SIM VER=1 BUSY=%lu DONE=%lu PASS=%lu FAIL=%lu MS=%lu RUNS=%lu LOCK=%u STACK=%lu "
        "HEAP=%lu MINHEAP=%lu MODEL=1",
        (unsigned long)busy, (unsigned long)done, (unsigned long)passed, (unsigned long)failure,
        (unsigned long)elapsed, (unsigned long)runs, Synthetic_LockedStopped(),
        (unsigned long)(synthetic_task_handle ? uxTaskGetStackHighWaterMark(synthetic_task_handle) *
                                                    sizeof(StackType_t)
                                              : 0U),
        (unsigned long)xPortGetFreeHeapSize(), (unsigned long)xPortGetMinimumEverFreeHeapSize());
    Protocol_SendTaggedLine(request_id, msg);
}

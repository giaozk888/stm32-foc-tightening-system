#ifndef FOC_ADC_TIMING_STM32_H
#define FOC_ADC_TIMING_STM32_H
#include "foc_adc_window.h"
#ifdef __cplusplus
extern "C" {
#endif
#define FOC_ADC_TIMER_ARR 4249U
/* DS12288 Table 66, CKMODE=00: up to 3.5 ADC cycles when an injected
 * conversion aborts a regular conversion (2.5 cycles without abort).
 * At timer=170 MHz / ADC=42.5 MHz, reserve 3.5*4=14 timer ticks.
 * The planner guards the entire interval from trigger to aperture end,
 * so earlier sampling or synchronizer jitter cannot cross an edge either. */
#define FOC_ADC_TRIGGER_LATENCY_MAX_TICKS 14U
#ifndef FOC_ADC_SENSE_TOPOLOGY
#define FOC_ADC_SENSE_TOPOLOGY 0
#endif
#ifndef FOC_ADC_SETTLE_TICKS
#define FOC_ADC_SETTLE_TICKS 85U
#endif
/* Diagnostic remains hard-off. The separate protected candidate must retain
 * the original FSM, startup evidence and explicit runtime deadline admission. */
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
#if defined(FOC_ADC_RC_DIAGNOSTIC) || defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || \
    defined(FOC_COMPACT_CLOSED_LOOP) || !defined(FOC_PROTECTED_CLOSED_LOOP) || \
    !defined(FOC_LATEST_ORIGINAL_FSM) || !defined(FOC_STARTUP_TRACE) || \
    !defined(FOC_IRQ_COMPACT) || !defined(FOC_GATE_REUSE) || \
    !defined(FOC_ADC_WINDOW) || FOC_ADC_SENSE_TOPOLOGY != 2
#error "RC protected candidate requires complete original FSM, trace and low-side protection"
#endif
#endif
#if defined(FOC_ADC_RC_DIAGNOSTIC)
#if !defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || !defined(FOC_PROTECTED_CLOSED_LOOP) || \
    defined(FOC_LATEST_ORIGINAL_FSM) || defined(FOC_COMPACT_CLOSED_LOOP)
#error "RC sampling diagnostic requires the protected power-hard-off profile"
#endif
#endif
#if defined(FOC_ADC_RC_DIAGNOSTIC) || defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
#ifndef FOC_ADC_RC_MIN_LOW_ON_TICKS
#define FOC_ADC_RC_MIN_LOW_ON_TICKS 1700U
#endif
#if FOC_ADC_RC_MIN_LOW_ON_TICKS < 1700 || FOC_ADC_RC_MIN_LOW_ON_TICKS > 4249
#error "RC diagnostic minimum low-side observation must be 1700..4249 ticks"
#endif
#define FOC_ADC_MIN_LOW_ON_TICKS FOC_ADC_RC_MIN_LOW_ON_TICKS
#define FOC_ADC_SAMPLE_PLACEMENT FOC_SAMPLE_LATE_BEFORE_PEAK
#else
#define FOC_ADC_MIN_LOW_ON_TICKS 0U
#define FOC_ADC_SAMPLE_PLACEMENT FOC_SAMPLE_WINDOW_MIDPOINT
#endif
/* Provisional CPU-side reserve for the masked CCR preload transaction. This
 * is not a measured physical preload deadline or an analog qualification. */
#define FOC_ADC_COMMIT_GUARD_TICKS 170U
typedef struct {
    uint32_t irq_entries, pairs, pair_misses, plan_failures;
    uint32_t last_cycles, max_cycles, deadline_misses, blocks;
    uint32_t block_plan_sequence, plan_sequence;
    uint16_t command_phase[3], command_trigger;
    uint16_t trigger, slack_ticks;
    uint8_t last_plan_status, dwt_on, mixed_block;
    FocRawSpread raw;
    uint32_t processed_blocks, dropped_blocks, dropped_samples, rejected_samples;
    uint32_t worker_last_cycles, worker_max_cycles, worker_stack_free_bytes;
    uint8_t buffers_ready, buffers_reading, worker_busy, worker_stack_valid;
    uint32_t commit_checks, commit_failures;
} FocAdcTimingSnapshot;
FocWindowStatus FocAdcTiming_Commit(float u, float v, float w);
/* Prepare does not publish state or mask interrupts. Only commit an OK plan
 * returned by Prepare, after rechecking the caller's safety/admission gate. */
FocWindowStatus FocAdcTiming_Prepare(float u, float v, float w, FocWindowPlan *plan);
void FocAdcTiming_CommitPrepared(const FocWindowPlan *plan);
/* Separate RC candidate only. No reset/clear of failed deadline history.
 * Admission requires observed hard-off work with no coarse bottom alarm.
 * Checked commit must be inside the current ADC IRQ and before its bottom;
 * rejection writes no CCR; caller must immediately close output on failure. */
int FocAdcTiming_RcActuationReady(void);
int FocAdcTiming_CommitBeforeBottom(const FocWindowPlan *plan);
void FocAdcTiming_PlanFailed(FocWindowStatus status);
int FocAdcTiming_CanStart(void);
/* Foreground certification, before arming the protected loop. FastCanStart
 * checks the certified live clock registers and timer geometry, without HAL
 * frequency reconstruction in the 20/40 kHz interrupt paths. */
int FocAdcTiming_CertifyClock(void);
int FocAdcTiming_FastCanStart(void);
int FocAdcTiming_PairReady(void);
void FocAdcTiming_RecordRaw(uint16_t u, uint16_t v);
#if defined(FOC_FAST_PATH_PROFILE) || defined(FOC_PREEMPT_COMMIT_PROBE)
/* Hypothetical duty-dispatch location in hard-off compute: NEVER a CCR write
 * and never counted as an actual update. SRAM ledgers keep these separate. */
void FocAdcTiming_ProfileDutyPoint(void);
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
/* Real functional pending commit, not a debug timer-configuration probe.
 * Called at ADC vector entry, requires hard-off gates and a certified clock.
 * Writes CCR1/2/3 only; instrumentation never writes CR1/UDIS/SR/EGR/CCR4. */
int FocAdcTiming_PipelineCommit(const uint16_t phase[3]);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
/* Entry-commit timing admission, not the obsolete hypothetical FOC tail.
 * Keeps clock/geometry, paired ADC, real-late and 50us deadline guards. */
int FocAdcTiming_PipelineActuationReady(void);
int FocAdcTiming_PipelinePlanMatches(const FocWindowPlan *plan);
#endif
#endif
/* Foreground single-owner consumer; never runs statistics from an ISR.
 * Requires interrupts enabled. Returns one processed block or zero when
 * empty/busy/in interrupt context/interrupts masked. */
int FocAdcTiming_ProcessRawOne(void);
void FocAdcTiming_NoteWorkerStack(uint32_t free_bytes);
uint32_t FocAdcTiming_IrqEnter(void);
void FocAdcTiming_IrqExit(uint32_t start);
void FocAdcTiming_Snapshot(FocAdcTimingSnapshot *out);
int FocAdcTiming_Format(const char *command, char *out, uint32_t size);
#ifdef __cplusplus
}
#endif
#endif

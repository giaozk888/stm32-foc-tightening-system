#ifndef DOB_ID_TRACE_H
#define DOB_ID_TRACE_H
#include <stdint.h>
#include <stddef.h>
#if defined(FOC_DOB_ADMISSION_START_GUARD)
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
#define DIT_PRE 16U
#define DIT_DENSE 24U
#define DIT_TAIL 32U
#define DIT_ABI 7U
#define DIT_FRAME_BYTES 64U
#else
#define DIT_PRE 16U
#define DIT_DENSE 32U
#define DIT_TAIL 48U
#if defined(FOC_DOB_PERSISTENT_QUALITY)
#define DIT_ABI 6U
#elif defined(FOC_DOB_RECOVERABLE_ADMISSION)
#define DIT_ABI 5U
#elif defined(FOC_DOB_DIRECT_JUMP_REJECT)
#define DIT_ABI 4U
#else
#define DIT_ABI 3U
#endif
#define DIT_FRAME_BYTES 48U
#endif
#elif defined(FOC_DOB_SPIKE_ADMISSION)
#define DIT_PRE 32U
#define DIT_DENSE 32U
#define DIT_TAIL 128U
#define DIT_ABI 2U
#define DIT_FRAME_BYTES 24U
#else
#define DIT_PRE 64U
#define DIT_DENSE 64U /* includes the trigger */
#define DIT_TAIL 160U
#define DIT_ABI 1U
#define DIT_FRAME_BYTES 16U
#endif
#define DIT_CAPACITY (DIT_PRE+DIT_DENSE+DIT_TAIL)
#define DIT_BYTES (DIT_CAPACITY*DIT_FRAME_BYTES)
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
#define DIT_TAIL_US 16000U /* Observe >398ms warmup without growing RAM. */
#else
#define DIT_TAIL_US 4000U
#endif
enum { DIT_WAIT=0,DIT_POST=1,DIT_RECOVERY=2,DIT_DONE=3,DIT_STOPPED=4,DIT_BAD_TIME=5 };
enum { DIT_RESET=1U<<11,DIT_VALID=1U<<12,DIT_INITIALIZED=1U<<13,
       DIT_FILTER_SEEDED=1U<<14,DIT_TRIGGER=1U<<15 };
#if defined(FOC_DOB_SPIKE_ADMISSION)
typedef struct {
    float id_meas,iq_meas,abs_id_lpf,warmup_s;
    uint16_t interval_us,flags,decision,exit_reason;
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    uint32_t adc_seq,adc_source_us,adc_published_us;
    float speed_ref_rpm,speed_meas_rpm;
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    uint32_t id_bad_us; /* V6 replaces redundant fixed arm-qualification field. */
#else
    uint32_t qualify_us;
#endif
#endif
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    float id_adjacent_delta,lpf_before;
    uint32_t reset_reason,quality_meta;
#endif
} DobIdTraceFrame;
#else
typedef struct {float id_meas,abs_id_lpf,warmup_s;uint16_t interval_us,flags;} DobIdTraceFrame;
#endif
typedef struct {
    uint32_t abi,bound,running,frozen,state,pre_head,pre_count,post_count,tail_count;
    uint32_t stable_us,observations,trigger_us,trigger_seq,pre_last_us,last_stored_us,last_seq;
    uint32_t reset_calls_total,recorded_reset_calls,epoch_resets,epoch_reason,in_epoch,before_have;
    uint32_t encoding_errors,max_compute_us;
} DobIdTraceState;
extern DobIdTraceState dob_id_trace;
void DobIdTrace_Bind(void *buffer,size_t bytes);
void DobIdTrace_Lifecycle(uint8_t running,uint8_t fault);
void DobIdTrace_Begin(uint8_t have_sample);
void DobIdTrace_ResetEvent(uint32_t reason);
void DobIdTrace_After(uint32_t enc,uint32_t seq,uint32_t dt,float id,float filtered,
    float warmup,uint32_t status,uint8_t valid,uint8_t initialized,uint8_t have,
    float reference,float accel,float rpm
#if defined(FOC_DOB_SPIKE_ADMISSION)
    ,float iq
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    ,uint32_t adc_source_us,uint32_t adc_published_us
#endif
    );
#endif

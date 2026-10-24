#ifndef DOB_REAL_TRACE_H
#define DOB_REAL_TRACE_H
#include <stdint.h>
#include <stddef.h>
#define DOB_REAL_TRACE_CAPACITY 192U
#define DOB_REAL_TRACE_START_US 2000000U
#define DOB_REAL_TRACE_DURATION_US 192000U
enum { DRT_INPUT_VALID=1U<<11,DRT_SATURATED=1U<<12,DRT_LPF_UPDATED=1U<<13,
       DRT_SEQ_OVERFLOW=1U<<14,DRT_DOB_VALID=1U<<15 };
typedef struct {
    uint32_t encoder_us,observed_us;
    float id_a,iq_a,omega_rad_s;
    uint16_t adc_seq_step,flags;
} DobRealTracePoint;
typedef struct {
    uint32_t abi,count,observations,origin_us,origin_set,done;
    uint32_t first_seq,last_seq,first_us,last_us,overflow,max_cycles;
    uint32_t invalid_current,nonfinite,saturated,filter_skipped,dob_invalid;
    float reference_min_rpm,reference_max_rpm,accel_abs_peak_rpm_s,iq_command_abs_peak_a;
} DobRealTrace;
extern DobRealTrace dob_real_trace;
extern DobRealTracePoint *dob_real_points;
void DobRealTrace_Bind(void *buffer,size_t bytes);
/* One-shot task-only evidence. No setters, UART, allocation or IRQ access.
 * Fixed time window, NOT trigger/quality-selected. Fresh boot per run. */
void DobRealTrace_Observe(uint8_t running,uint32_t observed,uint32_t encoder,uint32_t seq,
    float id,float iq,float omega,uint8_t current_valid,uint8_t saturated,
    uint32_t status,uint8_t dob_valid,uint8_t lpf_updated,float reference,float accel,float command);
#endif

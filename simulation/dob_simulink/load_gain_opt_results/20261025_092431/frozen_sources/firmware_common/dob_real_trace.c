#include "dob_real_trace.h"
#include <math.h>
#include <stddef.h>
_Static_assert(sizeof(DobRealTracePoint)==24U,"Raw record ABI");
_Static_assert(sizeof(DobRealTrace)==84U,"Raw header ABI");
DobRealTrace dob_real_trace;
DobRealTracePoint *dob_real_points;
void DobRealTrace_Bind(void *buffer,size_t bytes){
    if(!dob_real_points&&bytes>=sizeof(DobRealTracePoint)*DOB_REAL_TRACE_CAPACITY)
        dob_real_points=buffer;
}
void DobRealTrace_Observe(uint8_t running,uint32_t now,uint32_t enc,uint32_t seq,
    float id,float iq,float omega,uint8_t valid,uint8_t sat,uint32_t status,uint8_t dob_valid,
    uint8_t updated,float reference,float accel,float command)
{
    DobRealTrace *s=&dob_real_trace;
    if(!running||s->done||!dob_real_points)return;
    s->abi=1U;++s->observations;
    if(!s->origin_set){s->origin_us=enc;s->origin_set=1U;}
    uint32_t elapsed=enc-s->origin_us;
    if(elapsed<DOB_REAL_TRACE_START_US)return;
    if(elapsed-DOB_REAL_TRACE_START_US>=DOB_REAL_TRACE_DURATION_US){s->done=1U;return;}
    if(s->count>=DOB_REAL_TRACE_CAPACITY){++s->overflow;s->done=1U;return;}
    if(!s->count){s->first_seq=seq;s->first_us=enc;s->reference_min_rpm=reference;s->reference_max_rpm=reference;}
    uint32_t delta=s->count?seq-s->last_seq:0;
    uint16_t flags=(uint16_t)(status&2047U);
    if(valid)flags|=DRT_INPUT_VALID;
    if(sat){flags|=DRT_SATURATED;++s->saturated;}
    if(updated)flags|=DRT_LPF_UPDATED;else ++s->filter_skipped;
    if(dob_valid)flags|=DRT_DOB_VALID;else ++s->dob_invalid;
    if(delta>65535U)flags|=DRT_SEQ_OVERFLOW;
    if(!valid)++s->invalid_current;
    if(!isfinite(id)||!isfinite(iq)||!isfinite(omega))++s->nonfinite;
    /* Preserve actual suspicious/nonfinite input, never replace by a trusted
     * value or DOB output. Invalid/source flags remain separate evidence. */
    dob_real_points[s->count++]=(DobRealTracePoint){enc,now,id,iq,omega,
        (uint16_t)(delta>65535U?65535U:delta),flags};
    s->last_seq=seq;s->last_us=enc;
    s->reference_min_rpm=fminf(s->reference_min_rpm,reference);
    s->reference_max_rpm=fmaxf(s->reference_max_rpm,reference);
    s->accel_abs_peak_rpm_s=fmaxf(s->accel_abs_peak_rpm_s,fabsf(accel));
    s->iq_command_abs_peak_a=fmaxf(s->iq_command_abs_peak_a,fabsf(command));
}

#include "dob_id_trace.h"
#include "mechanical_dob_monitor.h"
#include <math.h>
#include <string.h>
_Static_assert(sizeof(DobIdTraceFrame)==DIT_FRAME_BYTES,"Trace ABI");
_Static_assert(DIT_BYTES==4608U,"Reuse mechanical points, never grow heap/stack");
DobIdTraceState dob_id_trace;
static unsigned char *trace_buffer;
void DobIdTrace_Bind(void *buffer,size_t bytes){
    if(dob_id_trace.bound) return;
    if(!buffer || bytes<DIT_BYTES) return;
    trace_buffer=buffer;dob_id_trace.abi=DIT_ABI;dob_id_trace.bound=1;
}
void DobIdTrace_Lifecycle(uint8_t running,uint8_t fault){
    if(!dob_id_trace.bound || dob_id_trace.frozen) return;
    if(!running || fault){
        if(!dob_id_trace.running && !fault) return;
        dob_id_trace.running=0;dob_id_trace.frozen=1;dob_id_trace.in_epoch=0;
        if(dob_id_trace.state<DIT_DONE) dob_id_trace.state=DIT_STOPPED;
    } else dob_id_trace.running=1;
}
void DobIdTrace_Begin(uint8_t have_sample){
    dob_id_trace.in_epoch=(uint32_t)(dob_id_trace.running && !dob_id_trace.frozen);
    dob_id_trace.epoch_resets=0;dob_id_trace.epoch_reason=0;dob_id_trace.before_have=have_sample;
}
void DobIdTrace_ResetEvent(uint32_t reason){
    if(!dob_id_trace.in_epoch) return;
    ++dob_id_trace.epoch_resets;dob_id_trace.epoch_reason|=reason;
}
void DobIdTrace_After(uint32_t enc,uint32_t seq,uint32_t dt,float id,float filtered,
    float warmup,uint32_t status,uint8_t valid,uint8_t initialized,uint8_t have,
    float reference,float accel,float rpm
#if defined(FOC_DOB_SPIKE_ADMISSION)
    ,float iq
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    ,uint32_t adc_source_us,uint32_t adc_published_us
#endif
    ){
    if(!dob_id_trace.in_epoch) return;
    dob_id_trace.in_epoch=0;++dob_id_trace.observations;
    dob_id_trace.reset_calls_total+=dob_id_trace.epoch_resets;
    if(dob_id_trace.state>=DIT_DONE) return;
    uint8_t steady=(uint8_t)(isfinite(reference)&&isfinite(accel)&&isfinite(rpm)&&
        fabsf(reference-600.f)<.01f&&fabsf(accel)<=1.f&&fabsf(rpm-reference)<=12.f&&dt&&dt<=2000U);
    if(dob_id_trace.state==DIT_WAIT) dob_id_trace.stable_us=steady?dob_id_trace.stable_us+dt:0;
#if defined(FOC_DOB_ADMISSION_START_GUARD)
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    uint8_t trigger=(uint8_t)(dob_id_trace.state==DIT_WAIT&&dob_current_admission.armed&&
        dob_current_admission.seeded&&(dob_current_admission.decision==DCA_QUALITY_WAIT||
        dob_current_admission.decision==DCA_GAP_STALE||(dob_id_trace.epoch_reason&DOB_MONITOR_ID)));
#else
    /* First admission event, NOT a later steady-state view of a stale latch. */
    uint8_t trigger=(uint8_t)(dob_id_trace.state==DIT_WAIT&&
        (dob_current_admission.decision==DCA_SUSPECT||dob_current_admission.decision==DCA_BLOCKED||
         dob_current_admission.decision==DCA_DIRECT_REJECT||
#if defined(FOC_DOB_PERSISTENT_QUALITY)
         dob_current_admission.decision==DCA_JUMP_PENDING||dob_current_admission.decision==DCA_RUN_REJECT||
#endif
         (dob_current_admission.armed&&(dob_id_trace.epoch_reason&DOB_MONITOR_ID))));
#endif
#else
    uint8_t trigger=(uint8_t)(dob_id_trace.state==DIT_WAIT&&dob_id_trace.stable_us>=500000U&&
#if defined(FOC_DOB_SPIKE_ADMISSION)
        (dob_current_admission.decision==DCA_SUSPECT || dob_current_admission.decision==DCA_BLOCKED ||
         (dob_id_trace.epoch_reason&DOB_MONITOR_ID)));
#else
        (dob_id_trace.epoch_reason&DOB_MONITOR_ID));
#endif
#endif
    if(dob_id_trace.state==DIT_RECOVERY&&enc-dob_id_trace.last_stored_us<DIT_TAIL_US) return;
    uint32_t interval=dob_id_trace.pre_count?enc-dob_id_trace.last_stored_us:dt;
    if(!interval||interval>65535U){
        ++dob_id_trace.encoding_errors;dob_id_trace.state=DIT_BAD_TIME;return;
    }
    DobIdTraceFrame f={.id_meas=id,.abs_id_lpf=filtered,.warmup_s=warmup,
        .interval_us=(uint16_t)interval,.flags=(uint16_t)status};
#if defined(FOC_DOB_SPIKE_ADMISSION)
    f.iq_meas=iq;
    f.decision=(uint16_t)dob_current_admission.decision;
    f.exit_reason=(uint16_t)dob_current_admission.exit_reason;
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    f.exit_reason=(uint16_t)dob_current_admission.quality_reason;
    f.id_adjacent_delta=dob_current_admission.raw_delta_id;
    f.lpf_before=dob_current_admission.lpf_before;
    f.reset_reason=dob_id_trace.epoch_reason;
    f.quality_meta=(dob_current_admission.jump_run<65535U?dob_current_admission.jump_run:65535U)|
        (dob_current_admission.pending<<16)|(dob_current_admission.id_bad_latched<<17)|
        (dob_current_admission.raw_have<<18)|(dob_current_admission.filter_updated<<19);
#elif defined(FOC_DOB_PERSISTENT_QUALITY)
    /* V6: low8 jump-run count (saturating), bit8 confirmed Id condition. */
    f.exit_reason=(uint16_t)((dob_current_admission.jump_run<255U?dob_current_admission.jump_run:255U)|
                            (dob_current_admission.id_bad_latched<<8));
#endif
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    f.adc_seq=seq;f.adc_source_us=adc_source_us;f.adc_published_us=adc_published_us;
    f.speed_ref_rpm=reference;f.speed_meas_rpm=rpm;
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    f.id_bad_us=dob_current_admission.id_bad_us;
#else
    f.qualify_us=dob_current_admission.qualify_us;
#endif
#endif
    if(dob_id_trace.epoch_resets) f.flags|=DIT_RESET;
    if(valid) f.flags|=DIT_VALID;
    if(initialized) f.flags|=DIT_INITIALIZED;
    if(!dob_id_trace.before_have&&have) f.flags|=DIT_FILTER_SEEDED;
#if defined(FOC_DOB_SPIKE_ADMISSION)
    if(have&&(f.decision==DCA_SEED||f.decision==DCA_TRANSITION
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
        ||f.decision==DCA_QUALITY_SEED
#endif
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
        ||f.decision==DCA_GAP_RESEED
#endif
        )) f.flags|=DIT_FILTER_SEEDED;
#endif
    if(trigger) f.flags|=DIT_TRIGGER;
    uint32_t index;
    if(dob_id_trace.state==DIT_WAIT&&!trigger){
        index=dob_id_trace.pre_head;
        dob_id_trace.pre_head=(index+1U)%DIT_PRE;
        if(dob_id_trace.pre_count<DIT_PRE) ++dob_id_trace.pre_count;
        dob_id_trace.pre_last_us=enc;
    } else {
        if(trigger){
            dob_id_trace.state=DIT_POST;dob_id_trace.trigger_us=enc;dob_id_trace.trigger_seq=seq;
        }
        if(dob_id_trace.state==DIT_POST){
            index=DIT_PRE+dob_id_trace.post_count++;
            if(dob_id_trace.post_count==DIT_DENSE) dob_id_trace.state=DIT_RECOVERY;
        } else {
            index=DIT_PRE+DIT_DENSE+dob_id_trace.tail_count++;
            if(dob_id_trace.tail_count==DIT_TAIL) dob_id_trace.state=DIT_DONE;
        }
    }
    memcpy(trace_buffer+index*sizeof f,&f,sizeof f);
    dob_id_trace.recorded_reset_calls+=dob_id_trace.epoch_resets;
    dob_id_trace.last_stored_us=enc;dob_id_trace.last_seq=seq;
}

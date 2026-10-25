#include "mechanical_dob_monitor.h"
#include "dob_normal_control.h"
#include <assert.h>
#include <stdio.h>
static MechanicalDobMonitor m;
static DobFeedbackCandidate feedback={.enabled=1};
static uint32_t clock_us=100000,seq=0;
static float sample(float iq,float id,uint8_t iq_sat,uint32_t flags,uint32_t age){
    clock_us+=1000;seq+=20;
    MechanicalCurrent c={.seq=seq,.source_us=clock_us-age,.published_us=clock_us-age+5,.id=id,.iq=iq,.flags=flags};
    MechanicalDobMonitor_Observe(&m,clock_us+20,clock_us,1000,25.13274123f,iq_sat,&c,1);
    return DobFeedback_Update(&feedback,clock_us+20,1000,m.current.sample_us,m.current.disturbance_a,
        (uint8_t)(m.current.valid&&!(m.current.status&DOB_MONITOR_SATURATED)),1,.5f);
}
int main(void){
    DobNormal_Lifecycle(&m,&feedback,1,0);
    for(unsigned n=0;n<900;++n)sample(.16f,.001f,0,0,0);
    assert(m.current.valid&&m.observer.initialized);
    float warm=m.observer.elapsed_s;uint32_t good=feedback.valid_updates;
    for(unsigned n=0;n<100;++n){
        sample(.16f,.001f,1,0,0);
        assert(m.current.valid&&(m.current.status&DOB_MONITOR_SATURATED));
        assert(m.have_sample&&m.observer.initialized);
    }
    assert(m.observer.elapsed_s>warm+.09f&&feedback.valid_updates==good&&feedback.iq_comp_a==0);
    sample(.16f,.001f,0,0,0);assert(m.current.valid&&feedback.state==DOB_FB_TRACK);
    for(unsigned n=0;n<500;++n){sample(.26f,.001f,0,MEC_SATURATED,0);assert(m.current.valid);}
    assert(m.current.status==DOB_MONITOR_SATURATED);
    /* Same measured-Iq mechanical model remains meaningful under saturation. */
    assert(fabsf(m.current.disturbance_a-.10055f)<.006f);
    sample(.26f,.001f,0,0,0);assert(m.current.valid&&feedback.state==DOB_FB_TRACK);
    assert(fabsf(feedback.iq_comp_a)<=.025f);
    float before=m.abs_id_lpf,elapsed=m.observer.elapsed_s;
    sample(.26f,.701f,1,0,0);
    assert(!m.current.valid&&m.abs_id_lpf==before&&m.observer.elapsed_s==elapsed);
    sample(.26f,.001f,1,0,0);assert(m.abs_id_lpf<.002f);
    sample(.26f,.001f,1,0,0);assert(m.current.valid);
    assert(dob_saturation_audit.input_resets==0&&dob_saturation_audit.limited_valid>590);
    /* Saturation metadata never bypasses other input faults. */
    sample(.26f,.001f,1,MEC_SATURATED|MEC_RANGE,0);
    assert(!m.current.valid&&!m.observer.initialized&&(m.current.status&DOB_MONITOR_CURRENT));
    sample(.26f,.001f,1,MEC_SATURATED,300);
    assert(!m.current.valid&&!m.observer.initialized&&(m.current.status&DOB_MONITOR_TIME));
    for(unsigned n=0;n<900;++n)sample(.16f,.001f,0,0,0);
    assert(m.current.valid);
    for(unsigned n=0;n<100;++n)sample(.16f,.2f,1,0,0);
    assert(dob_current_admission.id_bad_entries==1&&!m.current.valid&&(m.current.status&DOB_MONITOR_ID));
    DobNormal_Lifecycle(&m,&feedback,0,1);
    assert(!m.running&&!m.current.valid&&feedback.iq_comp_a==0);
    puts("PASS: IQ/V limitation preserves observation; no fresh limited feedback; measured load step;700mA spike; Id/time/source/fault gates retained");
    return 0;
}

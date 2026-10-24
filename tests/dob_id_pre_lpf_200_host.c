/* Real DOB-only production code; synthetic signed currents, no hardware. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"

static MechanicalDobMonitor mon;
static unsigned char trace_buffer[DIT_BYTES];
static uint32_t enc,seq;
static void sample(float id,float iq){
    enc+=1000;seq+=20;
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,1000,62.831853f,0,&c,1);
    DobIdTrace_After(enc,seq,1000,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,0,600,mon.current.iq_a,
        mon.current.adc_source_us,mon.current.adc_published_us);
}
static void warm(void){
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};enc=seq=0;
    DobIdTrace_Bind(trace_buffer,sizeof trace_buffer);DobIdTrace_Lifecycle(1,0);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);
    for(unsigned i=0;i<600;++i)sample(.02f,.20f);
    assert(mon.current.valid);
}
static void pair(float from,float to,unsigned axis,int expect){
    DobCurrentAdmission s={0};
    for(uint32_t t=1000;t<=3000;t+=1000)
        DobAdmit_Push(&s,t,1000,axis?0:from,axis?from:0);
    assert(s.seeded);
    int result=DobAdmit_Push(&s,4000,1000,axis?0:to,axis?to:0);
    assert(result==expect);
    if(!expect)assert(s.decision==DCA_QUALITY_WAIT);
}
int main(void){
    assert(DOB_ADMIT_JUMP_A==.200f);
    assert(sizeof(DobCurrentAdmission)==204&&sizeof(MechanicalDobMonitor)==856);
    /* Signed differences, NOT abs(abs(current)-abs(previous)). */
    for(unsigned axis=0;axis<2;++axis){
        pair(-.075f,+.075f,axis,1);pair(+.075f,-.075f,axis,1);
        pair(-.100f,+.100f,axis,1);pair(+.100f,-.100f,axis,1);
        pair(-.100f,+.1001f,axis,0);pair(+.100f,-.1001f,axis,0);
        pair(-.150f,+.150f,axis,0);pair(+.150f,-.150f,axis,0);
    }
    for(unsigned sign=0;sign<2;++sign){
        warm();float lp=mon.abs_id_lpf,qlp=mon.iq_lpf,w=mon.observer.elapsed_s;
        uint32_t resets=dob_id_trace.reset_calls_total,good=mon.valid_samples;
        sample(sign?-.700f:.700f,.20f);
        assert(!mon.current.valid&&!dob_current_admission.filter_updated);
        assert(mon.abs_id_lpf==lp&&mon.iq_lpf==qlp&&mon.observer.elapsed_s==w);
        assert(mon.valid_samples==good&&dob_id_trace.reset_calls_total==resets);
        sample(.02f,.20f);
        assert(dob_current_admission.decision==DCA_QUALITY_RETURN&&!mon.current.valid);
        assert(mon.abs_id_lpf==lp&&mon.observer.elapsed_s==w);
        sample(.02f,.20f);assert(mon.current.valid);
        assert(dob_id_trace.reset_calls_total==resets);
    }
    /* Large Iq excludes the pair before either DOB filter too. */
    warm();float lp=mon.abs_id_lpf,qlp=mon.iq_lpf;
    sample(.03f,-.700f);
    assert(mon.abs_id_lpf==lp&&mon.iq_lpf==qlp&&!mon.current.valid);
    /* Unchanged sustained Id gate: coherent real level is admitted, then
     * existing 60mA / 20ms model-domain check makes the observer invalid. */
    warm();sample(.700f,.20f);sample(.700f,.20f);sample(.700f,.20f);
    assert(dob_current_admission.decision==DCA_QUALITY_LEVEL);
    unsigned ticks=0;
    while(!dob_current_admission.id_bad_latched){sample(.700f,.20f);assert(++ticks<=21);}
    assert(dob_current_admission.id_bad_us==20000&&!mon.current.valid);
    assert(mon.current.status==DOB_MONITOR_ID&&dob_current_admission.id_bad_entries==1);
    for(unsigned i=0;i<650;++i)sample(.02f,.20f);
    assert(mon.current.valid&&dob_current_admission.id_bad_recoveries==1);
    /* Missing trusted data still resets once beyond 10ms, never a count latch. */
    warm();uint32_t resets=dob_id_trace.reset_calls_total;
    for(unsigned i=0;i<35;++i)sample(i%2?.700f:-.700f,.20f);
    assert(dob_current_admission.gap_resets==1&&!dob_current_admission.blocked);
    assert(dob_id_trace.reset_calls_total==resets+1);
    for(unsigned i=0;i<650;++i)sample(.02f,.20f);
    assert(mon.current.valid);
    MechanicalDobMonitor_Lifecycle(&mon,1,1);
    assert(!mon.running&&mon.frozen==DOB_SHADOW_FAULT&&!mon.current.valid);
    puts("PASS: signed 150/200mA admitted, >200mA quarantined on both axes/directions; +/-700mA isolated; persistent Id and gap protection unchanged");
    return 0;
}

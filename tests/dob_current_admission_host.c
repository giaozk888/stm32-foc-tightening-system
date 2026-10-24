/* Offline synthetic stimuli, not physical motor evidence. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
static MechanicalDobMonitor mon;
static unsigned char storage[DIT_BYTES+16];
static uint32_t enc=1000,seq=20;
static void reset(void){
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};enc=1000;seq=20;
    memset(storage,0xA5,sizeof storage);DobIdTrace_Bind(storage,DIT_BYTES);
    DobIdTrace_Lifecycle(1,0);MechanicalDobMonitor_Lifecycle(&mon,1,0);
}
static void sample(float id,float iq,unsigned valid,unsigned saturation){
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,1000,62.831853f,(uint8_t)saturation,&c,(uint8_t)valid);
    DobIdTrace_After(enc,seq,1000,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,0,600,mon.current.iq_a);
    enc+=1000;seq+=20;
}
static void warmup(void){for(unsigned i=0;i<800;i++)sample(.04f,.22f,1,0);assert(mon.current.valid);}
int main(int argc,char **argv){
    (void)argv;
    assert(sizeof(DobIdTraceFrame)==24&&DIT_BYTES==4608&&sizeof(DobIdTraceState)==96);
    reset();warmup();float before=mon.observer.elapsed_s,lp=mon.abs_id_lpf,iq=mon.iq_lpf;
    sample(-.561689f,.22f,1,0);
    assert(dob_current_admission.decision==DCA_SUSPECT&&!mon.current.valid);
    assert(mon.current.id_a==-.561689f&&mon.abs_id_lpf==lp&&mon.iq_lpf==iq);
    assert(mon.observer.elapsed_s==before&&dob_id_trace.epoch_resets==0);
    sample(.04f,.22f,1,0);
    assert(dob_current_admission.decision==DCA_SPIKE_RETURN&&!mon.current.valid);
    assert(dob_current_admission.isolated==1&&dob_current_admission.accepted_gap_us==2000);
    assert(mon.observer.elapsed_s==before&&mon.abs_id_lpf==lp&&dob_id_trace.epoch_resets==0);
    sample(.04f,.22f,1,0);assert(mon.current.valid&&mon.observer.elapsed_s>before);
    if(argc>1){
        for(unsigned i=0;i<1500;i++)sample(.04f,.22f,1,0);
        DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
        assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.post_count==32&&dob_id_trace.tail_count==128);
        for(unsigned i=DIT_BYTES;i<sizeof storage;i++)assert(storage[i]==0xA5);
        _setmode(_fileno(stdout),_O_BINARY);
        fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(storage,DIT_BYTES,1,stdout);return 0;
    }
    /* Iq spike is paired: neither Iq nor Id enters the estimator. */
    reset();warmup();iq=mon.iq_lpf;sample(.04f,.70f,1,0);
    assert(!mon.current.valid&&mon.iq_lpf==iq);sample(.04f,.22f,1,0);
    assert(dob_current_admission.isolated==1&&mon.iq_lpf==iq);
    /* Recorded Id trigger/next values, with SYNTHETIC constant Iq (not
     * a replay of unrecorded actual Iq or of the full prehistory). */
    reset();for(unsigned i=0;i<800;i++)sample(.023362586f,.22f,1,0);
    mon.abs_id_lpf=.031163482f;
    sample(-.561689258f,.22f,1,0);assert(!mon.current.valid);
    sample(-.058916569f,.22f,1,0);
    assert(dob_current_admission.isolated==1&&dob_current_admission.blocked==0);
    assert(mon.abs_id_lpf<.05f&&dob_id_trace.epoch_resets==0);
    /* Real new level is admitted, never mislabeled isolated or clipped. */
    reset();warmup();sample(.35f,.22f,1,0);sample(.35f,.22f,1,0);
    assert(dob_current_admission.transitions==1&&dob_current_admission.isolated==0);
    assert(fabsf(mon.abs_id_lpf-.35f)<1e-6f&&mon.current.status==DOB_MONITOR_ID);
    assert(!mon.observer.initialized&&dob_id_trace.epoch_resets==2);
    /* Negative spike and negative persistent transition have equal rules. */
    reset();warmup();sample(-.55f,.22f,1,0);sample(.04f,.22f,1,0);
    assert(dob_current_admission.isolated==1&&!mon.current.valid);
    sample(-.35f,.22f,1,0);sample(-.35f,.22f,1,0);
    assert(dob_current_admission.transitions==1&&mon.current.status==DOB_MONITOR_ID);
    /* A genuine Iq level change with low Id resets THEN reinitializes, rather
     * than silently dropping persistent drive or asserting immediate validity. */
    reset();warmup();sample(.04f,.60f,1,0);sample(.04f,.60f,1,0);
    assert(dob_current_admission.transitions==1&&mon.observer.initialized);
    assert(!mon.current.valid&&mon.observer.elapsed_s==0&&fabsf(mon.iq_lpf-.60f)<1e-6f);
    assert(dob_id_trace.epoch_resets==1);
    /* High but non-jumping Id STILL triggers the original 50mA gate. */
    reset();for(unsigned i=0;i<1000;i++)sample(i%2?.06f:-.06f,.22f,1,0);
    assert(mon.current.status==DOB_MONITOR_ID&&dob_current_admission.held==0);
    /* Ambiguous consecutive pairs latch only diagnostic exit, never re-arm. */
    reset();warmup();sample(.35f,.22f,1,0);sample(-.35f,.22f,1,0);
    assert(dob_current_admission.blocked&&dob_current_admission.exit_reason==DCA_EXIT_CONSECUTIVE);
    for(unsigned i=0;i<100;i++)sample(.04f,.22f,1,0);
    assert(!mon.current.valid&&!mon.observer.initialized&&dob_current_admission.budget_exits==1);
    /* Repeated isolated spikes cannot evade the bounded 32-epoch budget. */
    reset();sample(.04f,.22f,1,0);
    for(unsigned i=0;i<5;i++){sample(.35f,.22f,1,0);sample(.04f,.22f,1,0);}
    assert(dob_current_admission.blocked&&dob_current_admission.exit_reason==DCA_EXIT_RATE);
    /* Existing data/saturation rejection wins BEFORE local admission. */
    reset();warmup();sample(.04f,.22f,0,0);
    assert(mon.current.status&DOB_MONITOR_CURRENT);assert(!mon.have_sample);
    sample(.04f,.22f,1,0);assert(!mon.current.valid&&mon.observer.elapsed_s==0);
    sample(.04f,.22f,1,1);assert(mon.current.status&DOB_MONITOR_SATURATED);
    assert(!mon.have_sample&&!mon.current.valid);
    /* Full source-gap, timestamp wrap, finite values, and fault/STOP. */
    DobCurrentAdmission s={0};assert(DobAdmit_Push(&s,0xffffff00U,1000,.04f,.22f)==1);
    assert(DobAdmit_Push(&s,(uint32_t)(0xffffff00U+1000),1000,.04f,.22f)==1);
    assert(DobAdmit_Push(&s,(uint32_t)(0xffffff00U+4000),1000,.04f,.22f)==-1);
    assert(s.exit_reason==DCA_EXIT_TIME);
    s=(DobCurrentAdmission){0};assert(DobAdmit_Push(&s,1000,1000,NAN,.22f)==-1);
    reset();warmup();MechanicalDobMonitor_Lifecycle(&mon,1,1);
    assert(mon.frozen==DOB_SHADOW_FAULT&&!mon.current.valid);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);unsigned n=mon.observations;
    sample(.04f,.22f,1,0);assert(mon.observations==n);
    puts("PASS: synthetic admission, original quality gates, paired data and bounded recovery");
    return 0;
}

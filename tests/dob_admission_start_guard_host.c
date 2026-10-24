/* Native synthetic tests only; no physical current quality claims. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
static MechanicalDobMonitor mon;
static unsigned char buffer[DIT_BYTES+16];
static uint32_t enc,seq;
static float omega;
static void reset(void){
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};
    enc=1000;seq=20;omega=0;memset(buffer,0xA5,sizeof buffer);
    DobIdTrace_Bind(buffer,DIT_BYTES);DobIdTrace_Lifecycle(1,0);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);
}
static void sample(float id,float iq,unsigned valid){
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,1000,omega,0,&c,(uint8_t)valid);
    DobIdTrace_After(enc,seq,1000,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,200,omega*9.5492965855f,mon.current.iq_a,
        mon.current.adc_source_us,mon.current.adc_published_us);
    enc+=1000;seq+=20;
}
static void arm(void){
    omega=12.566371f;
    for(unsigned i=0;i<49;i++)sample(.04f,.22f,1);
    assert(!dob_current_admission.armed&&dob_current_admission.qualify_us==49000);
    sample(.04f,.22f,1);
    assert(dob_current_admission.armed&&dob_current_admission.decision==DCA_SEED);
    assert(mon.observer.initialized&&mon.observer.elapsed_s==0&&!mon.current.valid);
    assert(dob_id_trace.epoch_resets==1);
}
int main(int argc,char **argv){
    assert(sizeof(DobCurrentAdmission)==112&&sizeof(DobIdTraceFrame)==48&&DIT_BYTES==4608);
    reset();
    for(unsigned i=0;i<100;i++){
        sample(.04f,i%2?.6f:-.3f,1);
        assert(!dob_current_admission.armed&&!dob_current_admission.blocked);
        assert(!mon.current.valid&&mon.observer.elapsed_s==0);
    }
    assert(dob_current_admission.samples==0&&dob_current_admission.prearm_samples==100);
    arm();assert(fabsf(mon.iq_lpf-.22f)<1e-6f&&fabsf(mon.abs_id_lpf-.04f)<1e-6f);
    /* Event during acceleration; trace MUST NOT wait for 500ms at 600rpm. */
    for(unsigned i=0;i<20;i++)sample(.04f,.22f,1);
    uint32_t first_suspect_us=enc;
    sample(-.56f,.22f,1);
    assert(dob_id_trace.trigger_us==first_suspect_us&&dob_id_trace.stable_us==0);
    assert(dob_id_trace.post_count==1&&dob_current_admission.decision==DCA_SUSPECT);
    if(argc>1&&argv[1][0]=='b'){
        sample(.5f,-.3f,1);
        assert(dob_current_admission.blocked&&dob_current_admission.exit_reason==DCA_EXIT_CONSECUTIVE);
    }else{
        float warm=mon.observer.elapsed_s;sample(.04f,.22f,1);
        assert(dob_current_admission.isolated==1&&!mon.current.valid&&mon.observer.elapsed_s==warm);
    }
    for(unsigned i=0;i<1000;i++)sample(.04f,.22f,1);
    if(!dob_current_admission.blocked)assert(mon.current.valid);
    else assert(!mon.current.valid&&dob_current_admission.budget_exits==1);
    DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
    assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.post_count==32&&dob_id_trace.tail_count==48);
    for(unsigned i=DIT_BYTES;i<sizeof buffer;i++)assert(buffer[i]==0xA5);
    if(argc>1){
        _setmode(_fileno(stdout),_O_BINARY);
        fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(buffer,DIT_BYTES,1,stdout);return 0;
    }
    /* Chattering sign and invalid current break pre-arm qualification. */
    reset();omega=3;for(unsigned i=0;i<30;i++)sample(.04f,.22f,1);
    omega=-3;sample(.04f,.22f,1);assert(dob_current_admission.qualify_us==1000);
    sample(.04f,.22f,0);assert(dob_current_admission.qualify_us==0&&!dob_current_admission.armed);
    omega=1;sample(.04f,.22f,1);assert(dob_current_admission.qualify_us==0);
    /* The existing Id gate remains active even before arming. */
    reset();sample(.08f,.22f,1);assert(mon.current.status==DOB_MONITOR_ID);
    arm();assert(mon.abs_id_lpf==.04f&&!mon.current.valid);
    /* Sign symmetry, same 50ms qualification, no old pre-arm reference. */
    reset();omega=-3;for(unsigned i=0;i<50;i++)sample(.04f,-.22f,1);
    assert(dob_current_admission.armed&&dob_current_admission.qualify_sign==-1);
    assert(dob_current_admission.samples==1&&mon.observer.elapsed_s==0);
    puts("PASS: start guard, original boundaries, first-event timing and raw source alignment");
    return 0;
}

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
static void reset(void){
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};enc=1000;seq=20;
    memset(buffer,0xA5,sizeof buffer);DobIdTrace_Bind(buffer,DIT_BYTES);
    DobIdTrace_Lifecycle(1,0);MechanicalDobMonitor_Lifecycle(&mon,1,0);
}
static void sample_dt(float id,float iq,unsigned valid,uint32_t dt){
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,dt,62.831853f,0,&c,(uint8_t)valid);
    DobIdTrace_After(enc,seq,dt,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,0,600,mon.current.iq_a,
        mon.current.adc_source_us,mon.current.adc_published_us);
    enc+=dt;seq+=20;
}
static void sample(float id,float iq){sample_dt(id,iq,1,1000);}
static void warm(void){for(unsigned i=0;i<600;i++)sample(.02f,.20f);assert(mon.current.valid);}
static void binary(void){
    for(unsigned i=0;i<1400;i++)sample(.02f,.20f);
    DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
    assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.abi==6);
    for(unsigned i=DIT_BYTES;i<sizeof buffer;i++)assert(buffer[i]==0xA5);
    _setmode(_fileno(stdout),_O_BINARY);
    fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(buffer,DIT_BYTES,1,stdout);
}
int main(int argc,char **argv){
    assert(sizeof(DobCurrentAdmission)==160&&DOB_ADMIT_JUMP_CONFIRM_POINTS==3&&DOB_ID_BAD_CONFIRM_US==20000);
    if(argc>1&&!strcmp(argv[1],"replay")){
        DobCurrentAdmission s={0};unsigned t,dt;float id,iq;
        puts("time_us,decision,result,blocked,jump_run");
        while(scanf("%u %u %f %f",&t,&dt,&id,&iq)==4){
            int a=DobAdmit_Push(&s,t,dt,id,iq);
            printf("%u,%u,%d,%u,%u\n",t,s.decision,a,s.blocked,s.jump_run);
        }return 0;
    }
    /* One spike plus return: both pending/admitted, never silently held. */
    reset();warm();uint32_t resets=dob_id_trace.reset_calls_total;
    sample(.18f,.20f);assert(mon.current.valid&&dob_current_admission.decision==DCA_JUMP_PENDING);
    sample(.02f,.20f);assert(mon.current.valid&&dob_current_admission.jump_run==2);
    sample(.02f,.20f);assert(mon.current.valid&&!dob_current_admission.jump_run);
    assert(!dob_current_admission.held&&dob_id_trace.reset_calls_total==resets);
    /* Third raw-adjacent jump starts rejection, earlier samples are not
     * retroactively removed. Short hold freezes LPFs/warmup, no count latch. */
    reset();warm();
    sample(.02f,.40f);assert(mon.current.valid);
    sample(.02f,.20f);assert(mon.current.valid);
    float lp=mon.iq_lpf,warmup=mon.observer.elapsed_s;
    sample(.02f,.40f);assert(!mon.current.valid&&dob_current_admission.decision==DCA_RUN_REJECT);
    assert(mon.iq_lpf==lp&&mon.observer.elapsed_s==warmup&&!dob_id_trace.epoch_resets);
    sample(.02f,.20f);assert(!mon.current.valid&&dob_current_admission.jump_run==4);
    sample(.02f,.20f);assert(dob_current_admission.decision==DCA_GAP_RECOVERY&&!mon.current.valid);
    assert(mon.observer.elapsed_s==warmup);sample(.02f,.20f);assert(mon.current.valid);
    if(argc>1&&!strcmp(argv[1],"binary")){binary();return 0;}
    /* Exact threshold, both axes/signs; a persistent new level is one jump,
     * not three adjacent jumps, and is not held forever against an old level. */
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2){
        DobCurrentAdmission s={0};assert(DobAdmit_Push(&s,1000,1000,0,0)==1);
        assert(DobAdmit_Push(&s,2000,1000,axis?0:sign*.100f,axis?sign*.100f:0)==1);
        assert(!s.jump_run);
        assert(DobAdmit_Push(&s,3000,1000,axis?0:sign*.25f,axis?sign*.25f:0)==1);
        assert(s.decision==DCA_JUMP_PENDING&&s.jump_run==1);
        assert(DobAdmit_Push(&s,4000,1000,axis?0:sign*.25f,axis?sign*.25f:0)==1);
        assert(!s.jump_run&&!s.held);
    }
    /* Confirmation uses elapsed microseconds between observed high-filter
     * epochs, not sample count; interrupted runs cannot be summed. */
    DobCurrentAdmission gate={0};
    assert(!DobAdmit_IdGate(&gate,.061f,.060f,1000,1)&&gate.id_bad_us==0);
    for(unsigned i=0;i<19;i++)assert(!DobAdmit_IdGate(&gate,.061f,.060f,1000,1));
    assert(gate.id_bad_us==19000);
    assert(!DobAdmit_IdGate(&gate,.061f,.060f,999,1)&&gate.id_bad_us==19999);
    assert(DobAdmit_IdGate(&gate,.061f,.060f,1,1)&&gate.id_bad_entries==1);
    assert(DobAdmit_IdGate(&gate,.061f,.060f,1000,1)&&gate.id_bad_entries==1);
    assert(DobAdmit_IdGate(&gate,.061f,.060f,2000,0)&&gate.id_bad_us==0);
    assert(!DobAdmit_IdGate(&gate,.060f,.060f,1000,1)&&gate.id_bad_recoveries==1);
    assert(!DobAdmit_IdGate(&gate,.061f,.060f,1000,1));
    for(unsigned i=0;i<19;i++)assert(!DobAdmit_IdGate(&gate,.061f,.060f,1000,1));
    assert(!DobAdmit_IdGate(&gate,.061f,.060f,1000,0)&&gate.id_bad_us==0);
    /* Full monitor: first sustained event resets exactly once, repeated high
     * Id remains invalid without repeated reset. Below limit rewarms normally. */
    reset();warm();unsigned elapsed=0;
    while(!dob_current_admission.id_bad_latched){
        sample(.061f,.20f);assert(++elapsed<300);
        if(!dob_current_admission.id_bad_latched)assert(mon.current.valid);
    }
    assert(mon.current.status==DOB_MONITOR_ID&&!mon.current.valid&&!mon.observer.initialized);
    assert(dob_current_admission.id_bad_us>=20000&&dob_id_trace.epoch_resets==1);
    for(unsigned i=0;i<10;i++){
        sample(.061f,.20f);assert(!mon.current.valid&&!dob_id_trace.epoch_resets);
    }
    if(argc>1&&!strcmp(argv[1],"idbinary")){binary();return 0;}
    for(unsigned i=0;i<600;i++)sample(.02f,.20f);
    assert(mon.current.valid&&dob_current_admission.id_bad_entries==1&&dob_current_admission.id_bad_recoveries==1);
    /* Long rejected run -> invalid + recoverable fresh warmup; no session latch. */
    reset();warm();
    for(unsigned i=0;i<40;i++)sample(.02f,i%2?.20f:.45f);
    assert(!mon.current.valid&&!mon.observer.initialized&&dob_current_admission.gap_resets==1);
    assert(!dob_current_admission.blocked&&!dob_current_admission.budget_exits);
    sample(.02f,.20f);assert(dob_current_admission.decision==DCA_GAP_RESEED&&mon.observer.elapsed_s==0);
    for(unsigned i=0;i<397;i++)sample(.02f,.20f);
    assert(!mon.current.valid);sample(.02f,.20f);assert(mon.current.valid);
    /* Existing quality and protection are still independent. */
    sample_dt(.02f,.20f,0,1000);assert(!mon.current.valid&&!mon.have_sample);
    assert(!dob_current_admission.jump_run&&!dob_current_admission.id_bad_us);
    MechanicalDobMonitor_Lifecycle(&mon,1,1);assert(!mon.running&&mon.frozen==DOB_SHADOW_FAULT);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);assert(!mon.running);
    puts("PASS: three-point raw jump confirmation, sustained20ms Id gate, recoverable gaps, original safety");return 0;
}

/* Synthetic source-qualified observer samples, never hardware. */
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
static void sample(float id,float iq,unsigned valid){
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,1000,62.831853f,0,&c,(uint8_t)valid);
    DobIdTrace_After(enc,seq,1000,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,0,600,mon.current.iq_a,
        mon.current.adc_source_us,mon.current.adc_published_us);
    enc+=1000;seq+=20;
}
static void warm(void){for(unsigned i=0;i<600;i++)sample(.02f,.20f,1);assert(mon.current.valid);}
static int push(DobCurrentAdmission *s,uint32_t t,float id,float iq){return DobAdmit_Push(s,t,1000,id,iq);}
int main(int argc,char **argv){
    assert(DOB_ADMIT_JUMP_A==.100f&&DOB_MONITOR_MAX_FILTERED_ABS_ID_A==.060f);
    assert(sizeof(DobCurrentAdmission)==124&&DIT_ABI==5&&DIT_TAIL_US==16000);
    if(argc>1&&!strcmp(argv[1],"replay")){
        DobCurrentAdmission s={0};unsigned t,dt;float id,iq;
        puts("time_us,decision,result,blocked");
        while(scanf("%u %u %f %f",&t,&dt,&id,&iq)==4)
            {int a=DobAdmit_Push(&s,t,dt,id,iq);printf("%u,%u,%d,%u\n",t,s.decision,a,s.blocked);}
        return 0;
    }
    reset();warm();float lp=mon.abs_id_lpf,iq=mon.iq_lpf,w=mon.observer.elapsed_s;
    sample(-.25f,.45f,1);
    assert(!mon.current.valid&&mon.current.disturbance_a==0);
    assert(mon.abs_id_lpf==lp&&mon.iq_lpf==iq&&mon.observer.elapsed_s==w&&!dob_id_trace.epoch_resets);
    sample(.02f,.20f,1); /* Return is also a raw-adjacent jump: skip, not reset. */
    assert(dob_current_admission.decision==DCA_DIRECT_REJECT&&!mon.current.valid);
    assert(mon.abs_id_lpf==lp&&mon.observer.elapsed_s==w&&!dob_id_trace.epoch_resets);
    sample(.02f,.20f,1);
    assert(dob_current_admission.decision==DCA_GAP_RECOVERY&&!mon.current.valid);
    assert(mon.observer.elapsed_s==w&&!dob_id_trace.epoch_resets);
    sample(.02f,.20f,1);assert(mon.current.valid);
    if(argc>1){
        for(unsigned i=0;i<1200;i++)sample(.02f,.20f,1);
        DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
        assert(dob_id_trace.state==DIT_DONE);
        for(unsigned i=DIT_BYTES;i<sizeof buffer;i++)assert(buffer[i]==0xA5);
        _setmode(_fileno(stdout),_O_BINARY);
        fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(buffer,DIT_BYTES,1,stdout);return 0;
    }
    /* Boundaries, axes, directions, timestamp wrap. */
    DobCurrentAdmission s={0};assert(push(&s,0xfffff000U,0,0)==1);
    assert(push(&s,0xfffff3e8U,.100f,0)==1);
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2){
        s=(DobCurrentAdmission){0};assert(push(&s,1000,0,0)==1);
        assert(push(&s,2000,axis?0:sign*.1001f,axis?sign*.1001f:0)==0);
        assert(push(&s,3000,axis?0:sign*.1001f,axis?sign*.1001f:0)==2);
        assert(!s.blocked&&s.reference_id==s.candidate_id&&s.reference_iq==s.candidate_iq);
    }
    /* Actual V4 latch fixture: raw delta40.699mA must recover, not latch. */
    s=(DobCurrentAdmission){0};assert(push(&s,1000,-.050119f,.124609f)==1);
    assert(push(&s,2000,.017647f,.235945f)==0);
    assert(push(&s,3000,.046028f,.276645f)==2&&!s.blocked);
    assert(!s.budget_exits);
    /* Sparse and repeated exclusions: no count/rate latch, valid recovers. */
    reset();warm();
    for(unsigned i=0;i<50;i++){
        sample(.02f,.40f,1);assert(!mon.current.valid);
        sample(.02f,.20f,1);assert(!mon.current.valid);
        sample(.02f,.20f,1);assert(!mon.current.valid);
        sample(.02f,.20f,1);assert(mon.current.valid);
    }
    assert(!dob_current_admission.blocked&&!dob_current_admission.budget_exits);
    assert(dob_current_admission.held==100&&dob_current_admission.gap_resets==0);
    /* Repeated large jumps: no fake estimate. One reset after10ms, not every
     * excluded epoch. A later calm actual pair seeds then completes warmup. */
    reset();warm();
    for(unsigned i=0;i<30;i++){
        sample(.02f,i%2?.20f:.45f,1);assert(!mon.current.valid);
        if(i<10)assert(mon.observer.initialized);
    }
    assert(!mon.observer.initialized&&dob_current_admission.gap_resets==1);
    assert(!dob_current_admission.blocked&&!dob_current_admission.budget_exits);
    sample(.02f,.20f,1);
    assert(dob_current_admission.decision==DCA_GAP_RESEED&&mon.observer.initialized);
    assert(mon.observer.elapsed_s==0&&!mon.current.valid);
    for(unsigned i=0;i<397;i++)sample(.02f,.20f,1);
    assert(!mon.current.valid);sample(.02f,.20f,1);assert(mon.current.valid);
    /* Qualities still reject; Id LPF60mA gate, source time and real protection
     * are not bypassed and FAULT cannot auto restart the motor/observer. */
    reset();for(unsigned i=0;i<600;i++)sample(.060f,.20f,1);assert(mon.current.valid);
    reset();for(unsigned i=0;i<100;i++)sample(.061f,.20f,1);
    assert(mon.current.status==DOB_MONITOR_ID&&!mon.current.valid);
    sample(.02f,.20f,0);assert(!mon.have_sample&&!mon.current.valid);
    for(unsigned i=0;i<600;i++){sample(.02f,.20f,1);}
    assert(mon.current.valid);
    MechanicalDobMonitor_Lifecycle(&mon,1,1);
    assert(!mon.running&&mon.frozen==DOB_SHADOW_FAULT&&!mon.current.valid&&mon.current.disturbance_a==0);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);assert(!mon.running);
    puts("PASS: previous-raw skip-only; no count latch; short freeze and long recoverable rewarm; protection intact");return 0;
}

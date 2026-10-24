/* Native synthetic tests; replay mode covers only actual retained dense rows. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
static MechanicalDobMonitor mon;
static unsigned char buffer[DIT_BYTES+16];
static uint32_t enc=1000,seq=20;
static float omega=12.566371f;
static void reset(void){
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};enc=1000;seq=20;
    memset(buffer,0xA5,sizeof buffer);DobIdTrace_Bind(buffer,DIT_BYTES);
    DobIdTrace_Lifecycle(1,0);MechanicalDobMonitor_Lifecycle(&mon,1,0);
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
static void warm(void){for(unsigned i=0;i<600;i++)sample(.02f,.20f,1);assert(mon.current.valid);}
int main(int argc,char **argv){
    assert(DOB_ADMIT_JUMP_A==.100f&&DOB_MONITOR_MAX_FILTERED_ABS_ID_A==.060f&&sizeof(DobCurrentAdmission)==112);
    if(argc>1&&!strcmp(argv[1],"replay")){
        DobCurrentAdmission s={0};unsigned t,dt;float id,iq;
        puts("time_us,decision,result,blocked");
        while(scanf("%u %u %f %f",&t,&dt,&id,&iq)==4){
            int a=DobAdmit_Push(&s,t,dt,id,iq);
            printf("%u,%u,%d,%u\n",t,s.decision,a,s.blocked);
        }
        return 0;
    }
    reset();warm();float lp=mon.abs_id_lpf,iq=mon.iq_lpf,warmup=mon.observer.elapsed_s;
    sample(-.25f,.45f,1);
    assert(dob_current_admission.decision==DCA_DIRECT_REJECT&&!mon.current.valid);
    assert(mon.abs_id_lpf==lp&&mon.iq_lpf==iq&&mon.observer.elapsed_s==warmup);
    assert(dob_id_trace.epoch_resets==0&&!dob_current_admission.pending);
    assert(dob_current_admission.reference_id==.02f&&dob_current_admission.reference_iq==.20f);
    sample(.02f,.20f,1);
    assert(dob_current_admission.decision==DCA_GAP_RECOVERY&&!mon.current.valid);
    assert(mon.observer.elapsed_s==warmup&&dob_id_trace.epoch_resets==0);
    assert(dob_current_admission.isolated==0&&dob_current_admission.transitions==0);
    sample(.02f,.20f,1);assert(mon.current.valid);
    if(argc>1){
        for(unsigned i=0;i<1000;i++)sample(.02f,.20f,1);
        DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
        assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.abi==4);
        for(unsigned i=DIT_BYTES;i<sizeof buffer;i++)assert(buffer[i]==0xA5);
        _setmode(_fileno(stdout),_O_BINARY);
        fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(buffer,DIT_BYTES,1,stdout);return 0;
    }
    /* Exact 100mA boundary allowed, strictly larger rejected; both axes/signs. */
    DobCurrentAdmission s={0};assert(DobAdmit_Push(&s,1000,1000,0,0)==1);
    assert(DobAdmit_Push(&s,2000,1000,.100f,0)==1);
    s=(DobCurrentAdmission){0};assert(DobAdmit_Push(&s,1000,1000,0,0)==1);
    assert(DobAdmit_Push(&s,2000,1000,-.100f,0)==1);
    for(unsigned axis=0;axis<2;axis++)for(int sign=-1;sign<=1;sign+=2){
        s=(DobCurrentAdmission){0};assert(DobAdmit_Push(&s,1000,1000,0,0)==1);
        assert(DobAdmit_Push(&s,2000,1000,axis?0:sign*.1001f,axis?sign*.1001f:0)==0);
        assert(s.decision==DCA_DIRECT_REJECT&&!s.pending&&s.reference_id==0&&s.reference_iq==0);
        assert(DobAdmit_Push(&s,3000,1000,0,0)==2&&s.decision==DCA_GAP_RECOVERY);
    }
    /* Actual prior first-event Id/Iq values. This is a short fixture seeded
     * at the old -2.013ms pair, NOT replay of the unrecorded whole session. */
    s=(DobCurrentAdmission){0};
    assert(DobAdmit_Push(&s,1000,1000,-.04419266f,.20079567f)==1);
    assert(DobAdmit_Push(&s,2000,1000,-.25098321f,.44871154f)==0);
    assert(DobAdmit_Push(&s,3000,1000,.00987960f,.14761427f)==2);
    assert(DobAdmit_Push(&s,4000,1000,.01538207f,.14278735f)==1);
    assert(s.transitions==0&&s.isolated==0&&!s.blocked);
    /* Sustained actual step cannot be silently rebased, ignored forever or
     * claim valid output; existing exit bounds still apply. */
    reset();warm();sample(.02f,.40f,1);sample(.02f,.40f,1);
    assert(dob_current_admission.blocked&&dob_current_admission.exit_reason==DCA_EXIT_CONSECUTIVE);
    assert(!mon.current.valid&&!mon.observer.initialized);
    for(unsigned i=0;i<20;i++)sample(.02f,.20f,1);
    assert(!mon.current.valid&&dob_current_admission.budget_exits==1);
    /* Rate bound, no threshold/limit increase and old Id gate intact. */
    reset();warm();
    for(unsigned i=0;i<5;i++){sample(.02f,.40f,1);sample(.02f,.20f,1);}
    assert(dob_current_admission.blocked&&dob_current_admission.exit_reason==DCA_EXIT_RATE);
    reset();for(unsigned i=0;i<600;i++)sample(.060f,.20f,1);
    assert(mon.current.valid&&mon.abs_id_lpf==.060f); /* Equal boundary allowed. */
    reset();for(unsigned i=0;i<100;i++)sample(.061f,.20f,1);
    assert(mon.current.status==DOB_MONITOR_ID&&dob_current_admission.held==0);
    sample(.061f,.20f,0);assert(!mon.have_sample&&!mon.current.valid);
    MechanicalDobMonitor_Lifecycle(&mon,1,1);assert(!mon.running&&mon.frozen==DOB_SHADOW_FAULT);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);assert(!mon.running);
    puts("PASS: direct100, immediate paired rejection, no candidate/transition, preserved safeguards");return 0;
}

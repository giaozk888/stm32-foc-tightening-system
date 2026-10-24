/* Production observer code, synthetic samples only; no hardware. */
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
    mon=(MechanicalDobMonitor){0};dob_id_trace=(DobIdTraceState){0};enc=0;seq=0;
    memset(buffer,0xA5,sizeof buffer);DobIdTrace_Bind(buffer,DIT_BYTES);
    DobIdTrace_Lifecycle(1,0);MechanicalDobMonitor_Lifecycle(&mon,1,0);
}
static void sample_dt(float id,float iq,unsigned valid,uint32_t dt){
    enc+=dt;seq+=20;
    MechanicalCurrent c={2,seq,enc+115,enc+134,id,iq,0};
    DobIdTrace_Begin((uint8_t)mon.have_sample);
    MechanicalDobMonitor_Observe(&mon,enc+160,enc,dt,62.831853f,0,&c,(uint8_t)valid);
    DobIdTrace_After(enc,seq,dt,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
        mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
        (uint8_t)mon.have_sample,600,0,600,mon.current.iq_a,
        mon.current.adc_source_us,mon.current.adc_published_us);
}
static void sample(float id,float iq){sample_dt(id,iq,1,1000);}
static void warm(void){for(unsigned i=0;i<600;i++)sample(.02f,.20f);assert(mon.current.valid);}
static void binary(void){
    for(unsigned i=0;i<1400;i++)sample(.02f,.20f);
    DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
    assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.abi==7);
    for(unsigned i=DIT_BYTES;i<sizeof buffer;i++)assert(buffer[i]==0xA5);
    _setmode(_fileno(stdout),_O_BINARY);
    fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(buffer,DIT_BYTES,1,stdout);
}
int main(int argc,char **argv){
    assert(sizeof(DobCurrentAdmission)==204&&sizeof(DobIdTraceFrame)==64&&DIT_BYTES==4608);
    if(argc>1&&!strcmp(argv[1],"replay")){
        DobCurrentAdmission s={0};unsigned t,dt;float id,iq;
        puts("time_us,decision,result,passed,held");
        while(scanf("%u %u %f %f",&t,&dt,&id,&iq)==4){
            int a=DobAdmit_Push(&s,t,dt,id,iq);
            printf("%u,%u,%d,%u,%u\n",t,s.decision,a,s.passed,s.held);
        }return 0;
    }
    reset();warm();float lp=mon.abs_id_lpf,qlp=mon.iq_lpf,w=mon.observer.elapsed_s;
    uint32_t passed=dob_current_admission.passed,good=mon.valid_samples;
    MechanicalDobShadow before=mon.observer;
    sample(.700f,.20f);
    assert(dob_current_admission.decision==DCA_QUALITY_WAIT&&!mon.current.valid);
    assert(!dob_current_admission.filter_updated&&mon.abs_id_lpf==lp&&mon.iq_lpf==qlp);
    assert(mon.observer.elapsed_s==w&&memcmp(&before,&mon.observer,sizeof before)==0);
    assert(!dob_id_trace.epoch_resets&&dob_current_admission.passed==passed&&mon.valid_samples==good);
    assert(dob_current_admission.quality_reason&(DQ_ID_JUMP|DQ_WAIT));
    sample(.02f,.20f);
    assert(dob_current_admission.decision==DCA_QUALITY_RETURN&&!mon.current.valid);
    assert(mon.abs_id_lpf==lp&&mon.observer.elapsed_s==w&&!dob_id_trace.epoch_resets);
    sample(.02f,.20f);assert(mon.current.valid);
    if(argc>1&&!strcmp(argv[1],"binary")){binary();return 0;}
    if(argc==1)printf("SINGLE_SPIKE before=%.9g after=%.9g hard_resets=0 valid_recovered=1\n",lp,mon.abs_id_lpf);
    /* An unqualified startup spike cannot seed the initial LPF either. */
    DobCurrentAdmission s={0};
    assert(DobAdmit_Push(&s,1000,1000,.700f,.20f)==0&&!s.seeded);
    assert(DobAdmit_Push(&s,2000,1000,.02f,.20f)==0&&!s.seeded);
    assert(DobAdmit_Push(&s,3000,1000,.02f,.20f)==0&&!s.seeded);
    assert(DobAdmit_Push(&s,4000,1000,.02f,.20f)==1&&s.seeded&&s.reference_id==.02f);
    /* Exact reproduced Id/Iq sequence: +699.8mA is quarantined, not applied
     * as the second jump or replayed when a later level is reconfirmed. */
    s=(DobCurrentAdmission){0};
    for(uint32_t t=1000;t<=3000;t+=1000)DobAdmit_Push(&s,t,1000,-.07751255f,.07718689f);
    assert(s.seeded);
    assert(DobAdmit_Push(&s,4000,1000,.04516713f,.05206013f)==0);
    assert(DobAdmit_Push(&s,5000,1000,.69978184f,-.21561746f)==0);
    assert(s.reference_id==-.07751255f);
    assert(DobAdmit_Push(&s,6000,1000,.03073925f,.06265529f)==0);
    assert(DobAdmit_Push(&s,7000,1000,.02354301f,.07509454f)==0);
    assert(DobAdmit_Push(&s,8000,1000,.00582795f,.09415615f)==2);
    assert(s.reference_id==.00582795f&&!s.pending&&!s.blocked);
    reset();warm();sample(-.0775f,.20f);lp=mon.abs_id_lpf;w=mon.observer.elapsed_s;
    sample(.0452f,.20f);assert(mon.abs_id_lpf==lp);
    sample(.6998f,.20f);assert(mon.abs_id_lpf==lp&&!dob_current_admission.filter_updated);
    sample(.0307f,.20f);assert(mon.abs_id_lpf==lp);
    sample(.0235f,.20f);assert(mon.abs_id_lpf==lp);
    sample(.0058f,.20f);assert(mon.abs_id_lpf<lp&&mon.observer.elapsed_s==w&&!dob_id_trace.epoch_resets);
    sample(.0058f,.20f);assert(mon.current.valid);
    if(argc==1)printf("REPRODUCED_SPIKE quarantine_lpf=%.9g hard_resets=0\n",lp);
    /* A quarantined sample cannot clear, advance or rebase an existing Id
     * confirmation timer. Qualified recovery later explicitly breaks time
     * continuity instead of charging missing data to the timer. */
    reset();warm();dob_current_admission.id_bad_us=5000;dob_current_admission.id_above_previous=1;
    sample(.700f,.20f);
    assert(dob_current_admission.id_bad_us==5000&&dob_current_admission.id_above_previous==1);
    sample(.02f,.20f);assert(dob_current_admission.id_bad_us==0&&!dob_current_admission.id_above_previous);
    /* A coherent REAL sustained level is not deleted forever as noise.
     * First2 withheld, latest3rd admitted, existing60mA/20ms model-domain gate
     * still detects sustained Id. No new raw absolute-current cap is invented. */
    reset();warm();lp=mon.abs_id_lpf;
    sample(.700f,.20f);assert(mon.abs_id_lpf==lp);
    sample(.700f,.20f);assert(mon.abs_id_lpf==lp);
    sample(.700f,.20f);
    assert(dob_current_admission.decision==DCA_QUALITY_LEVEL&&!mon.current.valid);
    assert(dob_current_admission.level_confirms==1&&mon.abs_id_lpf>lp);
    unsigned ticks=0;
    while(!dob_current_admission.id_bad_latched){sample(.700f,.20f);assert(++ticks<=21);}
    assert(dob_current_admission.id_bad_us==20000&&!mon.current.valid);
    assert(mon.current.status==DOB_MONITOR_ID&&dob_id_trace.epoch_resets==1);
    for(unsigned i=0;i<10;i++){sample(.700f,.20f);assert(!dob_id_trace.epoch_resets&&!mon.current.valid);}
    if(argc>1&&!strcmp(argv[1],"idbinary")){binary();return 0;}
    for(unsigned i=0;i<650;i++)sample(.02f,.20f);
    assert(mon.current.valid&&dob_current_admission.id_bad_entries==1&&dob_current_admission.id_bad_recoveries==1);
    puts("PERSISTENT_ID confirmed_us=20000 entry_resets=1 recovered=1");
    /* Never-consistent abnormal data: no held-data integration or endless
     * valid output; one reset after the unchanged10ms missing-data bound. */
    reset();warm();uint32_t resets=dob_id_trace.reset_calls_total;
    for(unsigned i=0;i<35;i++){
        sample(i%2?.700f:-.700f,.20f);assert(!mon.current.valid);
    }
    assert(!mon.observer.initialized&&dob_current_admission.gap_resets==1);
    assert(dob_id_trace.reset_calls_total==resets+1&&!dob_current_admission.blocked);
    sample(.02f,.20f);assert(mon.observer.initialized&&mon.observer.elapsed_s==0);
    assert(!dob_id_trace.epoch_resets); /* No redundant reset on long-gap reseed. */
    for(unsigned i=0;i<398;i++)sample(.02f,.20f);
    assert(mon.current.valid);
    /* Iq-correlated bad pairs are quarantined too; no altered FOC feedback. */
    reset();warm();lp=mon.abs_id_lpf;qlp=mon.iq_lpf;
    sample(.03f,.700f);assert(mon.abs_id_lpf==lp&&mon.iq_lpf==qlp&&!mon.current.valid);
    sample(.02f,.20f);sample(.02f,.20f);assert(mon.current.valid);
    /* Equal100mA allowed; finite/source/time failures stay independent. */
    s=(DobCurrentAdmission){0};
    for(uint32_t t=1000;t<=3000;t+=1000)DobAdmit_Push(&s,t,1000,0,0);
    assert(DobAdmit_Push(&s,4000,1000,.100f,0)==1);
    assert(DobAdmit_Push(&s,5000,1000,NAN,0)==-2);
    sample_dt(.02f,.20f,0,1000);assert(!mon.current.valid&&!mon.have_sample);
    MechanicalDobMonitor_Lifecycle(&mon,1,1);assert(!mon.running&&mon.frozen==DOB_SHADOW_FAULT);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);assert(!mon.running);
    puts("PASS: pre-LPF quarantine, unpolluted single-spike recovery, sustained fault detection, no safety change");return 0;
}

#include "dob_recovery_timing.h"
#include "mechanical_dob_monitor.h"
#include "dob_normal_control.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#undef assert
#define assert(c) do {if(!(c)){fprintf(stderr,"CHECK failed: %s at line %d\n",#c,__LINE__);exit(2);}}while(0)
static DobTrendClassifier s,reference;
static MechanicalDobMonitor monitor;
static DobFeedbackCandidate feedback;
static uint32_t t=100000,sequence;
static void reset(uint32_t origin){
    memset(&s,0,sizeof s);memset(&reference,0,sizeof reference);
    memset(&monitor,0,sizeof monitor);memset(&feedback,0,sizeof feedback);
    memset(&dob_recovery_timing,0,sizeof dob_recovery_timing);
    t=origin;sequence=0;DobNormal_Lifecycle(&monitor,&feedback,1,0);
}
static void compare_classifier(void){
    DobTrendClassifier a=s,b=reference;
    memset(a.value+75,0,25*sizeof(float));memset(a.stamp+75,0,25*sizeof(uint32_t));
    memset(b.value+75,0,25*sizeof(float));memset(b.stamp+75,0,25*sizeof(uint32_t));
    assert(memcmp(&a,&b,sizeof a)==0);
}
static void tick(float omega,float id,int skip){
    t+=1000;sequence+=20;
    MechanicalCurrent c={.seq=sequence,.source_us=t,.published_us=t+5,.iq=.16f,.id=id};
    float previous_warm=monitor.observer.elapsed_s;
    MechanicalDobMonitor_Observe(&monitor,t+20,t,1000,omega,0,&c,1);
    if(id>.6f)assert(monitor.observer.elapsed_s==previous_warm&&!dob_current_admission.filter_updated);
    DobTrendInput in={.encoder_us=t,.observed_us=t+20,.source_us=monitor.current.adc_source_us,
        .disturbance_a=monitor.current.disturbance_a,.direction=1,.running=1,
        .valid=(uint8_t)monitor.current.valid,.filter_updated=(uint8_t)(dob_current_admission.filter_updated&&!skip)};
    DobTrendClassifier_Step(&reference,in);DobTrendClassifier_Step(&s,in);
    MechanicalDobShadow before=monitor.observer;
    DobRecovery_Observe(&s,&in,monitor.current.status,omega,dob_current_admission.armed,monitor.observer.elapsed_s);
    assert(memcmp(&before,&monitor.observer,sizeof before)==0);compare_classifier();
}
static void closure(const DobRecoveryRecord *r){
    uint32_t sum=r->low_us+r->qualify_us+r->warm_us+r->quality_us+r->window_us+r->level_us+r->trend_us+r->other_us;
    assert(sum==r->end_us-r->start_us);
}
static void integration(void){
    reset(100000);
    DobTrendInput off={.encoder_us=t,.running=0};
    for(unsigned k=0;k<10;++k){off.encoder_us+=1000;DobRecovery_Observe(&s,&off,DOB_MONITOR_OFF,0,0,0);}
    assert(!dob_recovery_timing.abi&&!dob_recovery_timing.calls&&!dob_recovery_timing.records);
    for(unsigned k=0;k<900;++k)tick(25,.001f,0);
    assert(s.trend_valid&&dob_current_admission.armed&&dob_recovery_timing.records==1);
    DobRecoveryRecord r;DobRecovery_Read(&s,0,&r);closure(&r);
    assert((r.flags_reason&(DRT_COMPLETE|DRT_INITIAL))==(DRT_COMPLETE|DRT_INITIAL));
    assert(r.qualify_us>0&&r.warm_us>=238000&&r.window_us&&r.level_us&&r.trend_us);
    uint32_t before_records=dob_recovery_timing.records;
    for(unsigned k=0;k<2;++k)tick(25,.001f,1);
    tick(25,.001f,0);
    assert(dob_recovery_timing.records==before_records&&dob_recovery_timing.short_gaps==1);
    for(unsigned k=0;k<70;++k)tick(0,.001f,0);
    for(unsigned k=0;k<900;++k)tick(25,k==120?.7f:.001f,0);
    assert(s.trend_valid&&dob_recovery_timing.records==2);
    DobRecovery_Read(&s,1,&r);closure(&r);
    assert((r.flags_reason&(DRT_COMPLETE|DRT_CLASS_RESET))==(DRT_COMPLETE|DRT_CLASS_RESET));
    assert(!r.qualify_us); /* Armed is one-way: no invented second50ms qualification. */
    assert(r.low_us&&r.quality_us&&r.warm_us>=238000&&r.window_us&&r.level_us&&r.trend_us);
    /*20ms since LAST GOOD =19ms since the first bad 1ms epoch. */
    assert(r.start_us-dob_recovery_timing.first_invalid_us[1]==19000);
    assert(r.quality_us>=2000&&r.warm_credit_us<=r.warm_us+1000);
    printf("RECOVERY span=%lu low=%lu qualify=%lu warm_wall=%lu warm_credit=%lu quality=%lu window=%lu level=%lu trend=%lu\n",
        (unsigned long)(r.end_us-r.start_us),(unsigned long)r.low_us,(unsigned long)r.qualify_us,
        (unsigned long)r.warm_us,(unsigned long)r.warm_credit_us,(unsigned long)r.quality_us,
        (unsigned long)r.window_us,(unsigned long)r.level_us,(unsigned long)r.trend_us);
}
static void wrap_and_stop(void){
    reset(UINT32_MAX-500000U);
    for(unsigned cycle=0;cycle<5;++cycle){
        for(unsigned k=0;k<70;++k)tick(0,.001f,0);
        for(unsigned k=0;k<700;++k)tick(25,.001f,0);
    }
    assert(dob_recovery_timing.records==5&&dob_recovery_timing.overwritten==2);
    for(unsigned k=0;k<3;++k){DobRecoveryRecord r;DobRecovery_Read(&s,k,&r);closure(&r);}
    for(unsigned k=0;k<30;++k)tick(0,.001f,0);
    DobTrendInput in={.encoder_us=t+1000,.running=0};
    DobRecovery_Observe(&s,&in,DOB_MONITOR_OFF,0,1,0);
    assert(dob_recovery_timing.interrupted==1&&!dob_recovery_timing.active);
    DobRecoveryRecord r;DobRecovery_Read(&s,(dob_recovery_timing.records-1)%3,&r);closure(&r);
    assert((r.flags_reason&DRT_STOPPED)&&!(r.flags_reason&DRT_COMPLETE));
}
static void uncertain_clock_and_fault(void){
    reset(100000);
    for(unsigned k=0;k<900;++k)tick(25,.001f,0);
    for(unsigned k=0;k<30;++k)tick(0,.001f,0);
    t+=5000;tick(0,.001f,0); /* Unobserved scheduling hole: never claim precise phase timing. */
    for(unsigned k=0;k<700;++k)tick(25,.001f,0);
    DobRecoveryRecord r;DobRecovery_Read(&s,(dob_recovery_timing.records-1)%3,&r);closure(&r);
    assert((r.flags_reason&DRT_CLOCK_UNCERTAIN)&&dob_recovery_timing.clock_errors);
    for(unsigned k=0;k<30;++k)tick(0,.001f,0);
    DobTrendInput in={.encoder_us=t+1000,.running=1,.fault=1};
    DobRecovery_Observe(&s,&in,DOB_SHADOW_FAULT,0,1,0);
    assert(dob_recovery_timing.interrupted==1&&!dob_recovery_timing.active);
    DobRecovery_Read(&s,(dob_recovery_timing.records-1)%3,&r);closure(&r);
    assert((r.flags_reason&DRT_STOPPED)&&!(r.flags_reason&DRT_COMPLETE));
}
int main(int argc,char **argv){
    integration();
    if(argc==2){
        FILE *f=fopen(argv[1],"wb");assert(f);
        assert(fwrite(&dob_recovery_timing,1,sizeof dob_recovery_timing,f)==sizeof dob_recovery_timing);
        assert(fwrite(s.value+75,1,100,f)==100);assert(fwrite(s.stamp+75,1,100,f)==100);fclose(f);
    }
    wrap_and_stop();
    uncertain_clock_and_fault();
    puts("PASS: actual monitor+classifier untouched; initial/low/warm/window/confirmation timing; no second qualification; spike/short gap; partition closure; ring/clock wrap; stop marked incomplete");
    return 0;
}

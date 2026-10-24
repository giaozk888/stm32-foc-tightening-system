/* OFFLINE synthetic stimulus, calling the actual candidate C modules.
 * This is not a captured motor waveform and cannot access a device. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
#include "id_steady_stats.h"

int main(void){
    const char *cases[]={"bipolar_60mA","one_pulse_base40mA","one_pulse_base10mA",
                         "repeated_pulses_60ms","quality_gap_reseed","threshold_equal","jitter_dt"};
    puts("case,t_us,id_A,filtered_abs_A,signed_lpf_A,status,valid,warmup_us,stats_filtered_total_us,have_sample");
    assert(ID_STEADY_THRESHOLD_A==DOB_MONITOR_MAX_FILTERED_ABS_ID_A);
    for(unsigned c=0;c<sizeof(cases)/sizeof(cases[0]);c++){
        MechanicalDobMonitor mon={0};IdSteadyStats stats={0};
        MechanicalDobMonitor_Lifecycle(&mon,1,0);IdSteady_Lifecycle(&stats,1,0);
        uint32_t enc=1000,seq=20;float signed_lpf=0,golden=0;unsigned seed=0;
        for(unsigned i=0;i<2000;i++){
            uint32_t dt=c==6?(i%2?1050:950):1000;
            if(i) enc+=dt;
            float id=(c==2||c==4)?.01f:c==5?.05f:.04f;
            if(c==0) id=i%2?-.06f:.06f;
            if((c==1||c==2||c==6)&&i==800) id=.30f;
            if(c==3&&i>=800&&i<=1520&&(i-800)%60==0) id=.30f;
            if(c==4&&i==801) id=.08f;
            unsigned valid=!(c==4&&i==800);
            float k=(float)dt/(20000.f+(float)dt);
            if(!i) signed_lpf=id;else signed_lpf+=k*(id-signed_lpf);
            if(valid){if(!seed) golden=fabsf(id);else golden+=k*(fabsf(id)-golden);seed=1;}
            else seed=0;
            MechanicalCurrent current={2,seq,enc+115,enc+134,id,.22f,0};
            MechanicalDobMonitor_Observe(&mon,enc+160,enc,dt,62.831853f,0,&current,(uint8_t)valid);
            IdSteady_Observe(&stats,enc+160,enc,dt,600,0,600,0,0,&current,(uint8_t)valid,
                mon.abs_id_lpf,mon.current.status,(uint8_t)mon.current.valid);
            if(valid){
                assert(fabsf(mon.abs_id_lpf-golden)<2e-6f);
                assert((mon.current.status==DOB_MONITOR_ID)==(mon.abs_id_lpf>.05f));
                if(mon.current.status==DOB_MONITOR_ID){
                    assert(mon.observer.elapsed_s==0 && !mon.observer.initialized && !mon.current.valid);
                    assert(mon.have_sample); /* Id rejection does NOT clear the Id LPF. */
                }
            }
            printf("%s,%u,%.9g,%.9g,%.9g,%u,%u,%.9g,%u,%u\n",cases[c],enc-1000,
                (double)id,(double)mon.abs_id_lpf,(double)signed_lpf,mon.current.status,
                mon.current.valid,(double)mon.observer.elapsed_s*1e6,stats.filtered_over.total_us,mon.have_sample);
            seq+=20;
        }
    }
    return 0;
}

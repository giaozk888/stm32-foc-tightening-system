#include "dob_short_low_recovery.h"
#include "dob_trend_continuous.h"
#include <string.h>
#if !defined(FOC_DOB_TREND_WINDOW75) || !defined(FOC_DOB_TREND_CONTINUOUS)
#error Short-low audit requires the exclusive window75 tail
#endif
static void transfer(uint32_t slot,DobLowRecoveryEvent *event,uint8_t write){
    DobTrendClassifier *s=&dob_trend_continuous_arena->classifier;
    uint32_t offset=slot*96U,left=96U;unsigned char *p=(unsigned char *)event;
    while(left){
        unsigned char *part=offset<100U?(unsigned char *)&s->value[75]+offset:
            (unsigned char *)&s->stamp[75]+offset-100U;
        uint32_t n=offset<100U?100U-offset:200U-offset;if(n>left)n=left;
        if(write)memcpy(part,p,n);else memcpy(p,part,n);
        offset+=n;p+=n;left-=n;
    }
}
void DobLowAudit_Record(const void *recovery,const void *monitor,uint32_t enc,
    float omega,uint32_t input_valid,uint32_t reason,uint32_t site){
    if(!dob_trend_continuous_arena)return;
    const DobLowRecovery *g=recovery;const MechanicalDobMonitor *m=monitor;
    /* Lifecycle hooks have no new encoder epoch: label the last actual one. */
    if(!enc)enc=m->current.sample_us;
    DobLowRecoveryEvent e={
        enc,reason,site,g->mode,m->current.status,input_valid,dob_current_admission.filter_updated,
        dob_current_admission.decision,dob_current_admission.quality_reason,g->quiet_n,
        g->quiet_n?enc-g->quiet_start:0,g->low_start,g->return_start,
        enc-g->low_start,g->mode==DLR_LOW?0:enc-g->return_start,
        m->current.adc_source_us,m->current.adc_published_us,dob_current_admission.accepted_gap_us,
        omega,m->current.id_a,m->current.iq_a,m->abs_id_lpf,
        g->quiet_n?g->w_max-g->w_min:0,g->quiet_n?g->drive_max-g->drive_min:0};
    DobTrendClassifier *s=&dob_trend_continuous_arena->classifier;
    uint32_t count=s->stamp[99];
    if(!count)transfer(0,&e,1);
    transfer(1,&e,1);
    s->stamp[98]=0xD10A0001U;
    if(count!=UINT32_MAX)s->stamp[99]=count+1U;
}

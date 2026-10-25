#include "dob_recovery_timing.h"
#include "mechanical_dob_monitor.h"
#include <math.h>
#include <string.h>
#if !defined(FOC_DOB_TREND_WINDOW75) || !defined(FOC_DOB_TREND_CONTINUOUS)
#error Recovery timing requires the exclusive75-point continuous A recorder
#endif
DobRecoveryTiming dob_recovery_timing;
_Static_assert(DTS_WINDOW==100U&&sizeof(float)==4U,"Borrowed tail layout");
static void transfer(DobTrendClassifier *s,uint32_t slot,DobRecoveryRecord *r,uint8_t write){
    uint32_t offset=slot*48U,remaining=48U;unsigned char *p=(unsigned char *)r;
    while(remaining){
        unsigned char *part=offset<100U?(unsigned char *)&s->value[75]+offset:
            (unsigned char *)&s->stamp[75]+offset-100U;
        uint32_t n=offset<100U?100U-offset:200U-offset;if(n>remaining)n=remaining;
        if(write)memcpy(part,p,n);else memcpy(p,part,n);
        p+=n;offset+=n;remaining-=n;
    }
}
void DobRecovery_Read(const DobTrendClassifier *s,uint32_t slot,DobRecoveryRecord *r){
    if(slot>3U){*r=(DobRecoveryRecord){0};return;}
    transfer((DobTrendClassifier *)s,slot,r,0);
}
static uint32_t phase(const DobTrendClassifier *s,const DobTrendInput *in,uint32_t status,float omega,uint32_t armed){
    if(!in->running||in->fault)return DRT_OTHER;
    if(status&(DOB_SHADOW_FAULT|DOB_MONITOR_OFF|DOB_MONITOR_TIME|DOB_MONITOR_SEQUENCE))return DRT_QUALITY;
    if(!isfinite(omega))return DRT_QUALITY;
    if((status&DOB_SHADOW_ZERO_SPEED)||fabsf(omega)<DOB_OBSERVE10_MIN_RAD_S)return DRT_LOW;
    if(!armed)return DRT_QUALIFY;
    if((status&(DOB_MONITOR_CURRENT|DOB_MONITOR_ID))||!in->filter_updated)return DRT_QUALITY;
    if(!in->valid)return status&DOB_SHADOW_WARMUP?DRT_WARM:DRT_OTHER;
    if(!s->updated&&(s->reason==7U||s->reason==8U))return DRT_WINDOW;
    if(!s->valid)return DRT_LEVEL;
    if(!s->trend_valid)return DRT_TREND;
    return DRT_READY;
}
static void add(DobRecoveryRecord *r,uint32_t state,uint32_t dt){
    switch(state){
    case DRT_LOW:r->low_us+=dt;break;case DRT_QUALIFY:r->qualify_us+=dt;break;
    case DRT_WARM:r->warm_us+=dt;break;case DRT_QUALITY:r->quality_us+=dt;break;
    case DRT_WINDOW:r->window_us+=dt;break;case DRT_LEVEL:r->level_us+=dt;break;
    case DRT_TREND:r->trend_us+=dt;break;default:r->other_us+=dt;break;
    }
}
void DobRecovery_Observe(DobTrendClassifier *s,const DobTrendInput *in,
    uint32_t status,float omega,uint32_t armed,float warm_elapsed_s){
    DobRecoveryTiming *h=&dob_recovery_timing;
    /* Power-off preflight also flushes observations. It must not initialize
     * the run timer or manufacture an initial episode before START. */
    if(!in->running&&!h->active)return;
    if(!h->abi&&in->fault)return;
    uint32_t now=in->encoder_us,current=phase(s,in,status,omega,armed);
    uint32_t warm=isfinite(warm_elapsed_s)&&warm_elapsed_s>=0&&warm_elapsed_s<4000.f?
        (uint32_t)(warm_elapsed_s*1e6f+.5f):0;
    DobRecoveryRecord r;
    if(!h->abi){
        *h=(DobRecoveryTiming){.abi=1U,.last_us=now,.phase=current,.warm_us=warm};
        if(in->running&&!in->fault&&current!=DRT_READY){
            r=(DobRecoveryRecord){.start_us=now,.end_us=now,.flags_reason=DRT_INITIAL|status};
            transfer(s,3,&r,1);h->active=1;h->pending_first_invalid_us=now;
        }
    }
    ++h->calls;
    if(h->active){
        transfer(s,3,&r,0);uint32_t dt=now-h->last_us;
        if(h->calls>1U&&(!dt||dt>2000U)){++h->clock_errors;r.flags_reason|=DRT_CLOCK_UNCERTAIN;}
        add(&r,h->phase,dt);r.end_us=now;r.flags_reason|=status;
        if((h->phase==DRT_WARM||current==DRT_WARM)&&warm>=h->warm_us&&warm-h->warm_us<=2000U)
            r.warm_credit_us+=warm-h->warm_us;
        if(s->resets!=h->last_classifier_resets){
            if(r.flags_reason&DRT_CLASS_RESET)r.flags_reason|=DRT_MULTIPLE_RESETS;
            else if(!(r.flags_reason&DRT_INITIAL)){
                /* Match the previously reported440ms interval: classify from
                 * actual quality-reset epoch, not the earlier first bad point.
                 * Keep first-invalid timestamp separately, do not hide lead-in. */
                uint32_t flags=r.flags_reason|DRT_CLASS_RESET;
                r=(DobRecoveryRecord){.start_us=now,.end_us=now,.flags_reason=flags};
            }
        }
        if(current==DRT_READY||!in->running||in->fault){
            if(now-r.start_us>=20000U||(r.flags_reason&DRT_INITIAL)||!in->running||in->fault){
                if(current==DRT_READY){r.flags_reason|=DRT_COMPLETE;++h->completed;}
                else{r.flags_reason|=DRT_STOPPED;++h->interrupted;}
                h->first_invalid_us[h->records%3U]=h->pending_first_invalid_us;
                transfer(s,h->records%3U,&r,1);
                if(++h->records>3U)++h->overwritten;
            }else ++h->short_gaps;
            h->active=0;
        }
        transfer(s,3,&r,1);
    }else if(in->running&&!in->fault&&current!=DRT_READY){
        r=(DobRecoveryRecord){.start_us=now,.end_us=now,.flags_reason=status};
        if(s->resets!=h->last_classifier_resets)r.flags_reason|=DRT_CLASS_RESET;
        transfer(s,3,&r,1);h->active=1;h->pending_first_invalid_us=now;
    }
    h->last_us=now;h->phase=current;h->warm_us=warm;h->last_classifier_resets=s->resets;
}

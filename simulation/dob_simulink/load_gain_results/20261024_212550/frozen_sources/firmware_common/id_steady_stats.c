#include "id_steady_stats.h"
#include "mechanical_dob_monitor.h"
#include <math.h>
_Static_assert(sizeof(IdSteadyStats)<=512U,"Do not grow heap or shrink task stacks");
static void begin(IdSteadyStats *s){++s->version;KaSync_Barrier();}
static void end(IdSteadyStats *s){KaSync_Barrier();++s->version;}
static void close_run(IdSteadyOver *s,uint8_t censored){
    if (!s->run_us) return;
    unsigned bin=s->run_us<5000U?0:s->run_us<20000U?1:s->run_us<100000U?2:3;
    ++s->bins[bin];s->censored+=censored;s->run_us=0;
}
static void over(IdSteadyOver *s,uint8_t high,uint32_t dt){
    if (!high){close_run(s,0);return;}
    if (!s->run_us) ++s->episodes;
    s->total_us+=dt;s->run_us+=dt;++s->samples;
    if (s->run_us>s->max_us) s->max_us=s->run_us;
}
static void finish(IdSteadyStats *s,uint32_t state){
    close_run(&s->raw_over,1);close_run(&s->filtered_over,1);s->state=state;
}
void IdSteady_Lifecycle(IdSteadyStats *s,uint8_t running,uint8_t fault){
    if (s->frozen || (!s->running && !running && !fault)) return;
    begin(s);
    if (fault || !running){
        if (s->state!=IDS_DONE) finish(s,IDS_INCOMPLETE);
        s->running=0;s->frozen=1;
    } else s->running=1;
    end(s);
}
void IdSteady_Observe(IdSteadyStats *s,uint32_t now,uint32_t enc,uint32_t dt,
    float reference,float accel,float rpm,float idref,uint8_t iq_sat,
    const MechanicalCurrent *c,uint8_t valid,float filtered,uint32_t dob_status,uint8_t dob_valid){
    if (!s->running || s->frozen) return;
    begin(s);
    if (dob_valid) ++s->dob_status_n[0];
    for (unsigned bit=0;bit<11;bit++) if (dob_status&(1U<<bit)) ++s->dob_status_n[bit+1];
    if (s->state>=IDS_DONE){end(s);return;}
    uint8_t steady=(uint8_t)(isfinite(reference) && isfinite(accel) && isfinite(rpm) &&
        fabsf(reference-ID_STEADY_TARGET_RPM)<.01f && fabsf(accel)<=ID_STEADY_ACCEL_TOL_RPM_S &&
        fabsf(rpm-reference)<=ID_STEADY_SPEED_TOL_RPM && dt && dt<=2000U);
    if (s->state==IDS_WAIT){
        s->stable_us=steady?s->stable_us+dt:0;
        if (s->stable_us<ID_STEADY_CONFIRM_US){end(s);return;}
        s->state=IDS_WINDOW;s->begin_us=enc-dt;s->last_us=s->begin_us;s->have_seq=0;
    }
    uint32_t interval=enc-s->last_us,remaining=ID_STEADY_WINDOW_US-s->window_us;
    if (!interval || interval>=0x80000000U){finish(s,IDS_INCOMPLETE);end(s);return;}
    uint32_t step=interval<remaining?interval:remaining;
    s->window_us+=step;s->last_us=enc;
    if (!steady) s->unstable_us+=step;
    /* Observe finite large Id as data! Neither the 50mA DOB gate nor WARMUP
     * excludes a sample here. Saturation is measured separately, not hidden. */
    uint8_t usable=(uint8_t)(valid && c && isfinite(c->id) && isfinite(c->iq) &&
        isfinite(idref) && isfinite(rpm) &&
        !(c->flags&~MEC_SATURATED) && interval==dt && dt && dt<=2000U &&
        now-enc<=2000U && now-c->source_us<=200U && c->published_us-c->source_us<=100U &&
        (!s->have_seq || ((uint32_t)(c->seq-s->last_seq)>0U && (uint32_t)(c->seq-s->last_seq)<=80U)));
    if (!usable){
        ++s->bad_n;s->bad_us+=step;s->have_seq=0;
        s->filtered_bad_us+=step;
        close_run(&s->raw_over,1);close_run(&s->filtered_over,1);
    } else {
        float values[IDS_SIGNALS]={idref,c->id,c->iq,c->id-idref,rpm};
        for (unsigned i=0;i<IDS_SIGNALS;i++){
            IdSteadyMoment *m=&s->signal[i];float x=values[i];
            if (!s->good_n || x<m->min) m->min=x;
            if (!s->good_n || x>m->max) m->max=x;
            m->integral+=x*(float)step;m->abs_integral+=fabsf(x)*(float)step;
            m->sq_integral+=x*x*(float)step;
        }
        ++s->good_n;s->good_us+=step;s->last_seq=c->seq;s->have_seq=1;
        float a=fabsf(c->id);
        unsigned bin=a<=.02f?0:a<=.05f?1:a<=.1f?2:a<=.2f?3:4;
        ++s->abs_id_bins[bin];
        over(&s->raw_over,(uint8_t)(a>ID_STEADY_THRESHOLD_A),step);
        if (isfinite(filtered) && !(dob_status&(DOB_MONITOR_TIME|DOB_MONITOR_SATURATED|
            DOB_MONITOR_SEQUENCE|DOB_MONITOR_CURRENT))){
            s->filtered_good_us+=step;
            over(&s->filtered_over,(uint8_t)(filtered>ID_STEADY_THRESHOLD_A),step);
        } else {
            s->filtered_bad_us+=step;close_run(&s->filtered_over,1);
        }
        if (c->id>ID_STEADY_THRESHOLD_A) s->positive_over_us+=step;
        if (c->id< -ID_STEADY_THRESHOLD_A) s->negative_over_us+=step;
        if (c->flags&MEC_SATURATED) s->voltage_sat_us+=step;
        if (iq_sat) s->iq_sat_us+=step;
    }
    if (s->window_us==ID_STEADY_WINDOW_US) finish(s,IDS_DONE);
    end(s);
}
uint8_t IdSteady_Read(const IdSteadyStats *s,IdSteadyView *v){
    for(unsigned attempt=0;attempt<2;attempt++){
        uint32_t version=s->version;if (version&1U) continue;KaSync_Barrier();
        IdSteadyView x={s->state,s->good_n,s->good_us,s->bad_us,
            s->raw_over.total_us,s->filtered_over.total_us,s->max_compute_us};
        KaSync_Barrier();if(version==s->version){*v=x;return 1;}
    }
    return 0;
}

#ifndef FOC_FAST_PATH_PROFILE_H
#define FOC_FAST_PATH_PROFILE_H
#include <stdint.h>

/* Diagnostic ledger only. No control input, timeout or admission decision may
 * depend on it. Each interval is a wall delta plus the SAME interval's measured
 * nested-IRQ union; exception entry/exit outside the IRQ hooks remains in CPU.
 * Maxima of different intervals must never be added as a measured total. */
enum { FOC_PROF_ADC, FOC_PROF_RAW_DIAG, FOC_PROF_VALIDATE,
       FOC_PROF_TRANSFORM, FOC_PROF_PI, FOC_PROF_INVERSE,
       FOC_PROF_SVPWM, FOC_PROF_DUTY, FOC_PROF_OTHER, FOC_PROF_N };
typedef struct { uint32_t wall[FOC_PROF_N], irq[FOC_PROF_N]; } FocProfileFrame;
typedef struct {
    uint32_t frames, invalid, normal_total_max, normal_cpu_max;
    uint32_t wall_max[FOC_PROF_N], cpu_max[FOC_PROF_N];
    uint32_t worst_total, worst_irq;
    FocProfileFrame worst; /* One coherent worst-wall frame, not sum of maxima. */
} FocPathProfile;

static inline void FocProfile_Record(FocPathProfile *s,
    const FocProfileFrame *f, uint32_t total, uint32_t irq)
{
    if (irq>total) { ++s->invalid; return; }
    uint32_t sum=0U,irq_sum=0U;
    for (unsigned i=0U;i<FOC_PROF_N;++i) {
        if (f->irq[i]>f->wall[i]) { ++s->invalid; return; }
        sum+=f->wall[i];
        irq_sum+=f->irq[i];
    }
    if (sum!=total || irq_sum!=irq) { ++s->invalid; return; }
    ++s->frames;
    if (total>s->normal_total_max) s->normal_total_max=total;
    if (total-irq>s->normal_cpu_max) s->normal_cpu_max=total-irq;
    for (unsigned i=0U;i<FOC_PROF_N;++i) {
        if (f->wall[i]>s->wall_max[i]) s->wall_max[i]=f->wall[i];
        uint32_t cpu=f->wall[i]-f->irq[i];
        if (cpu>s->cpu_max[i]) s->cpu_max[i]=cpu;
    }
    if (total>s->worst_total) { s->worst_total=total; s->worst_irq=irq; s->worst=*f; }
}

#if defined(FOC_FAST_PATH_PROFILE)
#if !defined(FOC_FAST_CURRENT_REJECT) || !defined(FOC_FAST_REJECT_COMPUTE_ONLY)
#error Stage profiling is a separate power-hard-off fast-current diagnostic
#endif
void FocProfile_Begin(void);
void FocProfile_Mark(unsigned stage);
void FocProfile_End(uint8_t normal);
void FocProfile_IrqRecord(unsigned source,uint32_t begin);
#else
#define FocProfile_Begin() ((void)0)
#define FocProfile_Mark(stage) ((void)0)
#define FocProfile_End(normal) ((void)0)
#endif
#endif

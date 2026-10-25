#ifndef FOC_PWM_PIPELINE_H
#define FOC_PWM_PIPELINE_H
#include <stdint.h>

/* Single ADC owner. Task mode changes/faults invalidate under the caller's
 * existing short critical section. This slot NEVER enables a power gate. */
typedef struct {
    uint16_t ccr[3];
    uint32_t source_seq, entry_seq, mode;
    uint8_t valid, have_entry;
} FocPwmPending;
static inline void FocPwmPending_Invalidate(FocPwmPending *p)
{ p->valid=0U; }
static inline void FocPwmPending_Init(FocPwmPending *p,uint16_t neutral)
{
    *p=(FocPwmPending){.ccr={neutral,neutral,neutral}};
}
/* Call before reading/validating this ADC pair. Retain the accepted command
 * across invalid samples; a held command is not a new command generation. */
static inline int FocPwmPending_Entry(FocPwmPending *p,uint32_t seq,
                                    uint32_t mode,uint8_t healthy)
{
    if (!healthy || mode!=p->mode ||
        (p->have_entry && (uint32_t)(seq-p->entry_seq)!=1U)) p->valid=0U;
    p->entry_seq=seq; p->have_entry=1U; p->mode=mode;
    return p->valid && p->source_seq!=seq;
}
static inline int FocPwmPending_Stage(FocPwmPending *p,uint32_t seq,
    uint32_t mode,uint8_t normal,const uint16_t ccr[3])
{
    if (!normal) return 0; /* No PI work or replacement current here. */
    if (!p->have_entry || seq!=p->entry_seq || mode!=p->mode || !ccr) {
        p->valid=0U; return 0;
    }
    p->ccr[0]=ccr[0]; p->ccr[1]=ccr[1]; p->ccr[2]=ccr[2];
    p->source_seq=seq; p->valid=1U;
    return 1;
}
#endif

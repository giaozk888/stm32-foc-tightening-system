#ifndef FOC_DQ_DECOUPLING_H
#define FOC_DQ_DECOUPLING_H
#include <math.h>
#include <stdint.h>

/* A-only opt-in. Provisional, user-selected L estimates, NOT qualified data. */
#ifndef FOC_DQ_DECOUPLING_ENABLED_DEFAULT
#define FOC_DQ_DECOUPLING_ENABLED_DEFAULT 0
#endif
#ifndef FOC_DQ_LD_H
#define FOC_DQ_LD_H 0.00002003f
#endif
#ifndef FOC_DQ_LQ_H
#define FOC_DQ_LQ_H 0.00001118f
#endif
#ifndef DECOUPLING_SIGN_TEST
#define DECOUPLING_SIGN_TEST 0
#endif
#ifndef DECOUPLING_SIGN_MODE
#define DECOUPLING_SIGN_MODE 0
#endif
#if DECOUPLING_SIGN_MODE < 0 || DECOUPLING_SIGN_MODE > 3 || \
    (DECOUPLING_SIGN_MODE != 0 && !DECOUPLING_SIGN_TEST)
#error Non-nominal dq signs require the explicit A diagnostic sign-test build
#endif

/* Park: d=alpha*cos+beta*sin, q=-alpha*sin+beta*cos.
 * omega is SIGNED electrical rad/s from the existing encoder angle chain.
 * Only inductive cross coupling: no Rs term, flux/back-EMF or new observer.
 * Call only on an accepted normal PI update; invalid/held samples do not call.
 * Common vector saturation and PI tracking are owned by the caller. */
static inline uint8_t FocDqDecoupling_Apply(uint8_t enabled,
    float omega_e,float id,float iq,float *vd_ff,float *vq_ff)
{
    *vd_ff=0.0f; *vq_ff=0.0f;
    if (!enabled) return 1U; /* Exact existing PI path, no input dependency. */
    if (!isfinite(omega_e) || !isfinite(id) || !isfinite(iq) ||
        !isfinite(FOC_DQ_LD_H) || !isfinite(FOC_DQ_LQ_H) ||
        FOC_DQ_LD_H<=0.0f || FOC_DQ_LQ_H<=0.0f) return 0U;
    float d=-omega_e*FOC_DQ_LQ_H*iq;
    float q= omega_e*FOC_DQ_LD_H*id;
#if DECOUPLING_SIGN_TEST && (DECOUPLING_SIGN_MODE & 1)
    d=-d;
#endif
#if DECOUPLING_SIGN_TEST && (DECOUPLING_SIGN_MODE & 2)
    q=-q;
#endif
    if (!isfinite(d) || !isfinite(q)) return 0U;
    *vd_ff=d; *vq_ff=q;
    return 1U;
}

typedef struct {
    uint32_t seq,source_us,enabled,saturated,valid;
    float omega_e,id,iq,vd_pi,vq_pi,vd_ff,vq_ff,vd,vq;
} FocDqDecouplingFrame;
#endif

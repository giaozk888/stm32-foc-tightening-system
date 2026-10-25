#include "foc_fast_trig.h"
#include "foc_hot_path.h"
#include <math.h>
#include <stddef.h>
#if defined(__FAST_MATH__)
#error Finite input rejection requires IEEE math; do not enable fast-math
#endif

FOC_RAM_PATH int FocFast_SinCos(float angle, float *sine, float *cosine)
{
    const float half_pi=1.57079632679489661923f;
    const float two_pi=6.28318530717958647692f;
    if (sine==NULL || cosine==NULL || !isfinite(angle) ||
        angle < -two_pi || angle > two_pi) return 0;
    /* Nearest quadrant makes |r| <= pi/4; both polynomials share r and r^2.
     * Degree 9 sine / degree 8 cosine Taylor truncation is below 2.5e-8
     * on this interval. Floating-point range reduction dominates the error. */
    float scaled=angle*0.63661977236758134308f;
    int quadrant=(int)(scaled+(scaled>=0.0f ? 0.5f : -0.5f));
    float r=angle-(float)quadrant*half_pi;
    float z=r*r;
    float s=r+r*z*(-0.16666666666666666667f+z*(0.00833333333333333333f+
              z*(-0.00019841269841269841f+z*0.00000275573192239859f)));
    float c=1.0f+z*(-0.5f+z*(0.04166666666666666667f+
              z*(-0.00138888888888888889f+z*0.00002480158730158730f)));
    switch ((unsigned)(quadrant+4)&3U) {
    case 0U: *sine=s;  *cosine=c;  break;
    case 1U: *sine=c;  *cosine=-s; break;
    case 2U: *sine=-s; *cosine=-c; break;
    default: *sine=-c; *cosine=s;  break;
    }
    return 1;
}

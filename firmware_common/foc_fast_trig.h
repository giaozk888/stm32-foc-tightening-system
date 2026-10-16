#ifndef FOC_FAST_TRIG_H
#define FOC_FAST_TRIG_H
/* Bounded single-precision sin/cos for the FOC's wrapped electrical angles.
 * Returns 0 for nonfinite/out-of-range input; never hides it with saturation.
 * No lookup allocation, peripheral ownership, libm range reduction or loop.
 * This numerical approximation is opt-in, not an actuator qualification. */
int FocFast_SinCos(float angle, float *sine, float *cosine);
#endif

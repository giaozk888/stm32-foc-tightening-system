/* Included only by the zero estimator. No runtime current classification,
 * power output, timer, IRQ, threshold or fault-latch ownership is changed. */
static void ZeroAdmission_Fail(FocZeroRobust *s,FocZeroCal *c,uint16_t flag)
{
    s->flags=flag;
    FocZero_Abort(c,FOC_ZERO_UNSTABLE);
}
static void ZeroAdmission_Block(FocZeroRobust *s,FocZeroCal *c,uint16_t mu,uint16_t mv)
{
    if (!c->count) { c->min_u=c->max_u=mu; c->min_v=c->max_v=mv; }
    if (mu<c->min_u) c->min_u=mu;
    if (mu>c->max_u) c->max_u=mu;
    if (mv<c->min_v) c->min_v=mv;
    if (mv>c->max_v) c->max_v=mv;
    if ((uint32_t)(c->max_u-c->min_u)>FOC_ZERO_MAX_SPAN ||
        (uint32_t)(c->max_v-c->min_v)>FOC_ZERO_MAX_SPAN) {
        ZeroAdmission_Fail(s,c,FOC_ROBUST_CENTER_SPAN); return;
    }
    for (unsigned i=0U;i<FOC_ROBUST_BLOCK;++i) {
        uint16_t u=s->u[i],v=s->v[i];
        if (distance(u,mu)>FOC_ROBUST_OUTLIER_DELTA ||
            distance(v,mv)>FOC_ROBUST_OUTLIER_DELTA) {
            ++s->reject_count; ++s->segment_outliers;
            if (++s->consecutive_reject>s->max_consecutive_reject)
                s->max_consecutive_reject=s->consecutive_reject;
            if (s->reject_count>ZERO_CAL_MAX_REJECT_COUNT) {
                ZeroAdmission_Fail(s,c,FOC_ZERO_ADMIT_REJECT_LIMIT); return;
            }
            if (s->consecutive_reject>ZERO_CAL_MAX_CONSEC_REJECT) {
                ZeroAdmission_Fail(s,c,FOC_ZERO_ADMIT_CONSEC_LIMIT); return;
            }
            continue; /* No rejected value reaches any offset/segment sum. */
        }
        s->consecutive_reject=0U;
        c->sum_u+=u; c->sum_v+=v;
        if (c->count<ZERO_CAL_VALID_TARGET/2U) { c->first_u+=u; c->first_v+=v; }
        ++c->count;
        s->segment_u+=u; s->segment_v+=v;
        if (c->count%FOC_ROBUST_SEGMENT==0U) {
            if (!s->segments) {
                s->segment_min_u=s->segment_max_u=s->segment_u;
                s->segment_min_v=s->segment_max_v=s->segment_v;
            }
            if (s->segment_u<s->segment_min_u) s->segment_min_u=s->segment_u;
            if (s->segment_u>s->segment_max_u) s->segment_max_u=s->segment_u;
            if (s->segment_v<s->segment_min_v) s->segment_min_v=s->segment_v;
            if (s->segment_v>s->segment_max_v) s->segment_max_v=s->segment_v;
            /* Segment sums now contain 500 accepted RAW pairs, instead of
             * 100 block medians. The allowed mean drift stays FIVE counts. */
            uint32_t limit=FOC_ZERO_MAX_HALF_DRIFT*FOC_ROBUST_SEGMENT;
            if (s->segment_max_u-s->segment_min_u>limit ||
                s->segment_max_v-s->segment_min_v>limit) {
                ++c->drift_restarts;
                ZeroAdmission_Fail(s,c,FOC_ROBUST_SEGMENT_DRIFT); return;
            }
            ++s->segments;
            s->segment_u=s->segment_v=s->segment_outliers=0U;
        }
        if (c->count==ZERO_CAL_VALID_TARGET) {
            c->zero_u=(uint16_t)((c->sum_u+ZERO_CAL_VALID_TARGET/2U)/ZERO_CAL_VALID_TARGET);
            c->zero_v=(uint16_t)((c->sum_v+ZERO_CAL_VALID_TARGET/2U)/ZERO_CAL_VALID_TARGET);
            if (distance(c->zero_u,c->nominal)>FOC_ZERO_MAX_NOMINAL_DELTA ||
                distance(c->zero_v,c->nominal)>FOC_ZERO_MAX_NOMINAL_DELTA) {
                s->flags=FOC_ROBUST_BAD_NOMINAL;
                FocZero_Abort(c,FOC_ZERO_OUT_OF_RANGE); return;
            }
            c->state=FOC_ZERO_READY;
            return; /* Up to four already-buffered tail pairs are unused. */
        }
    }
}

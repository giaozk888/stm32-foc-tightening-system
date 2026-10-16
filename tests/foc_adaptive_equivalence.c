#include <assert.h>
#include <stdio.h>
#include "foc_adaptive_reference.h"

static uint32_t rng=0x15102026U;
static uint32_t random32(void)
{ rng^=rng<<13U; rng^=rng>>17U; rng^=rng<<5U; return rng; }
static void same_noise(const FocAdaptiveNoise *a,const FocAdaptiveNoise *b)
{
    assert(a->noise_q8==b->noise_q8);
    assert(a->quiet==b->quiet);
    assert(a->learned==b->learned);
}
static void window(uint16_t p,uint16_t a,uint16_t b,uint16_t c,unsigned n)
{
    static const uint16_t noises[]={0U,256U,853U,854U,1280U,1706U,1707U,2048U,65535U};
    static const uint8_t quiets[]={0U,15U,16U,17U};
    FocAdaptiveNoise x={.noise_q8=noises[n%9U],.quiet=quiets[n%4U],
        .learned=n%2U?UINT32_MAX:UINT32_MAX-1U},y=x;
    FocAdaptiveWindow w=FocAdaptive_Analyze(&x,p,a,b,c);
    assert(w.isolated==RefAdaptive_Isolated(&y,p,a,b,c));
    assert(!w.isolated || !w.quiet_residual_plus1);
    for (unsigned repaired=0U;repaired<4U;++repaired) {
        FocAdaptiveNoise u=x,v=y;
        FocAdaptive_LearnWindow(&u,w,(uint8_t)repaired);
        RefAdaptive_Learn(&v,p,a,b,c,(uint8_t)repaired);
        same_noise(&u,&v);
        u=x;
        FocAdaptive_Learn(&u,p,a,b,c,(uint8_t)repaired);
        same_noise(&u,&v);
    }
}
int main(void)
{
    unsigned n=0U;
    /* Exhaust the quiet +/-10 boundary and the residual +/-30 boundary. */
    for (int p=-11;p<=11;++p) for (int a=-11;a<=11;++a)
    for (int b=-11;b<=11;++b) for (int c=-11;c<=11;++c)
        window((uint16_t)(1560+p),(uint16_t)(1560+a),
            (uint16_t)(1560+b),(uint16_t)(1560+c),n++);
    /* Candidate cutoffs, prediction clipping, ADC invalids and unsigned edges. */
    static const uint16_t edges[]={0U,1U,9U,10U,11U,19U,20U,21U,29U,30U,31U,
        39U,40U,41U,1560U,4094U,4095U,4096U,5000U,65535U};
    for (unsigned p=0U;p<20U;++p) for (unsigned a=0U;a<20U;++a)
    for (unsigned b=0U;b<20U;++b) for (unsigned c=0U;c<20U;++c)
        window(edges[p],edges[a],edges[b],edges[c],n++);
    /* All possible estimator values, including threshold rounding endpoints. */
    for (uint32_t noise=0U;noise<=65535U;++noise) {
        FocAdaptiveNoise s={.noise_q8=(uint16_t)noise};
        assert(FocAdaptive_Jump(&s)==RefAdaptive_Jump(&s));
        for (uint16_t d=19U;d<=41U;++d)
            assert(FocAdaptive_Isolated(&s,1560U,1560U,(uint16_t)(1560U+d),1560U)==
                RefAdaptive_Isolated(&s,1560U,1560U,(uint16_t)(1560U+d),1560U));
    }
    FocCurrentMedian x,y;
    FocCurrentMedian_Begin(&x); FocCurrentMedian_Begin(&y);
    for (unsigned i=0U;i<2000000U;++i) {
        uint16_t u,v; unsigned phase=i%2000U;
        if (phase<1200U) { /* Exercise long learning runs, then small spikes. */
            u=(uint16_t)(1560U+random32()%7U); v=(uint16_t)(1560U+random32()%7U);
            if (i%101U==50U) u=(uint16_t)(u+25U);
            if (i%157U==78U) v=(uint16_t)(v+60U);
        } else if (phase<1400U) {
            u=(uint16_t)(1200U+phase-1200U); v=(uint16_t)(1800U-(phase-1200U));
        } else if (phase<1600U) {
            u=(uint16_t)(random32()%4096U); v=(uint16_t)(random32()%4096U);
        } else if (phase<1800U) {
            u=(uint16_t)random32(); v=(uint16_t)random32();
        } else { u=1560U; v=1560U; }
        uint16_t xu=123U,xv=456U,yu=xu,yv=xv;
        int ready=FocCurrentMedian_Push(&x,u,v,&xu,&xv);
        assert(ready==RefAdaptive_Push(&y,u,v,&yu,&yv));
        assert(xu==yu && xv==yv && x.last_spike_mask==y.last_spike_mask);
        assert(x.index==y.index && x.count==y.count);
        for (unsigned ch=0U;ch<2U;++ch) same_noise(&x.noise[ch],&y.noise[ch]);
        for (unsigned k=0U;k<4U;++k) assert(x.u[k]==y.u[k] && x.v[k]==y.v[k]);
        /* Saturating learned counters are checked in the paired path too. */
        if (i%2000U==1800U) x.noise[0].learned=y.noise[0].learned=UINT32_MAX-1U;
    }
    printf("PASS %u boundary windows; all 65536 noise values; 2000000 physical pairs/state\n",n);
    return 0;
}

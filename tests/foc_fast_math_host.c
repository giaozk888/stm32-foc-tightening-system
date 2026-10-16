#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "foc_fast_trig.h"
#include "foc_irq_load.h"

int main(void)
{
    const float tau=6.28318530717958647692f;
    double max_error=0.0, max_norm=0.0, max_roundtrip=0.0;
    for (unsigned i=0;i<=1000000U;++i) {
        float a=(float)(-tau+2.0*(double)tau*i/1000000.0),s,c;
        assert(FocFast_SinCos(a,&s,&c));
        double error=fmax(fabs(s-sin((double)a)),fabs(c-cos((double)a)));
        double norm=fabs((double)s*s+(double)c*c-1.0);
        if (error>max_error) max_error=error;
        if (norm>max_norm) max_norm=norm;
        assert(error<0.000001 && norm<0.000001);
        /* Same-angle Park/inverse Park round trip, per-unit vector. */
        float alpha=0.31f,beta=-0.72f,d=alpha*c+beta*s,q=-alpha*s+beta*c;
        double roundtrip=fmax(fabs((d*c-q*s)-alpha),fabs((d*s+q*c)-beta));
        if (roundtrip>max_roundtrip) max_roundtrip=roundtrip;
        assert(roundtrip<0.000001);
    }
    float s=123.0f,c=456.0f;
    const float invalid[]={NAN,INFINITY,-INFINITY,7.0f,-7.0f,1.0e30f,
                           nextafterf(tau,INFINITY),nextafterf(-tau,-INFINITY)};
    for (unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);++i) {
        assert(!FocFast_SinCos(invalid[i],&s,&c)); assert(s==123.0f && c==456.0f);
    }
    assert(!FocFast_SinCos(0.0f,NULL,&c)); assert(!FocFast_SinCos(0.0f,&s,NULL));
    assert(FocFast_SinCos(-0.0f,&s,&c)); assert(s==0.0f && c==1.0f);
    FocIrqLoad load={0};
    FocIrqLoad_Begin(&load,100U); FocIrqLoad_Begin(&load,120U);
    FocIrqLoad_End(&load,150U); assert(FocIrqLoad_Total(&load,180U)==80U);
    FocIrqLoad_End(&load,200U); assert(FocIrqLoad_Total(&load,220U)==100U);
    /* Nested intervals are a union, not 100+30, and wrap remains bounded. */
    FocIrqLoad_Begin(&load,UINT32_MAX-9U); FocIrqLoad_End(&load,10U);
    assert(FocIrqLoad_Total(&load,20U)==120U);
    FocIrqLoad_End(&load,30U); assert(load.total==120U && load.depth==0U);
    printf("PASS 1000001 angles: max component error %.9g norm %.9g Park roundtrip %.9g; nested IRQ union/wrap\n",
           max_error,max_norm,max_roundtrip);
    return 0;
}

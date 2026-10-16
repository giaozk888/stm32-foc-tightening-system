#include <stdio.h>
#include <stdint.h>
#include "foc_spike_cubic5_candidate.h"
int main(void)
{
#if defined(OFFLINE_QUADRATIC4)
    enum { WINDOW=4, DELAY=1 };
#else
    enum { WINDOW=5, DELAY=2 };
#endif
    uint16_t history[2][5]={{0}},x[2][5];
    unsigned u,v,n=0,index=0;
    while (scanf("%u %u",&u,&v)==2) {
        if (u>65535U || v>65535U) return 2;
        history[0][index]=(uint16_t)u; history[1][index]=(uint16_t)v;
        index=(index+1U)%WINDOW; ++n;
        if (n<WINDOW) continue;
        for (unsigned ch=0;ch<2U;++ch) {
            x[ch][4]=0U;
            for (unsigned k=0;k<WINDOW;++k) x[ch][k]=history[ch][(index+k)%WINDOW];
        }
        printf("%u %u %u %u\n",n-1U-DELAY,Cubic5_Select(x[0]),Cubic5_Select(x[1]),
            Cubic5_Isolated(x[0])|(Cubic5_Isolated(x[1])<<1U));
    }
    return 0;
}

#include "foc_pwm_boundary.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    FocPwmBoundary s={0};
    FocPwmBoundaryFrame f={.seq=1,.remaining=4200,.wall=4000,.irq=100,
        .geometry=1,.stable=1,.dwt=1,.sources={{40,60,0,0},{1,1,0,0},0}};
    FocPwmBoundary_Record(&s,&f);
    assert(s.frames==1 && s.worst.valid && s.worst.margin==200 && !s.first_late.valid);
    f.seq=2; f.wall=4200;
    FocPwmBoundary_Record(&s,&f);
    assert(s.first_late.seq==2 && s.first_late.margin==0 && s.late==1);
    f.seq=3; f.wall=4500;
    FocPwmBoundary_Record(&s,&f);
    assert(s.worst.seq==3 && s.worst.margin==-300 && s.first_late.seq==2);
    FocPwmBoundaryFrame good=f;
    for (unsigned bad=0;bad<8;++bad) {
        f=good;
        switch (bad) {
        case 0: f.geometry=0; break;
        case 1: f.stable=0; break;
        case 2: f.dwt=0; break;
        case 3: f.sources.error=1; break;
        case 4: f.irq=f.wall+1; break;
        case 5: f.sources.cycles[0]++; break;
        case 6: f.remaining=UINT32_MAX; break;
        case 7: f.sources.cycles[0]=UINT32_MAX; f.sources.cycles[1]=101; break;
        }
        FocPwmBoundary_Record(&s,&f);
        assert(!f.valid && s.worst.seq==3 && s.first_late.seq==2);
    }
    assert(s.invalid==8);
    f=good; f.wall=UINT32_MAX;
    FocPwmBoundary_Record(&s,&f);
    assert(f.margin==INT32_MIN);
    puts("PASS boundary arithmetic: frozen first, same-frame worst, overflow, invalid evidence");
}

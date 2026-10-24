#include <assert.h>
#include <math.h>
#include "psi_ke_identification.h"

static PsiIdentFrame sample(unsigned n,float rpm,float psi)
{
    PsiIdentFrame f={.seq=n+1,.us=1000000U+n*50000U,.we=rpm*10.f*0.1047197551196598f,
        .id=.002f,.iq=.16f,.vd=.01f};
    f.vq=.78f*f.iq+f.we*20.03e-6f*f.id+f.we*psi;
    assert(PsiIdent_Calculate(&f,.78f,20.03e-6f,10));return f;
}
static void observe(PsiIdentification *s,PsiIdentFrame f,float ref,float accel,uint8_t healthy)
{ PsiIdent_Observe(s,f,ref,accel,healthy,f.us); }
int main(void)
{
    _Static_assert(sizeof(PsiIdentification)==168,"Pinned diagnostic ABI");
    assert(PsiIdent_Allowed(100,250,300));assert(PsiIdent_Allowed(200,250,300));
    assert(!PsiIdent_Allowed(300,250,300));assert(!PsiIdent_Allowed(400,250,300));
    assert(!PsiIdent_Allowed(300,400,300));assert(!PsiIdent_Allowed(120,250,300));
    for (int sign=-1;sign<=1;sign+=2) {
        PsiIdentFrame f=sample(0,sign*200,.0004f);
        assert(fabsf(f.psi-.0004f)<1e-9f);
        assert(f.bemf*f.we>0 && fabsf(f.rpm-sign*200)<.001f);
    }
    PsiIdentFrame low={.we=0,.iq=.1f,.vq=.1f};
    assert(!PsiIdent_Calculate(&low,.78f,20e-6f,10));assert(low.quality==PSI_Q_LOW_SPEED);
    assert(!low.psi && !low.bemf);
    low.we=NAN;assert(!PsiIdent_Calculate(&low,.78f,20e-6f,10));
    assert(low.quality==PSI_Q_BAD_INPUT);
    low.we=200.f*10.f*0.1047197551196598f;
    assert(PsiIdent_Calculate(&low,.78f,20e-6f,10));assert(low.quality==PSI_Q_VALID);
    for (unsigned bad=0;bad<4;bad++) {
        PsiIdentification s={.active=1,.rpm=200};
        for (unsigned n=0;n<100 && !s.finished;n++) {
            PsiIdentFrame f=sample(n,200,.0004f+(n%2 ? 1e-5f : -1e-5f));
            if (n>=15 && n<15+bad) f.saturated=1;
            observe(&s,f,200,0,1);
        }
        assert(s.finished && s.window_complete);
        assert(s.reject==bad && s.seen==41);
        assert(s.passed==(bad<=2));
        assert(fabsf(s.mean[5]-.0004f)<1e-6f && s.psi_m2>0);
        unsigned valid=s.valid;
        observe(&s,sample(101,200,.1f),200,0,1);assert(s.valid==valid);
        PsiIdent_Finish(&s,0);assert(!s.passed && s.stage==PSI_ABORT);
    }
    PsiIdentification accelerating={.active=1,.rpm=200};
    for(unsigned n=0;n<60;n++) observe(&accelerating,sample(n,200,.0004f),200,200,1);
    assert(!accelerating.window_start && !accelerating.valid);
    PsiIdent_Finish(&accelerating,1);assert(!accelerating.passed);
    PsiIdentification short_window={.active=1,.rpm=200};
    for(unsigned n=0;n<49;n++) observe(&short_window,sample(n,200,.0004f),200,0,1);
    PsiIdent_Finish(&short_window,1);assert(!short_window.passed);
    PsiIdentification unhealthy={.active=1,.rpm=200};
    for(unsigned n=0;n<60;n++) observe(&unhealthy,sample(n,200,.0004f),200,0,0);
    assert(!unhealthy.window_start && !unhealthy.valid);
    return 0;
}

#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include "tightening_rundown_guard.h"
#define FOC_RUNDOWN_DIAGNOSTIC 1
#include "foc_startup_trace.h"
int main(void)
{
    TightenRundownGuard g={0};
    for (unsigned t=0;t<=200;t+=10)
        assert(!TightenRundown_Update(&g,t,20,20,20,t*.12f,.2f,1));
    assert(TightenRundown_CanContact(&g));
    assert(!TightenRundown_CanOk(&g,0));
    assert(TightenRundown_CanOk(&g,1));
    TightenRundown_Begin(&g);
    for (unsigned t=0;t<=1500;t+=10) {
        int fail=TightenRundown_Update(&g,t,20,2.77f,2.77f,t*.01662f,.35f,1);
        assert(fail==(t==1500)); assert(!TightenRundown_CanContact(&g));
    }
    TightenRundown_Begin(&g);
    for (unsigned t=0;t<=200;t+=10)
        assert(!TightenRundown_Update(&g,t,-20,-20,-20,-(float)t*.12f,-.2f,1));
    assert(TightenRundown_CanContact(&g));
    for (unsigned scenario=0;scenario<6;++scenario) {
        TightenRundown_Begin(&g);
        for (unsigned t=0;t<=1400;t+=10) {
            float speed=scenario==0 ? (t==50 ? 100.0f:0.0f) : 20.0f;
            float ctrl=scenario==1 ? -speed:speed;
            float detect=scenario==2 ? 0.0f:speed;
            float pos=scenario==3 ? 0.0f:t*.12f;
            if (scenario==4) ctrl=NAN;
            assert(!TightenRundown_Update(&g,t,20,ctrl,detect,pos,.2f,scenario!=5));
            assert(!TightenRundown_CanContact(&g));
        }
    }
    TightenRundown_Begin(&g);
    TightenRundown_Update(&g,10,20,20,20,0,.35f,1);
    TightenRundown_Update(&g,110,20,20,20,12,.35f,1); /* missing observations */
    assert(!TightenRundown_CanContact(&g));
    /* Binary schema used by the file-only Python decoder. */
    _Static_assert(sizeof(FocStartupFrame)==124,"frame schema");
    _Static_assert(offsetof(FocStartupFrame,command)==60,"float schema");
    _Static_assert(offsetof(FocStartupFrame,encoder_delta)==84,"delta schema");
    _Static_assert(offsetof(FocStartupFrame,pending_ccr)==100,"PWM schema");
    _Static_assert(offsetof(FocStartupFrame,validator_state)==112,"state schema");
    _Static_assert(sizeof(FocStartupTrace)==4112,"trace schema");
    FocStartupTrace trace={0}; FocStartup_Begin(&trace,1000);
    for (unsigned t=0;t<=3000000;t+=1000)
        FocStartup_Push(&trace,(FocStartupFrame){.us=1000+t,.adc_seq=t});
    assert(trace.total==32 && trace.rows[0].us==0 && trace.rows[31].us==1550000);
    FocStartup_Stop(&trace); /* normal output-off before process annotation */
    FocStartup_RundownEnd(&trace,(FocStartupFrame){.us=1601000,.state=11});
    assert(trace.frozen && trace.terminal_valid && trace.fault.us==1600000);
    FocStartup_RundownEnd(&trace,(FocStartupFrame){.us=9999999});
    assert(trace.fault.us==1600000);
    FocStartupTrace fault={0}; FocStartup_Begin(&fault,1000);
    FocStartup_Push(&fault,(FocStartupFrame){.us=1000});
    FocStartup_Fault(&fault,1024,9000,(FocStartupFrame){.us=9000,.encoder_delta=17});
    FocStartup_RundownEnd(&fault,(FocStartupFrame){.us=10000});
    assert(fault.fault_valid && fault.fault.encoder_delta==17 && !fault.terminal_valid);
    puts("PASS rundown guard and extended trace");
}

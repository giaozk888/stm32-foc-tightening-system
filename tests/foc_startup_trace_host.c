#include <assert.h>
#include <string.h>
#include "foc_startup_trace.h"
int main(void)
{
    FocStartupTrace trace={0}; FocStartupFrame row={0},out={0}; char text[256];
    FocStartup_Begin(&trace,UINT32_MAX-5U);
    for (unsigned n=0;n<45U;++n) {
        row.us=UINT32_MAX-5U+n; row.adc_seq=n;
        row.ref=20.0f; row.instant=87.0f; row.speed=60.7f;
        row.iq_ref=-0.1f; row.iq=0.2f;
        FocStartup_Push(&trace,row);
    }
    assert(!FocStartup_Get(&trace,0,&out));
    FocStartup_Fault(&trace,1024U,40U,row);
    assert(trace.first_flags==1024U && trace.first_off_us==40U);
    FocStartup_Fault(&trace,32U,55U,(FocStartupFrame){0});
    FocStartup_Push(&trace,(FocStartupFrame){0}); FocStartup_Begin(&trace,90U);
    assert(trace.total==45U && trace.first_flags==1024U && trace.fault.iq_ref==-0.1f);
    assert(FocStartup_Count(&trace)==32U);
    for (unsigned i=0;i<32U;++i) {
        assert(FocStartup_Get(&trace,i,&out));
        assert(out.adc_seq==13U+i && out.us==13U+i);
    }
    assert(!FocStartup_Get(&trace,32U,&out));
    FocStartup_Format(&trace.fault,text,sizeof text);
    assert(strstr(text,"RPM10=200,870,607") && strstr(text,"MA=-100,0,200"));
    FocStartup_Format(&trace.fault,text,32U);
    assert(strstr(text,"ERR 109 STARTUP_FORMAT_SIZE"));
    assert(FocStartup_Scaled(NAN,1000.0f)==INT32_MIN);
    assert(FocStartup_Scaled(INFINITY,1000.0f)==INT32_MIN);
    assert(FocStartup_Scaled(1.0e30f,1000.0f)==INT32_MIN);
    FocStartupTrace stopped={0}; FocStartup_Begin(&stopped,0U);
    FocStartup_Stop(&stopped); FocStartup_Push(&stopped,row);
    assert(stopped.frozen && !stopped.total && !stopped.fault_valid);
    puts("PASS startup trace: wrap, chronology, freeze, first cause, stop, invalid floats");
    return 0;
}

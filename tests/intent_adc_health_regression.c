/* Replay retained A728 duties/config with the REAL unchanged window planner.
 * No hardware, current/voltage/settling threshold edits or PWM writes. */
#include "foc_adc_window.h"
#include <assert.h>
#include <stdio.h>

static int safe_tick(const FocWindowConfig *c,const uint16_t p[3],int t)
{
    int end=t+c->latency_ticks+c->aperture_ticks;
    int period=2*c->arr,guard=c->dead_ticks+c->settle_ticks;
    if (t<=0 || end>=c->arr) return 0;
    for (unsigned i=0;i<3;++i) {
        if (i<2 && (t<p[i]+guard || t<p[i]+c->dead_ticks+c->min_low_on_ticks ||
                     end>period-p[i]-guard)) return 0;
        for (int cycle=-1;cycle<=1;++cycle) {
            int edge=cycle*period+p[i],reverse=cycle*period+period-p[i];
            if (!(end<=edge-guard || t>=edge+guard) ||
                !(end<=reverse-guard || t>=reverse+guard)) return 0;
        }
    }
    return 1;
}
int main(void)
{
    FocWindowConfig cfg={4249,85,85,14,50,FOC_SENSE_LOW_SIDE_UV,
                         1700,FOC_SAMPLE_LATE_BEFORE_PEAK};
    FocWindowPlan plan;
    const uint16_t bad[3]={1891,2401,1848},boundary[3]={1891,2399,1848};
    assert(FocAdcWindow_Duty(&cfg,0.4450235664844513f,
           0.5650515556335449f,0.43494847416877747f,&plan)==FOC_WINDOW_TOO_SHORT);
    assert(FocAdcWindow_Plan(&cfg,bad,&plan)==FOC_WINDOW_TOO_SHORT);
    assert(!plan.trigger); /* Rejected plan must never leave stale valid PWM. */
    for (int t=1;t<cfg.arr;++t) assert(!safe_tick(&cfg,bad,t));
    assert(2401+85+1700==4186 && 4249-1-14-50==4184);
    assert(FocAdcWindow_Plan(&cfg,boundary,&plan)==FOC_WINDOW_OK);
    assert(plan.trigger==4184 && plan.earliest==4184 && plan.slack_ticks==0);
    assert(safe_tick(&cfg,boundary,plan.trigger));
    assert(FocAdcWindow_Duty(&cfg,.5f,.5f,.5f,&plan)==FOC_WINDOW_OK);
    assert(plan.trigger==4184 && plan.slack_ticks==274);
    puts("PASS A728 retained command: window deficit=2 ticks; protection correctly rejects; no thresholds changed");
    return 0;
}

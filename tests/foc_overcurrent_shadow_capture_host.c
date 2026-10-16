/* Execute the exact capture/protocol include files without hardware or UART. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "foc_overcurrent_shadow.h"
#include "foc_current_median.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
#define FOC_CURRENT_TRIP_A 4.0f
static FocOcShadow foc_oc_shadow;
#if defined(FOC_FILTERED_OBSERVE_ONLY)
static FocOcShadow foc_filtered_oc_shadow;
#endif
static FocCurrentMedian current_spike_filter;
static uint32_t foc_trend_pairs, foc_trend_changed, foc_trend_u_changed, foc_trend_v_changed;
static volatile struct {
    FocOcShadow shadow;
    int32_t raw_mA[3], filtered_mA[3];
    uint16_t trend_u[4], trend_v[4];
    uint32_t trend_pairs, trend_changed, trend_u_changed, trend_v_changed;
    uint8_t trip_source, raw_mask, filtered_mask, spike_mask, valid;
} foc_current_trip_snapshot;
static void capture(float physical_u_A,float physical_v_A,float filtered_u_A,float filtered_v_A)
{
    float physical_w_A=-(physical_u_A+physical_v_A);
    float filtered_w_A=-(filtered_u_A+filtered_v_A);
    int physical_trip=FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,4.0f)!=0;
#include "foc_overcurrent_shadow_capture.inc"
    foc_current_trip_snapshot.valid=1;
}
static uint32_t primask;
static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask=1; }
static void __set_PRIMASK(uint32_t value) { primask=value; }
static void __DMB(void) { }
static char response[384];
static int Protocol_SendFormatted(char *out,size_t capacity,const char *format,...)
{
    va_list args; va_start(args,format); int n=vsnprintf(out,capacity,format,args); va_end(args);
    CHECK(n>0 && n<=224 && (size_t)n<capacity && (size_t)n<sizeof(response));
    memcpy(response,out,(size_t)n+1U); return 1;
}
static void query(const char *cmd)
{
    uint32_t request_id=UINT32_MAX;
    if (0) { }
#include "foc_overcurrent_shadow_protocol.inc"
    else CHECK(0);
}
int main(void)
{
    query("OC RAW POLICY");
#if defined(FOC_FILTERED_OBSERVE_ONLY)
    CHECK(strstr(response,"RAW=OBSERVE_POWER_OFF FILTERED=OBSERVE_POWER_OFF")!=NULL);
    CHECK(strstr(response,"INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0")!=NULL);
    FocOcShadow_Begin(&foc_filtered_oc_shadow);
    FocOcShadow_Push(&foc_filtered_oc_shadow,1,4,1);
    query("OC FILTERED STATUS");
    CHECK(strstr(response,"DELAY_PAIRS=1 N=1 SEQ=1 HIT=0,0,1 LAST_MASK=4")!=NULL);
    foc_filtered_oc_shadow.samples=foc_filtered_oc_shadow.last_seq=UINT32_MAX;
    for (unsigned i=0;i<3;++i) foc_filtered_oc_shadow.phase[i].hits=UINT32_MAX;
    query("OC FILTERED STATUS"); /* Worst-case decimal fields fit the bounded TX. */
#elif defined(FOC_RAW_OBSERVE_ONLY)
    CHECK(strstr(response,"RAW=OBSERVE_POWER_OFF FILTERED=STOP")!=NULL);
    CHECK(strstr(response,"INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0")!=NULL);
#else
    CHECK(strstr(response,"RAW=STOP FILTERED=STOP LIMIT_MA=4000")!=NULL);
#endif
    FocCurrentMedian_Begin(&current_spike_filter);
    uint16_t u,v;
    FocCurrentMedian_Push(&current_spike_filter,1560,1560,&u,&v);
    FocCurrentMedian_Push(&current_spike_filter,1561,1561,&u,&v);
    FocCurrentMedian_Push(&current_spike_filter,2400,1562,&u,&v);
    FocCurrentMedian_Push(&current_spike_filter,1562,1563,&u,&v);
    FocOcShadow_Push(&foc_oc_shadow,4,1,1);
    foc_trend_pairs=100; foc_trend_changed=10; foc_trend_u_changed=8; foc_trend_v_changed=3;
    capture(4.2f,0,0.01f,0.02f);
    CHECK(foc_current_trip_snapshot.trip_source==1 && foc_current_trip_snapshot.raw_mask==5);
    CHECK(!foc_current_trip_snapshot.filtered_mask && foc_current_trip_snapshot.raw_mA[0]>4100);
    CHECK(foc_current_trip_snapshot.filtered_mA[0]==10 && foc_current_trip_snapshot.spike_mask==1);
    CHECK(foc_current_trip_snapshot.trend_u[0]==1560 && foc_current_trip_snapshot.trend_u[2]==2400);
    CHECK(foc_current_trip_snapshot.trend_u[3]==1562 && foc_current_trip_snapshot.trend_changed==10);
    query("FAULT SHADOW"); CHECK(strstr(response,"SRC=1 RM=5 FM=0") && strstr(response,"PEND=1 CONF=0"));
    query("FAULT TREND"); CHECK(strstr(response,"U=1560,1561,2400,1562") && strstr(response,"CHANGED=10 CU=8 CV=3"));
    capture(0.01f,0.02f,2.3f,2.3f);
    CHECK(foc_current_trip_snapshot.trip_source==2 && foc_current_trip_snapshot.filtered_mask==4);
    capture(4.2f,0,2.3f,2.3f); CHECK(foc_current_trip_snapshot.trip_source==3);
    /* Worst-case formatted counters/history; no silent truncation. */
    foc_current_trip_snapshot.shadow.samples=UINT32_MAX;
    foc_current_trip_snapshot.shadow.gaps=foc_current_trip_snapshot.shadow.invalid=UINT32_MAX;
    for (unsigned i=0;i<3;++i) {
        foc_current_trip_snapshot.raw_mA[i]=INT32_MIN;
        foc_current_trip_snapshot.filtered_mA[i]=INT32_MIN;
        foc_oc_shadow.phase[i].hits=foc_oc_shadow.phase[i].singles=UINT32_MAX;
    }
    query("FAULT SHADOW"); query("FAULT TREND");
    foc_oc_shadow.samples=foc_oc_shadow.gaps=foc_oc_shadow.invalid=foc_oc_shadow.last_seq=UINT32_MAX;
    foc_trend_pairs=foc_trend_changed=foc_trend_u_changed=foc_trend_v_changed=UINT32_MAX;
    primask=1; query("OC SHADOW STATUS"); CHECK(primask==1);
    CHECK(strstr(response,"MODE=OBSERVE LIMIT_MA=4000"));
    query("OC FILTER STATUS"); CHECK(primask==1 && strstr(response,"CHANGED=4294967295"));
    foc_current_trip_snapshot.valid=0; query("FAULT SHADOW"); CHECK(strstr(response,"VALID=0"));
    query("FAULT TREND"); CHECK(strstr(response,"VALID=0"));
    puts("frozen raw/filtered source, chronological history, counters, bounded read-only replies PASS");
    return 0;
}

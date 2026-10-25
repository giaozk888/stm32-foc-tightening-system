/* Offline MSVC adapter; compile-time assertions remain active. */
#if defined(_MSC_VER)
#define DOB_WA_JOIN_(a,b) a##b
#define DOB_WA_JOIN(a,b) DOB_WA_JOIN_(a,b)
#define _Static_assert(c,msg) typedef char DOB_WA_JOIN(DobWindowAssert,__LINE__)[(c)?1:-1]
#endif
#ifndef DOB_TREND_SHADOW_H
#define DOB_TREND_SHADOW_H
#include <stdint.h>
#include <stddef.h>
/* A-only task observer. Fixed baseline100/80ms. No actuator/protection API. */
#define DTS_WINDOW DOB_WINDOW_POINTS
#define DTS_POINTS 144U
#define DTS_PRE 32U
#define DTS_POST (DTS_POINTS-DTS_PRE)
#define DTS_RECORD_US 8000U
enum { DTS_UNKNOWN,DTS_LIGHT,DTS_MEDIUM,DTS_UNUSED,DTS_HIGH };
enum { DTS_TUNKNOWN,DTS_STEADY,DTS_RISING,DTS_FALLING };
enum { DTS_ARMED=1U,DTS_TRIGGERED=2U,DTS_DONE=4U,DTS_STOPPED=8U,DTS_BUFFER_ERROR=16U,
       DTS_PREACTIVE_RISE=32U,DTS_PREACTIVE_FALL=64U };
typedef struct {
    float value[DTS_WINDOW];uint32_t stamp[DTS_WINDOW];uint8_t good[DTS_WINDOW];
    uint32_t head,count,state,proposal,accepted,rejected,resets,level_changes;
    uint32_t have_call,trend_state,trend_proposal,trend_changes;
    int32_t direction;
    uint32_t previous_good,have_source,last_call,last_good,last_source;
    float mean,trend,coverage,trend_filtered;
    uint32_t level_dwell_us,trend_dwell_us,valid,trend_valid,updated,reason;
} DobTrendClassifier;
typedef struct {
    uint32_t encoder_us,observed_us,source_us;
    float disturbance_a;
    int32_t direction;
    uint8_t running,fault,valid,filter_updated;
} DobTrendInput;
typedef struct {
    uint32_t encoder_us;
    float disturbance_a,trend_a_s,rpm,iq_a;
    uint16_t flags;uint8_t level,trend;
} DobTrendPoint;
typedef struct {DobTrendClassifier classifier;DobTrendPoint points[DTS_POINTS];} DobTrendArena;
typedef struct {
    uint32_t abi,flags,observations,start_us,last_record_us,arm_qual_us,arm_us;
    float baseline_a,peak_a;
    uint32_t proxy_rise_us,proxy_fall_us,trigger_head,head,pre_count,post_count;
    uint32_t trend_rise_us,trend_fall_us,level_high_us,feature_updates;
    uint32_t dt_min_us,dt_max_us,max_cycles,record_count;
} DobTrendShadow;
extern DobTrendShadow dob_trend_shadow;
extern DobTrendArena *dob_trend_arena;
void DobTrendClassifier_Reset(DobTrendClassifier *s);
void DobTrendClassifier_Step(DobTrendClassifier *s,DobTrendInput in);
void DobTrendShadow_Bind(void *buffer,size_t bytes);
void DobTrendShadow_Observe(DobTrendInput in,float reference,float accel,float rpm,float iq,uint32_t status);
_Static_assert(sizeof(DobTrendPoint)==24U,"Trend trace record ABI");
_Static_assert(sizeof(DobTrendArena)<=4608U,"Reuse mechanical points, no new ring allocation");
_Static_assert(sizeof(DobTrendShadow)==92U,"Trend header ABI");
#endif

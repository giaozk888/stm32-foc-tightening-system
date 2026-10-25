#ifndef DOB_TREND_CONTINUOUS_H
#define DOB_TREND_CONTINUOUS_H
#include "dob_trend_shadow.h"
/* ABI2: the same classifier, independent whole-RUN timeline and event rings.
 * 138 x60ms covers the original8s RUN; longer sessions overwrite oldest frames
 * explicitly, never stop the classifier. No new control or protection API. */
#define DTC_POINTS 138U
#define DTC_EVENTS 32U
#define DTC_RECORD_US 60000U
enum { DTC_RECORD_WRAP=128U,DTC_EVENT_WRAP=256U,DTC_LOG_NONFINITE=512U };
enum { DTC_ARM=1U,DTC_MEAN_UP,DTC_MEAN_DOWN,DTC_LEVEL,DTC_TREND,DTC_RESET,DTC_STOP };
typedef struct {
    uint32_t encoder_us;
    float disturbance_a,mean_a,trend_a_s;
    int16_t rpm_deci,iq_ma;
    uint16_t flags;uint8_t level,trend;
} DobTrendContinuousPoint;
typedef struct {uint32_t encoder_us;uint16_t type;uint8_t level,trend;} DobTrendEvent;
typedef struct {
    DobTrendClassifier classifier;
    DobTrendContinuousPoint points[DTC_POINTS];
    DobTrendEvent events[DTC_EVENTS];
} DobTrendContinuousArena;
typedef struct {
    uint32_t abi,flags,observations,start_us,last_record_us,arm_qual_us,arm_us;
    float baseline_a,peak_a;
    uint32_t proxy_rise_us,proxy_fall_us,record_overflow,head,event_count,event_dropped;
    uint32_t trend_rise_us,trend_fall_us,level_high_us,feature_updates;
    uint32_t dt_min_us,dt_max_us,max_cycles,record_count,proxy_above,event_head;
} DobTrendContinuous;
extern DobTrendContinuous dob_trend_continuous;
extern DobTrendContinuousArena *dob_trend_continuous_arena;
void DobTrendContinuous_Bind(void *buffer,size_t bytes);
void DobTrendContinuous_Observe(DobTrendInput in,float reference,float accel,float rpm,float iq,uint32_t status);
_Static_assert(sizeof(DobTrendContinuousPoint)==24U,"Continuous point ABI");
_Static_assert(sizeof(DobTrendEvent)==8U,"Trend event ABI");
_Static_assert(sizeof(DobTrendContinuousArena)==4580U,"Original4608B mechanical point ownership");
_Static_assert(sizeof(DobTrendContinuous)==100U,"Continuous header ABI");
#endif

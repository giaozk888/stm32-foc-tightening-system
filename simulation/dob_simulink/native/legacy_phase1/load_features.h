#ifndef DOB_OFFLINE_LOAD_FEATURES_H
#define DOB_OFFLINE_LOAD_FEATURES_H
/* Software-only, read-only consumer. No controller/observer/HAL dependency.
 * Fixed 1 ms calls, 100 ms evidence window; all load values are A-equivalent. */
#define LOAD_WINDOW 100U
enum { LOAD_UNKNOWN,LOAD_LIGHT,LOAD_MEDIUM,LOAD_RISING,LOAD_HIGH,LOAD_RELEASING };
enum { LR_OK,LR_DISABLED,LR_STOP,LR_FAULT,LR_SOURCE,LR_SHORT_GAP,LR_LONG_GAP,
       LR_WARMUP,LR_COVERAGE,LR_DIRECTION,LR_TIME,LR_CONFIG };
typedef struct {
    double light_a,high_a,hysteresis_a,trend_a_s,dwell_s,min_span_s,min_coverage,long_gap_s;
} LoadConfig;
typedef struct {
    double value[LOAD_WINDOW],time[LOAD_WINDOW];
    unsigned char good[LOAD_WINDOW];
    unsigned head,count,state,proposal,accepted,rejected,resets,transitions,have_call;
    int direction,previous_good,have_source;
    double last_call,last_good,last_source,mean,trend,coverage,dwell;
} LoadFeatures;
typedef struct {
    double now_s,source_us,disturbance_a,direction;
    int enabled,running,fault,valid,filter_updated;
} LoadInput;
/* state,valid,mean_A,trend_A_s,coverage,updated,reason,accepted,rejected,
 * quality_resets,dwell_ms,window_good,directional_raw_A,age_ms,transitions,proposal */
#define LOAD_NY 16
LoadConfig Load_DefaultConfig(void);
void Load_Reset(LoadFeatures *s);
void Load_Step(LoadFeatures *s,const LoadConfig *c,LoadInput in,double out[LOAD_NY]);
#endif

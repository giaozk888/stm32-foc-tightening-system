/* Offline Simulink adapter for a generated, audited copy of the actual MCU
 * float classifier. No controller, HAL, protection or actuator interface. */
#define S_FUNCTION_NAME DOB_WINDOW_SFUN_NAME
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include "dob_trend_shadow.h"
#include <string.h>
typedef struct {DobTrendClassifier state;double last_time;double cached[18];} WindowBlock;
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,0);if(ssGetSFcnParamsCount(S))return;
    if(!ssSetNumInputPorts(S,1))return;
    ssSetInputPortWidth(S,0,8);ssSetInputPortDirectFeedThrough(S,0,1);ssSetInputPortRequiredContiguous(S,0,1);
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,18);
    ssSetNumDWork(S,1);ssSetDWorkWidth(S,0,sizeof(WindowBlock));ssSetDWorkDataType(S,0,SS_UINT8);
    ssSetNumSampleTimes(S,1);ssSetOperatingPointCompliance(S,USE_DEFAULT_OPERATING_POINT);
    ssSetOptions(S,SS_OPTION_EXCEPTION_FREE_CODE);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.001);ssSetOffsetTime(S,0,0);}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){WindowBlock b={0};b.last_time=-1;memcpy(ssGetDWork(S,0),&b,sizeof b);}
static void mdlOutputs(SimStruct *S,int_T tid){
    (void)tid;WindowBlock b;memcpy(&b,ssGetDWork(S,0),sizeof b);
    double now=ssGetT(S);
    if(b.last_time<0||now-b.last_time>1e-10){
        const double *u=ssGetInputPortRealSignal(S,0);
        DobTrendInput in={.encoder_us=(uint32_t)(now*1e6+.5)+100000U,
            .observed_us=(uint32_t)(now*1e6+.5)+100020U,.source_us=(uint32_t)u[4],
            .disturbance_a=(float)u[1],.direction=u[6]>0?1:u[6]<0?-1:0,
            .running=1,.fault=(uint8_t)(u[5]!=0),.valid=(uint8_t)(u[2]!=0),.filter_updated=(uint8_t)(u[3]!=0)};
        DobTrendClassifier_Step(&b.state,in);DobTrendClassifier *s=&b.state;
        double y[18]={s->state,s->valid,s->mean,s->trend,s->coverage,s->updated,s->reason,
            s->accepted,s->rejected,s->resets,s->level_changes,s->trend_state,s->trend_valid,
            s->trend_filtered,s->trend_changes,s->level_dwell_us*.001,s->trend_dwell_us*.001,s->proposal};
        memcpy(b.cached,y,sizeof y);b.last_time=now;memcpy(ssGetDWork(S,0),&b,sizeof b);
    }
    memcpy(ssGetOutputPortRealSignal(S,0),b.cached,sizeof b.cached);
}
static void mdlTerminate(SimStruct *S){(void)S;}
#include "simulink.c"

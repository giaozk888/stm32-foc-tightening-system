#define S_FUNCTION_NAME load_features_sfun
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include "load_features.h"
#include <string.h>
typedef struct {LoadFeatures state;double last_time;double cached[LOAD_NY];} LoadBlock;
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,2);if(ssGetNumSFcnParams(S)!=ssGetSFcnParamsCount(S))return;
    if(!mxIsDouble(ssGetSFcnParam(S,0))||mxGetNumberOfElements(ssGetSFcnParam(S,0))!=1||
       !mxIsDouble(ssGetSFcnParam(S,1))||mxGetNumberOfElements(ssGetSFcnParam(S,1))!=11){
        ssSetErrorStatus(S,"Load observer requires enable scalar and 11 configuration values");return;}
    ssSetSFcnParamTunable(S,0,1);ssSetSFcnParamTunable(S,1,0);
    if(!ssSetNumInputPorts(S,2))return;
    for(int k=0;k<2;++k){ssSetInputPortWidth(S,k,k==0?33:10);
        ssSetInputPortDirectFeedThrough(S,k,1);ssSetInputPortRequiredContiguous(S,k,1);}
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,LOAD_NY);
    ssSetNumDWork(S,1);ssSetDWorkWidth(S,0,sizeof(LoadBlock));ssSetDWorkDataType(S,0,SS_UINT8);
    ssSetNumSampleTimes(S,1);ssSetOperatingPointCompliance(S,USE_DEFAULT_OPERATING_POINT);
    ssSetOptions(S,SS_OPTION_EXCEPTION_FREE_CODE);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.001);ssSetOffsetTime(S,0,0);}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){
    LoadBlock b={0};b.last_time=-1;memcpy(ssGetDWork(S,0),&b,sizeof b);
}
static void mdlOutputs(SimStruct *S,int_T tid){
    (void)tid;LoadBlock b;memcpy(&b,ssGetDWork(S,0),sizeof b);
    double now=ssGetT(S);
    if(b.last_time<0||now-b.last_time>1e-10){
        const double *y=ssGetInputPortRealSignal(S,0),*u=ssGetInputPortRealSignal(S,1);
        const double *p=mxGetPr(ssGetSFcnParam(S,1));
        LoadConfig c={p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8],p[9],p[10]};
        LoadInput in={now,y[24],y[10],u[0],mxGetScalar(ssGetSFcnParam(S,0))!=0,
            u[9]!=0,y[29]!=0,y[11]!=0,y[15]!=0};
        Load_Step(&b.state,&c,in,b.cached);b.last_time=now;
        memcpy(ssGetDWork(S,0),&b,sizeof b);
    }
    memcpy(ssGetOutputPortRealSignal(S,0),b.cached,sizeof b.cached);
}
static void mdlTerminate(SimStruct *S){(void)S;}
#include "simulink.c"

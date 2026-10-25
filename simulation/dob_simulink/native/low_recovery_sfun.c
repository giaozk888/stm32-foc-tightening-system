#define S_FUNCTION_NAME LOW_RECOVERY_SFUN_NAME
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include "dob_loader.h"
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,2);if(ssGetSFcnParamsCount(S)!=2)return;
    ssSetSFcnParamTunable(S,0,0);ssSetSFcnParamTunable(S,1,0);
    if(!ssSetNumInputPorts(S,1))return;ssSetInputPortWidth(S,0,14);
    ssSetInputPortDirectFeedThrough(S,0,1);ssSetInputPortRequiredContiguous(S,0,1);
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,33);
    ssSetNumPWork(S,1);ssSetNumRWork(S,34);ssSetNumSampleTimes(S,1);
    ssSetOperatingPointCompliance(S,DISALLOW_OPERATING_POINT);
    ssSetOptions(S,SS_OPTION_EXCEPTION_FREE_CODE);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.001);ssSetOffsetTime(S,0,0);}
#define MDL_START
static void mdlStart(SimStruct *S){
    char *path=mxArrayToString(ssGetSFcnParam(S,0));
    if(!path||!dob_load(path)){if(path)mxFree(path);ssSetErrorStatus(S,"Cannot load isolated recovery DLL");return;}
    mxFree(path);ssSetPWorkValue(S,0,mxCalloc(dob_size(),1));
}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){dob_reset(mxGetPr(ssGetSFcnParam(S,1)));dob_save(ssGetPWorkValue(S,0));ssGetRWork(S)[0]=-1;}
static void mdlOutputs(SimStruct *S,int_T tid){
    (void)tid;double *r=ssGetRWork(S),now=ssGetT(S);
    if(r[0]<0||now-r[0]>1e-10){dob_restore(ssGetPWorkValue(S,0));dob_observe(ssGetInputPortRealSignal(S,0),r+1);dob_save(ssGetPWorkValue(S,0));r[0]=now;}
    memcpy(ssGetOutputPortRealSignal(S,0),r+1,33*sizeof(double));
}
static void mdlTerminate(SimStruct *S){if(ssGetPWorkValue(S,0))mxFree(ssGetPWorkValue(S,0));}
#include "simulink.c"

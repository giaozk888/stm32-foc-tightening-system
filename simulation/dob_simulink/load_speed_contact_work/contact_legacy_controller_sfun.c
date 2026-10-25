#ifndef DOB_CONTROLLER_SFUN_NAME
#define DOB_CONTROLLER_SFUN_NAME dob_controller_sfun
#endif
#define S_FUNCTION_NAME DOB_CONTROLLER_SFUN_NAME
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include "dob_loader.h"
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,2);if(ssGetNumSFcnParams(S)!=ssGetSFcnParamsCount(S))return;
    ssSetSFcnParamTunable(S,0,0);ssSetSFcnParamTunable(S,1,1);
    if(!ssSetNumInputPorts(S,1))return;
    ssSetInputPortWidth(S,0,16);ssSetInputPortDirectFeedThrough(S,0,1);
    ssSetInputPortRequiredContiguous(S,0,1);
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,64);
    ssSetNumSampleTimes(S,1);
    ssSetOperatingPointCompliance(S,USE_CUSTOM_OPERATING_POINT);
    ssSetOptions(S,SS_OPTION_EXCEPTION_FREE_CODE);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.001);ssSetOffsetTime(S,0,0);}
#define MDL_START
static void mdlStart(SimStruct *S){
    char *path=mxArrayToString(ssGetSFcnParam(S,0));
    if(!path||!dob_load(path)){ssSetErrorStatus(S,"Cannot load offline DOB host DLL");if(path)mxFree(path);return;}
    mxFree(path);
}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){dob_reset(mxGetPr(ssGetSFcnParam(S,1)));}
static void mdlOutputs(SimStruct *S,int_T tid){
    (void)tid;dob_step(ssGetT(S),ssGetInputPortRealSignal(S,0),ssGetOutputPortRealSignal(S,0));
}
static void mdlTerminate(SimStruct *S){(void)S;}
#define MDL_OPERATING_POINT
static mxArray *mdlGetOperatingPoint(SimStruct *S){
    mxArray *state=mxCreateNumericMatrix(1,dob_size(),mxUINT8_CLASS,mxREAL);(void)S;
    dob_save(mxGetData(state));return state;
}
static void mdlSetOperatingPoint(SimStruct *S,const mxArray *state){
    if(!mxIsUint8(state)||mxGetNumberOfElements(state)!=dob_size()){
        ssSetErrorStatus(S,"Offline host snapshot ABI mismatch");return;
    }
    dob_restore(mxGetData(state));
    /* Fast Restart restores the cold operating point, then this run's
     * tunable diagnostic gain/enable/cap must remain the requested ones. */
    dob_configure(mxGetPr(ssGetSFcnParam(S,1)));
}
#include "simulink.c"

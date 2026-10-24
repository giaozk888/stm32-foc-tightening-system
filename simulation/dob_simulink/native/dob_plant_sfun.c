#define S_FUNCTION_NAME dob_plant_sfun
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include <math.h>
/* Four physical states: omega [rad/s], actual Iq [A], travel [deg], unused.
 * Current lag is a declared modeling assumption, NOT the real FOC current PI. */
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,1);if(ssGetNumSFcnParams(S)!=ssGetSFcnParamsCount(S))return;
    ssSetSFcnParamTunable(S,0,0);ssSetNumDiscStates(S,3);
    if(!ssSetNumInputPorts(S,1))return;ssSetInputPortWidth(S,0,2);
    ssSetInputPortDirectFeedThrough(S,0,0);ssSetInputPortRequiredContiguous(S,0,1);
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,3);
    ssSetNumSampleTimes(S,1);
    ssSetOperatingPointCompliance(S,USE_DEFAULT_OPERATING_POINT);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.00005);ssSetOffsetTime(S,0,0);}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){real_T *x=ssGetRealDiscStates(S);x[0]=x[1]=x[2]=0;}
static void mdlOutputs(SimStruct *S,int_T tid){
    real_T *x=ssGetRealDiscStates(S),*y=ssGetOutputPortRealSignal(S,0);(void)tid;
    y[0]=x[0];y[1]=x[1];y[2]=x[2];
}
#define MDL_UPDATE
static void mdlUpdate(SimStruct *S,int_T tid){
    real_T *x=ssGetRealDiscStates(S);const real_T *u=ssGetInputPortRealSignal(S,0);
    const double *p=mxGetPr(ssGetSFcnParam(S,0));const double dt=.00005;(void)tid;
    double current=p[4]>0?x[1]+(1-exp(-dt/p[4]))*(u[0]-x[1]):u[0];
    double drive=current-p[3]-u[1],next;
    if(fabs(x[0])<1e-9&&fabs(drive)<=p[2])next=0;
    else {
        double sign=x[0]>0?1:x[0]<0?-1:drive>0?1:-1;
        double torque=drive-p[2]*sign;
        next=p[1]>0?x[0]*exp(-p[1]*dt/p[0])+torque/p[1]*(1-exp(-p[1]*dt/p[0])):
            x[0]+torque/p[0]*dt;
        if(next*x[0]<0&&fabs(drive)<=p[2])next=0;
    }
    x[0]=next;x[1]=current;x[2]+=fabs(next)*dt*180/3.141592653589793;
}
static void mdlTerminate(SimStruct *S){(void)S;}
#include "simulink.c"

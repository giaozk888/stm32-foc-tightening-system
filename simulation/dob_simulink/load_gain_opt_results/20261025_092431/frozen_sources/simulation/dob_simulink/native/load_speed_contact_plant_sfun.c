#define S_FUNCTION_NAME load_speed_contact_plant_sfun
#define S_FUNCTION_LEVEL 2
#include "simstruc.h"
#include <math.h>
/* Same declared RL-free current lag/mechanics as dob_plant_sfun, signed
 * position plus an independent, ideal unilateral fixture. No DOB input. */
static void mdlInitializeSizes(SimStruct *S){
    ssSetNumSFcnParams(S,1);if(ssGetSFcnParamsCount(S)!=1)return;
    ssSetSFcnParamTunable(S,0,0);ssSetNumDiscStates(S,7);
    if(!ssSetNumInputPorts(S,1))return;ssSetInputPortWidth(S,0,5);
    ssSetInputPortDirectFeedThrough(S,0,0);ssSetInputPortRequiredContiguous(S,0,1);
    if(!ssSetNumOutputPorts(S,1))return;ssSetOutputPortWidth(S,0,12);ssSetNumSampleTimes(S,1);
    ssSetOperatingPointCompliance(S,USE_DEFAULT_OPERATING_POINT);
}
static void mdlInitializeSampleTimes(SimStruct *S){ssSetSampleTime(S,0,.00005);ssSetOffsetTime(S,0,0);}
#define MDL_INITIALIZE_CONDITIONS
static void mdlInitializeConditions(SimStruct *S){real_T *x=ssGetRealDiscStates(S);for(int k=0;k<7;++k)x[k]=0;}
static void mdlOutputs(SimStruct *S,int_T tid){
    (void)tid;real_T *x=ssGetRealDiscStates(S),*y=ssGetOutputPortRealSignal(S,0);for(int k=0;k<7;++k)y[k]=x[k];
    const double *p=mxGetPr(ssGetSFcnParam(S,0));for(int k=0;k<5;++k)y[7+k]=p[k];
}
#define MDL_UPDATE
static void mdlUpdate(SimStruct *S,int_T tid){
    (void)tid;real_T *x=ssGetRealDiscStates(S);const real_T *u=ssGetInputPortRealSignal(S,0);
    const double *p=mxGetPr(ssGetSFcnParam(S,0));double dt=.00005;
    double iq=p[4]>0?x[1]+(1-exp(-dt/p[4]))*(u[0]-x[1]):u[0];
    double drive=iq-p[3]-u[1],w=0;
    if(!(fabs(x[0])<1e-9&&fabs(drive)<=p[2])){
        double sign=x[0]>0?1:x[0]<0?-1:drive>0?1:-1,force=drive-p[2]*sign;
        w=p[1]>0?x[0]*exp(-p[1]*dt/p[0])+force/p[1]*(1-exp(-p[1]*dt/p[0])):x[0]+force/p[0]*dt;
        if(w*x[0]<0&&fabs(drive)<=p[2])w=0;
    }
    double position=x[2]+w*dt*180/3.141592653589793,direction=u[4]<0?-1:1,reaction=0;
    if(u[3]!=0&&!(u[3]==2&&x[4]&&x[6]>=.080)&&direction*position>=u[2]&&direction*w>0){
        position=direction*u[2];w=0;x[4]=1;
        reaction=direction*fmax(0,direction*drive-p[2]);
    }
    x[3]=u[1]+reaction;x[5]+=fabs(w)*dt*180/3.141592653589793;
    x[0]=w;x[1]=iq;x[2]=position;
    if(x[4])x[6]+=dt; /* Physical fixture clock, independent of controller/DOB. */
}
static void mdlTerminate(SimStruct *S){(void)S;}
#include "simulink.c"

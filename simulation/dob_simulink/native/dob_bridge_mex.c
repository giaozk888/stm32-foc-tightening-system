#include "mex.h"
#include "dob_loader.h"
void mexFunction(int nlhs,mxArray *plhs[],int nrhs,const mxArray *prhs[]){
    if(nrhs<2)mexErrMsgIdAndTxt("DOB:args","Use reset(dll,config) or step(time,input)");
    char command[20];mxGetString(prhs[0],command,sizeof command);
    if(!strcmp(command,"reset")){
        if(nrhs!=3||mxGetNumberOfElements(prhs[2])!=3)mexErrMsgIdAndTxt("DOB:args","reset arguments");
        char *path=mxArrayToString(prhs[1]);
        if(!path||!dob_load(path))mexErrMsgIdAndTxt("DOB:load","Offline DLL load failed");
        mxFree(path);dob_reset(mxGetPr(prhs[2]));return;
    }
    if(!strcmp(command,"observe")){
        if(nrhs!=2||mxGetNumberOfElements(prhs[1])!=14||nlhs!=1||!dob_dll)
            mexErrMsgIdAndTxt("DOB:args","reset first; observe(14-vector) ->33-vector");
        plhs[0]=mxCreateDoubleMatrix(1,33,mxREAL);
        dob_observe(mxGetPr(prhs[1]),mxGetPr(plhs[0]));return;
    }
    if(strcmp(command,"step")||nrhs!=3||mxGetNumberOfElements(prhs[2])!=10||nlhs!=1||!dob_dll)
        mexErrMsgIdAndTxt("DOB:args","reset first; step(time,10-vector) ->33-vector");
    plhs[0]=mxCreateDoubleMatrix(1,33,mxREAL);
    dob_step(mxGetScalar(prhs[1]),mxGetPr(prhs[2]),mxGetPr(plhs[0]));
}

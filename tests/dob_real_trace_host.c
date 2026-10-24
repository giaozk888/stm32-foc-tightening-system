#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "dob_real_trace.h"
static void push(uint32_t enc,float id,uint8_t valid,uint32_t status){
 DobRealTrace_Observe(1,enc+40,enc,enc/50,id,.15f,25.0f,valid,0,status,1,valid,240,0,.2f);
}
int main(void){
 DobRealTracePoint buffer[DOB_REAL_TRACE_CAPACITY];
 DobRealTrace_Bind(buffer,sizeof buffer);
 /* Idle/calculation preflight cannot fill or arm the trace. */
 DobRealTrace_Observe(0,1,1,1,0,0,0,1,0,0,0,0,0,0,0);
 assert(!dob_real_trace.origin_set);
 push(10000,0,1,0);
 for(unsigned k=1;k<2000;k++)push(10000+k*1000,0,1,0);
 assert(!dob_real_trace.count);
 for(unsigned k=0;k<DOB_REAL_TRACE_CAPACITY;k++)push(2010000+k*1000,k==100?.7f:.005f,k!=100,k==100?1024:0);
 assert(dob_real_trace.count==DOB_REAL_TRACE_CAPACITY&&buffer[100].id_a==.7f);
 assert(!(buffer[100].flags&DRT_INPUT_VALID));
 assert(dob_real_trace.invalid_current==1&&dob_real_trace.filter_skipped==1);
 for(unsigned k=1;k<DOB_REAL_TRACE_CAPACITY;k++)assert(buffer[k].adc_seq_step==20);
 push(2202000,0,1,0);assert(dob_real_trace.done&&!dob_real_trace.overflow);
 DobRealTrace saved=dob_real_trace;push(3000000,2,1,0);assert(!memcmp(&saved,&dob_real_trace,sizeof saved));
 /* Gaps remain gaps, never fake repeated points. Nonfinite is retained and
  * marked for analysis, not silently replaced by a good-looking sample. */
 memset(&dob_real_trace,0,sizeof dob_real_trace);push(0,0,1,0);
 push(2000000,NAN,0,1024);push(2003000,.005f,1,0);push(2192000,0,1,0);
 assert(dob_real_trace.count==2&&dob_real_trace.nonfinite==1);
 assert(buffer[1].encoder_us-buffer[0].encoder_us==3000);
 assert(isnan(buffer[0].id_a));
 /* Clock wrap is unsigned, not a negative/huge late-start rejection. */
 memset(&dob_real_trace,0,sizeof dob_real_trace);
 uint32_t origin=0xfff00000U;push(origin,0,1,0);push(origin+2000000U,.01f,1,0);
 assert(dob_real_trace.count==1);
 puts("PASS: fixed-window raw trace, no spike selection/replay/control side effects");
}

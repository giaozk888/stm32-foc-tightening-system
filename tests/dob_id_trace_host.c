/* Synthetic offline fixture. Calls actual monitor/reset hook; never a board log. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include "dob_id_trace.h"
#include "mechanical_dob_monitor.h"
static unsigned char storage[DIT_BYTES+16];
static MechanicalDobMonitor mon;
int main(int argc,char **argv){
    unsigned mode=argc>1?(unsigned)(argv[1][0]-'0'):0;
    memset(storage,0xA5,sizeof storage);
    DobIdTrace_Bind(storage,DIT_BYTES);DobIdTrace_Lifecycle(1,0);
    MechanicalDobMonitor_Lifecycle(&mon,1,0);
    assert(dob_id_trace.reset_calls_total==0); /* lifecycle is outside capture epoch */
    uint32_t t=mode==2?0xffff0000U:1000,seq=20;
    for(unsigned i=0;i<2200;i++){
        uint32_t dt=mode==2?(i%2?1050:950):1000;
        if(i)t+=dt;
        float id=(mode!=1&&i==800)?.30f:.04f;
        if(mode==3&&i==810){dt=70000;t+=69000;}
        MechanicalCurrent c={2,seq,t+115,t+134,id,.22f,0};
        DobIdTrace_Begin((uint8_t)mon.have_sample);
        MechanicalDobMonitor_Observe(&mon,t+160,t,dt,62.831853f,0,&c,(uint8_t)!(mode==4&&i==820));
        DobIdTrace_After(t,seq,dt,mon.current.id_a,mon.abs_id_lpf,mon.observer.elapsed_s,
            mon.current.status,(uint8_t)mon.current.valid,(uint8_t)mon.observer.initialized,
            (uint8_t)mon.have_sample,600,0,600);
        if(mode==3&&i==810)break;
        seq+=20;
    }
    DobIdTrace_Lifecycle(0,0);MechanicalDobMonitor_Lifecycle(&mon,0,0);
    for(unsigned i=DIT_BYTES;i<sizeof storage;i++)assert(storage[i]==0xA5);
    assert(dob_id_trace.frozen&&!dob_id_trace.running);
    if(mode==1){assert(!dob_id_trace.post_count&&dob_id_trace.state==DIT_STOPPED);}
    else if(mode!=3){
        assert(dob_id_trace.state==DIT_DONE&&dob_id_trace.post_count==64&&dob_id_trace.tail_count==160);
        assert(dob_id_trace.reset_calls_total>=4&&dob_id_trace.reset_calls_total<=6);
        assert(dob_id_trace.trigger_seq==16020);
        DobIdTraceFrame f;memcpy(&f,storage+64*16,16);
        assert((f.flags&(DIT_TRIGGER|DIT_RESET))==(DIT_TRIGGER|DIT_RESET));
        assert(f.warmup_s==0&&f.abs_id_lpf>.05f&&f.abs_id_lpf<.055f);
    }
    unsigned calls=dob_id_trace.reset_calls_total;
    DobIdTrace_Lifecycle(1,0);DobIdTrace_Begin(0);DobIdTrace_ResetEvent(256);
    assert(!dob_id_trace.in_epoch&&dob_id_trace.reset_calls_total==calls);
    _setmode(_fileno(stdout),_O_BINARY);
    fwrite(&dob_id_trace,sizeof dob_id_trace,1,stdout);fwrite(storage,DIT_BYTES,1,stdout);
    return 0;
}

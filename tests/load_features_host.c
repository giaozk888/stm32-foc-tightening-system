#include "load_features.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static LoadConfig cfg;
static LoadFeatures s;
static double y[LOAD_NY];
static void feed(int k,double load,int good,int direction){
    LoadInput in={k*.001,k*1000.+100020,load,direction,1,1,0,good,good};
    Load_Step(&s,&cfg,in,y);
    for(unsigned i=0;i<LOAD_NY;++i)assert(isfinite(y[i]));
}
static void settle(double load,int direction){
    Load_Reset(&s);for(int k=0;k<500;++k)feed(k,load,1,direction);
}
int main(void){
    cfg=Load_DefaultConfig();
    settle(0,1);assert(y[0]==LOAD_LIGHT&&y[1]);
    settle(.04,1);assert(y[0]==LOAD_HIGH&&y[1]);
    settle(-.04,-1);assert(y[0]==LOAD_HIGH&&fabs(y[2]-.04)<1e-12);
    settle(.017,1);assert(y[0]==LOAD_MEDIUM);
    /* The quarantined +700mA value must never enter any feature statistic. */
    double mean=y[2],trend=y[3],dwell=y[10],accepted=y[7],resets=y[9];
    feed(500,.7,0,1);
    assert(y[2]==mean&&y[3]==trend&&y[10]==dwell&&y[7]==accepted&&y[9]==resets&&!y[1]);
    feed(501,.017,1,1);assert(y[0]==LOAD_MEDIUM&&y[1]&&y[10]==dwell);
    /* Repeated rejected evidence cannot extend accepted dwell. */
    for(int k=502;k<505;++k)feed(k,.7,0,1);
    assert(y[9]==resets&&y[10]==dwell);
    for(int k=505;k<530;++k)feed(k,.7,0,1);
    assert(y[0]==LOAD_UNKNOWN&&!y[1]&&y[9]==resets+1);
    for(int k=530;k<730;++k)feed(k,.04,1,1);
    assert(y[0]==LOAD_HIGH&&y[1]);
    /* A sustained actual level/ramp is not rejected just for being large. */
    settle(0,1);for(int k=500;k<800;++k)feed(k,(k-500)*.00015,1,1);
    assert(y[0]==LOAD_HIGH&&y[16]==TREND_RISING);
    for(int k=800;k<1300;++k)feed(k,.045,1,1);
    assert(y[0]==LOAD_HIGH);
    double level_changes=y[14];
    for(int k=1300;k<1600;++k)feed(k,.045-(k-1300)*.00004,1,1);
    assert(y[0]==LOAD_HIGH&&y[16]==TREND_FALLING&&y[14]==level_changes);
    /* Reversal, source repeats and invalid numerical input are not new evidence. */
    feed(1600,-.02,1,-1);assert(y[0]==LOAD_UNKNOWN&&!y[1]);
    LoadInput in={1.601,1600*1000.+100020,-.02,-1,1,1,0,1,1};
    accepted=s.accepted;Load_Step(&s,&cfg,in,y);assert(s.accepted==accepted&&!y[1]);
    in.now_s=1.602;in.source_us+=2000;in.disturbance_a=NAN;Load_Step(&s,&cfg,in,y);
    assert(!y[1]);for(unsigned j=0;j<LOAD_NY;++j)assert(isfinite(y[j]));
    in.now_s=NAN;Load_Step(&s,&cfg,in,y);assert(y[0]==LOAD_UNKNOWN);
    settle(.04,1);in=(LoadInput){.5,600020,.04,1,1,1,1,1,1};
    Load_Step(&s,&cfg,in,y);assert(y[0]==LOAD_UNKNOWN&&y[6]==LR_FAULT);
    settle(.04,1);in.fault=0;in.running=0;Load_Step(&s,&cfg,in,y);assert(y[6]==LR_STOP&&!y[1]);
    settle(.04,1);in.running=1;in.enabled=0;Load_Step(&s,&cfg,in,y);assert(y[6]==LR_DISABLED);
    cfg.high_a=NAN;Load_Step(&s,&cfg,in,y);assert(y[6]==LR_CONFIG&&!y[1]);
    puts("PASS: levels, reverse, isolated spike, short/long gaps, recovery, trends, source/time/NaN, stop/fault/config");
    return 0;
}

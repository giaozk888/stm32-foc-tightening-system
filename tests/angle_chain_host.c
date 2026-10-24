#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "foc_angle_chain_diag.h"
#include "foc_torque_chain_diag.h"
static void observe_turn(FocAngleHand *s,int direction,unsigned pairs)
{
    unsigned raw=1234; int count=0; uint32_t now=1000;
    FocAngleHand_Begin(s,now);
    for(unsigned i=0;i<=2048;++i) {
        if(i) { int step=i<=1024 ? -16 : 16; raw=(raw+step)&16383U; count-=step; }
        FocAngleHand_Observe(s,now,(uint16_t)raw,
            AS5047P_ElectricalAngleRad((uint16_t)raw,10507,pairs,direction),
            (float)count*(360.0f/16384.0f),1,1);
        now+=1000;
        if(i==1024 && pairs==10 && direction==-1) {
            assert(s->mechanical_counts==16384);
            assert(fabsf(s->electrical_deg-3600.0f)<.1f);
        }
    }
}
int main(void)
{
    FocAngleHand s={0};
    observe_turn(&s,-1,10);
    assert(FocAngleHand_End(&s) && s.passed && !s.active);
    assert(s.max_counts==16384 && s.mechanical_counts==0 && s.errors==0);
    assert(fabsf(s.electrical_deg)<.1f && s.records>ANGLE_HAND_ROWS);
    for(unsigned i=s.records-ANGLE_HAND_ROWS;i<s.records;++i) assert(s.rows[i%ANGLE_HAND_ROWS].seq==i);
    observe_turn(&s,1,10); assert(!FocAngleHand_End(&s));
    observe_turn(&s,-1,9); assert(!FocAngleHand_End(&s));
    FocAngleHand_Begin(&s,0);
    FocAngleHand_Observe(&s,1000,10,1,0,1,1);
    FocAngleHand_Observe(&s,10000,10,1,0,1,1); assert(s.errors);
    assert(!FocAngleHand_End(&s));
    FocAngleHand_Begin(&s,0);
    FocAngleHand_Observe(&s,1000,10,1,0,0,1); assert(!s.active && s.errors && !s.passed);
    FocAngleHand_Begin(&s,0);
    FocAngleHand_Observe(&s,1000,10,NAN,0,1,1); assert(!s.active && s.errors);
    FocAngleHand_Begin(&s,0);
    FocAngleHand_Observe(&s,1000,10,1,0,1,1);
    FocAngleHand_Observe(&s,2000,8202,1,0,1,1); assert(s.errors);
    int32_t sign,offset;
    const char *good[]={"-30","-20","-10","0","+10","+20","+30"};
    const int expected[]={-30,-20,-10,0,10,20,30};
    char cmd[96];
    for(unsigned i=0;i<7;++i) {
        snprintf(cmd,sizeof cmd,"MOTOR TEST ANGLE OFFSET %s CONFIRM",good[i]);
        assert(FocAngleOffset_Parse(cmd,&sign,&offset));
        assert(sign==1 && offset==expected[i] && FocAngleOffset_Allowed(offset));
        for(unsigned raw=0;raw<16384;raw+=127) {
            float base=AS5047P_ElectricalAngleRad(raw,10507,10,-1);
            float theta=FocTorqueChain_Angle(base,offset);
            float want=fmodf(base+(float)offset*.0174532925199433f,6.283185307179586f);
            if(want<0) want+=6.283185307179586f;
            assert(theta>=0 && theta<6.283186f && fabsf(theta-want)<1e-5f);
        }
    }
    const char *bad[]={"MOTOR TEST ANGLE OFFSET +40 CONFIRM","MOTOR TEST ANGLE OFFSET 10 CONFIRM",
        "MOTOR TEST ANGLE OFFSET +10 CONFIRM extra","MOTOR TEST ANGLE OFFSET +10",
        "MOTOR TEST ANGLE SWEEP CONFIRM","MOTOR TEST TORQUE350 CONFIRM","START"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];++i) assert(!FocAngleOffset_Parse(bad[i],&sign,&offset));
    return 0;
}

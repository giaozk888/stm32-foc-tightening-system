#include "foc_repair_trace.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void feed(FocRepairTrace *t,uint32_t seq,uint8_t mask)
{
    FocRepairTrace_Record(t,seq,seq*50U,1560U,1800U,1561U,1562U,1U,mask,22U,40U);
}
int main(void)
{
    FocRepairTrace t={0}; char text[256]; FocRepairTraceRow row;
    assert(!FocRepairTrace_Row(&t,0U,&row));
    assert(FocRepairTrace_Format(&t,"MOTOR TEST REPAIR",text,sizeof text));
    assert(strstr(text,"FROZEN=0"));
    for (uint32_t i=1U;i<=70U;++i) feed(&t,i,(uint8_t)(i%4U));
    assert(t.count==32U && !t.gap);
    FocRepairTrace_Freeze(&t,9U,0x5555U,1U,6U,4U,55U);
    assert(t.frozen && t.cause==1U && FocRepairTrace_Hits(t.window)==8U);
    for (unsigned i=0U;i<32U;++i) {
        assert(FocRepairTrace_Row(&t,i,&row));
        assert(row.seq==39U+i && row.raw_u==1560U && row.raw_v==1800U);
        assert(row.filtered_u==1561U && row.filtered_v==1562U && row.ready);
        assert(row.mask==row.seq%4U && row.jump_u==22U && row.jump_v==40U);
    }
    FocRepairTrace saved=t;
    feed(&t,71U,3U); FocRepairTrace_Freeze(&t,3U,0U,0U,32U,32U,0U);
    assert(!memcmp(&t,&saved,sizeof t));
    assert(FocRepairTrace_Format(&t,"MOTOR TEST REPAIR",text,sizeof text));
    assert(strstr(text,"REASON=9 CAUSE=1 HITS=8 LIMIT=6 STREAK=1 SLIMIT=4 GAP=0"));
    const char *bad[]={"-1","32","9999999999999999999999999","1x","","+1"," 1"};
    for (unsigned i=0U;i<sizeof bad/sizeof bad[0];++i) {
        char cmd[80]; snprintf(cmd,sizeof cmd,"MOTOR TEST REPAIR ROW %s",bad[i]);
        assert(FocRepairTrace_Format(&t,cmd,text,sizeof text)); assert(strstr(text,"ERR 109"));
    }
    assert(FocRepairTrace_Format(&t,"MOTOR TEST REPAIR ROW 31",text,sizeof text));
    assert(strstr(text,"SEQ=70 SRC=69 RAW=1560,1800 FILTER=1561,1562 MASK=2 READY=1 JUMP=22,40"));
    assert(!FocRepairTrace_Format(&t,"STOP",text,sizeof text));
    t=(FocRepairTrace){0}; feed(&t,UINT32_MAX,1U); feed(&t,0U,0U);
    FocRepairTrace_Freeze(&t,9U,31U,5U,6U,4U,5U);
    assert(!t.gap && t.cause==2U); assert(FocRepairTrace_Row(&t,0U,&row) && row.seq==UINT32_MAX);
    assert(FocRepairTrace_Row(&t,1U,&row) && row.seq==0U);
    t=(FocRepairTrace){0}; feed(&t,1U,1U); feed(&t,3U,3U);
    FocRepairTrace_Freeze(&t,9U,127U,5U,6U,4U,7U);
    assert(t.cause==3U && t.gap && !FocRepairTrace_Row(&t,0U,&row));
    t=(FocRepairTrace){0};
    FocRepairTrace_Record(&t,1U,50U,4095U,0U,4095U,0U,1U,3U,63U,0U);
    FocRepairTrace_Freeze(&t,3U,0U,0U,6U,4U,0U);
    assert(FocRepairTrace_Row(&t,0U,&row));
    assert(row.raw_u==4095U && row.filtered_u==4095U && row.jump_u==63U && !row.jump_v);
    t=(FocRepairTrace){0};
    FocRepairTrace_Record(&t,1U,50U,4096U,0U,0U,0U,1U,0U,20U,20U);
    assert(t.gap && !t.count);
    t=(FocRepairTrace){.count=32U,.frozen=1U,.last_seq=UINT32_MAX,
        .last_us=UINT32_MAX,.window=UINT32_MAX,.repaired=UINT32_MAX,
        .reason=255U,.cause=3U,.streak=255U,.limit=255U,.streak_limit=255U};
    assert(FocRepairTrace_Format(&t,"MOTOR TEST REPAIR",text,sizeof text));
    assert(strstr(text,"TOTAL=4294967295") && strlen(text)<sizeof text-1U);
    puts("PASS trace packing/ring/freeze/sequence/wrap/window/streak/commands");
}

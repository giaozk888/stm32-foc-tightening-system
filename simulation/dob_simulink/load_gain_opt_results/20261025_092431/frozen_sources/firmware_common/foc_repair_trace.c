#include "foc_repair_trace.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void FocRepairTrace_Record(FocRepairTrace *t,uint32_t seq,uint32_t us,
    uint16_t raw_u,uint16_t raw_v,uint16_t u,uint16_t v,
    uint8_t ready,uint8_t mask,uint16_t jump_u,uint16_t jump_v)
{
    if (t->frozen) return;
    if (raw_u>4095U || raw_v>4095U || u>4095U || v>4095U ||
        ready>1U || mask>3U || jump_u>63U || jump_v>63U) { t->gap=1U; return; }
    if (t->count && (uint32_t)(seq-t->last_seq)!=1U) t->gap=1U;
    t->rows[t->next]=(uint64_t)raw_u | ((uint64_t)raw_v<<12U) |
        ((uint64_t)u<<24U) | ((uint64_t)v<<36U) | ((uint64_t)mask<<48U) |
        ((uint64_t)ready<<50U) | ((uint64_t)jump_u<<51U) | ((uint64_t)jump_v<<57U);
    t->next=(uint8_t)((t->next+1U)&31U);
    if (t->count<FOC_REPAIR_TRACE_N) ++t->count;
    t->last_seq=seq; t->last_us=us;
}
unsigned FocRepairTrace_Hits(uint32_t bits)
{
    bits-=(bits>>1U)&UINT32_C(0x55555555);
    bits=(bits&UINT32_C(0x33333333))+((bits>>2U)&UINT32_C(0x33333333));
    bits=(bits+(bits>>4U))&UINT32_C(0x0f0f0f0f);
    bits+=bits>>8U; bits+=bits>>16U;
    return bits&63U;
}
void FocRepairTrace_Freeze(FocRepairTrace *t,uint8_t reason,uint32_t window,
    uint8_t streak,uint8_t limit,uint8_t streak_limit,uint32_t repaired)
{
    if (t->frozen) return;
    t->reason=reason; t->window=window; t->streak=streak;
    t->limit=limit; t->streak_limit=streak_limit; t->repaired=repaired;
    t->cause=(uint8_t)((FocRepairTrace_Hits(window)>limit?1U:0U) |
        (streak>streak_limit?2U:0U));
    t->frozen=1U;
}
int FocRepairTrace_Row(const FocRepairTrace *t,unsigned i,FocRepairTraceRow *out)
{
    if (!t->frozen || t->gap || i>=t->count) return 0;
    unsigned slot=(t->next+FOC_REPAIR_TRACE_N-t->count+i)&31U;
    uint64_t bits=t->rows[slot];
    *out=(FocRepairTraceRow){.seq=t->last_seq-(uint32_t)t->count+1U+i,
        .raw_u=(uint16_t)(bits&4095U),.raw_v=(uint16_t)((bits>>12U)&4095U),
        .filtered_u=(uint16_t)((bits>>24U)&4095U),.filtered_v=(uint16_t)((bits>>36U)&4095U),
        .mask=(uint8_t)((bits>>48U)&3U),.ready=(uint8_t)((bits>>50U)&1U),
        .jump_u=(uint8_t)((bits>>51U)&63U),.jump_v=(uint8_t)((bits>>57U)&63U)};
    return 1;
}
int FocRepairTrace_Format(const FocRepairTrace *t,const char *cmd,char *out,size_t size)
{
    static const char summary[]="MOTOR TEST REPAIR";
    static const char prefix[]="MOTOR TEST REPAIR ROW ";
    int is_summary=!strcmp(cmd,summary);
    if (!is_summary && strncmp(cmd,prefix,sizeof prefix-1U)) return 0;
    if (!t->frozen) {
        snprintf(out,size,"OK REPAIR ENABLED=1 HARD_OFF=1 N=32 FROZEN=0"); return 1;
    }
    if (is_summary) {
        snprintf(out,size,"OK REPAIR ENABLED=1 HARD_OFF=1 N=32 FROZEN=1 COUNT=%u SEQ=%lu US=%lu REASON=%u CAUSE=%u HITS=%u LIMIT=%u STREAK=%u SLIMIT=%u GAP=%u WIN=0x%08lX TOTAL=%lu",
            t->count,(unsigned long)t->last_seq,(unsigned long)t->last_us,t->reason,t->cause,
            FocRepairTrace_Hits(t->window),t->limit,t->streak,t->streak_limit,t->gap,
            (unsigned long)t->window,(unsigned long)t->repaired); return 1;
    }
    const char *arg=cmd+sizeof prefix-1U;
    char *end=NULL;
    unsigned long i=(*arg>='0' && *arg<='9')?strtoul(arg,&end,10):FOC_REPAIR_TRACE_N;
    FocRepairTraceRow row;
    if (i>=FOC_REPAIR_TRACE_N || *end || !FocRepairTrace_Row(t,(unsigned)i,&row)) {
        snprintf(out,size,"ERR 109 REPAIR_ROW"); return 1;
    }
    snprintf(out,size,"OK REPAIR ROW I=%lu SEQ=%lu SRC=%lu RAW=%u,%u FILTER=%u,%u MASK=%u READY=%u JUMP=%u,%u",
        i,(unsigned long)row.seq,(unsigned long)(row.ready?row.seq-1U:0U),
        row.raw_u,row.raw_v,row.filtered_u,row.filtered_v,row.mask,row.ready,row.jump_u,row.jump_v);
    return 1;
}

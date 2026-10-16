/* Frozen local UART records only. No interrupt mask around ring export. */
static void ZeroTrace_Point(uint32_t id,const char *kind,unsigned index,const FocZeroTracePoint *p)
{
    char msg[240];
    (void)Protocol_SendFormatted(msg,sizeof(msg),
        "%lu OK ZERO_TRACE_%s INDEX=%u SEQ=%lu A=%u,%u B=%u,%u C=%u,%u FILTER=%u,%u MASK=%u\r\n",
        (unsigned long)id,kind,index,(unsigned long)p->seq,p->au,p->av,p->bu,p->bv,
        p->cu,p->cv,p->fu,p->fv,p->mask);
}
static uint8_t ZeroTrace_Command(uint32_t id,const char *cmd)
{
    if (strcmp(cmd,"ZERO TRACE STATUS")==0) {
        if (zero_retest_running) { Protocol_SendError(id,PROTO_ERR_BUSY,"ZERO_TRACE_ACTIVE"); return 1U; }
        char msg[320];
        (void)Protocol_SendFormatted(msg,sizeof(msg),
            "%lu OK ZERO_TRACE TRACE=1 DONE=%u HIT=%u CENTER=%lu PHYSICAL=%lu POST=%u ROWS=%u "
            "REASON=%u N_BEFORE=%lu RET=%lu S=%lu D=%lu RANGE=%u:%u,%u:%u EXTREMA=%u DELAY_PAIRS=1 "
            "FILTER_REV=%u END=%u JUMP=%u MEAN=1\r\n",
            (unsigned long)id,zero_trace.done,zero_trace.triggered,(unsigned long)zero_trace.trigger,
            (unsigned long)zero_trace.physical,zero_trace.post,FocTrace_Rows(&zero_trace),
            zero_trace.reason,(unsigned long)zero_trace.window_count,(unsigned long)zero_trace.restarts,
            (unsigned long)zero_trace.span_restarts,(unsigned long)zero_trace.drift_restarts,
            zero_trace.min_u,zero_trace.max_u,zero_trace.min_v,zero_trace.max_v,zero_trace.extrema_valid,
            (unsigned)FOC_SPIKE3_FILTER_REV,(unsigned)FOC_SPIKE3_ENDPOINT_COUNTS,(unsigned)FOC_SPIKE3_JUMP_COUNTS);
        return 1U;
    }
    const char *arg=NULL; uint8_t extreme=0U;
    if (strncmp(cmd,"ZERO TRACE READ ",16U)==0) arg=cmd+16U;
    else if (strncmp(cmd,"ZERO TRACE EXTREME ",19U)==0) { arg=cmd+19U; extreme=1U; }
    else return 0U;
    if (zero_retest_running || !zero_trace.done) {
        Protocol_SendError(id,PROTO_ERR_BUSY,"ZERO_TRACE_NOT_FROZEN"); return 1U;
    }
    unsigned index=0U,n=0U;
    while (*arg>='0' && *arg<='9' && n<3U) { index=index*10U+(unsigned)(*arg++-'0'); ++n; }
    FocZeroTracePoint p;
    if (!n || *arg || (extreme ? (index>=4U || !zero_trace.extrema_valid) :
        !FocTrace_Read(&zero_trace,index,&p))) {
        Protocol_SendError(id,PROTO_ERR_BAD_ARGUMENT,"ZERO_TRACE_BAD_INDEX"); return 1U;
    }
    if (extreme) p=zero_trace.extrema[index];
    ZeroTrace_Point(id,extreme?"EXTREME":"ROW",index,&p);
    return 1U;
}

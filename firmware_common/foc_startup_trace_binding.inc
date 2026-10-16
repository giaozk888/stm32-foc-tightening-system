/* Included only by the opt-in startup-evidence candidate. Never at 20 kHz. */
#include "foc_startup_trace.h"
static FocStartupTrace cl_startup;
static FocStartupFrame ProtectedLoop_StartupFrame(uint32_t now)
{
    return (FocStartupFrame){.us=now,.adc_seq=cl_seq,
        .encoder_us=encoder_dma_cursor.sample_us,.angle=encoder_raw,
        .u=cl_last_u,.v=cl_last_v,.ref=speed_ref_rpm,
        .instant=encoder_rpm_instant,.speed=encoder_speed_rpm,
        .iq_ref=foc_iq_ref_A,.id=foc_id_A,.iq=foc_iq_A,
        .vd=foc_vd_V,.vq=foc_vq_V,.int_d=foc_int_d_V,.int_q=foc_int_q_V};
}
static void ProtectedLoop_StartupPush(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (cl_session.state==CL_RUNNING && cl_startup.active)
        FocStartup_Push(&cl_startup,ProtectedLoop_StartupFrame(AS5047P_DmaNowUs()));
    __set_PRIMASK(mask);
}
static int ProtectedLoop_StartupCommand(const char *cmd,char *out,size_t size)
{
    const char *prefix="MOTOR TEST STARTUP";
    if (strncmp(cmd,prefix,strlen(prefix))) return 0;
    if (!strcmp(cmd,"MOTOR TEST STARTUP CONFIG")) {
        snprintf(out,size,"OK STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1 BYTES=%lu",
            (unsigned long)sizeof cl_startup); return 1;
    }
    /* No live transfer/formatting while bridge is enabled. A frozen trace
     * is immutable until reset, so no large memcpy under PRIMASK is needed. */
    if (!cl_startup.frozen) {
        snprintf(out,size,"ERR 109 STARTUP_NOT_FROZEN"); return 1;
    }
    if (!strcmp(cmd,prefix)) {
        snprintf(out,size,"OK STARTUP N=%lu TOTAL=%lu FROZEN=1 FAULT=%u FIRST_FLAGS=%lu OFF_US=%lu ORDER=REF,INST,CTRL;IQREF,ID,IQ;VD,VQ;INTD,INTQ",
            (unsigned long)FocStartup_Count(&cl_startup),(unsigned long)cl_startup.total,
            cl_startup.fault_valid,(unsigned long)cl_startup.first_flags,
            (unsigned long)cl_startup.first_off_us); return 1;
    }
    if (!strcmp(cmd,"MOTOR TEST STARTUP FAULT") && cl_startup.fault_valid) {
        FocStartup_Format(&cl_startup.fault,out,(uint32_t)size); return 1;
    }
    const char *frame_prefix="MOTOR TEST STARTUP FRAME ";
    const char *digit=cmd;
    uint32_t index=0U; int valid=0; FocStartupFrame row;
    if (!strncmp(cmd,frame_prefix,strlen(frame_prefix))) {
        digit=cmd+strlen(frame_prefix);
        valid=*digit!='\0';
        while (*digit) {
            if (*digit<'0' || *digit>'9' || index>=FOC_STARTUP_ROWS) { valid=0; break; }
            index=index*10U+(uint32_t)(*digit++-'0');
        }
    }
    if (valid && FocStartup_Get(&cl_startup,index,&row))
        FocStartup_Format(&row,out,(uint32_t)size);
    else snprintf(out,size,"ERR 109 STARTUP_FRAME");
    return 1;
}

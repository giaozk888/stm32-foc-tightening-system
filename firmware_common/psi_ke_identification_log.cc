#define PW_LOG_MODULE_NAME "PSI_IDENT"
#include "psi_ke_identification.h"
#include "pw_log/log.h"
extern "C" void PsiIdent_Log(const PsiIdentFrame *f)
{
    /* Same index across four <=32-byte token payloads, 20 Hz task context. */
    PW_LOG_INFO("PSI R index=%u seq=%u us=%u rpm=%.5f we=%.6f",
        unsigned(f->index),unsigned(f->seq),unsigned(f->us),f->rpm,f->we);
    PW_LOG_INFO("PSI I index=%u id=%.7f iq=%.7f vd=%.7f vq=%.7f",
        unsigned(f->index),f->id,f->iq,f->vd,f->vq);
    PW_LOG_INFO("PSI E index=%u resistive=%.7f cross=%.7f bemf=%.7f psi=%.9f",
        unsigned(f->index),f->resistive,f->cross,f->bemf,f->psi);
    PW_LOG_INFO("PSI S index=%u quality=%u sat=%u fault=%u stage=%u",
        unsigned(f->index),unsigned(f->quality),unsigned(f->saturated),unsigned(f->fault),unsigned(f->stage));
}

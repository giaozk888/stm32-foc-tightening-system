#ifndef DOB_NORMAL_CONTROL_H
#define DOB_NORMAL_CONTROL_H
#include "dob_feedback_candidate.h"
#include "mechanical_dob_monitor.h"
#if !defined(FOC_DOB_FEEDBACK_CANDIDATE) || !defined(FOC_DOB_ID_PRE_LPF_QUALITY)
#error Normal DOB requires the reviewed bounded feedback and pre-LPF admission
#endif
#if defined(FOC_DOB_GAIN_AB_DIAG)
#if !defined(FOC_DOB_REAL_TRACE) || !defined(FOC_DOB_CONTACT20_OBSERVE10)
#error Gain A/B is restricted to the explicit raw-trace diagnostic A
#endif
#else
_Static_assert(DOB_FB_GAIN==.25f,"Normal DOB gain must remain the selected 0.25");
#endif
/* Task-only lifecycle. No command, power, current feedback or watchdog write.
 * The original START/admission/one-use lease stays authoritative. Re-entering
 * SPEED after an explicit FSM mode change starts a fresh observer, not a motor.
 * OFF persists until an idle guarded ON or MCU reboot; bad quality uses the
 * existing observer gate and feedback hold/fade, not a new fault bypass. */
static inline void DobNormal_Lifecycle(MechanicalDobMonitor *m,DobFeedbackCandidate *f,
                                      uint8_t running,uint8_t fault)
{
    if(!running||fault){
        DobFeedback_Clear(f);
        MechanicalDobMonitor_Lifecycle(m,0,fault);
        return;
    }
    if(!m->running){
        MechanicalDobMonitor_Rearm(m);
        DobFeedback_Clear(f);
    }
    MechanicalDobMonitor_Lifecycle(m,1,0);
}
#endif

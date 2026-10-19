"""Actual C guard + extracted production FSM regressions; no hardware."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'firmware_common'
OUT=ROOT/'tests/rundown_guard_build'
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


def extract_braces(text,start):
    begin=text.index('{',start); depth=1; end=begin+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}'); end+=1
    return text[start:end]


class RundownTests(unittest.TestCase):
    def run_c(self,name,source):
        OUT.mkdir(exist_ok=True)
        path=OUT/(name+'.c'); path.write_text(source,encoding='utf-8')
        for opt in ('-Os','-O2'):
            exe=OUT/(name+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-I',str(COMMON),'-I',str(ROOT/'tests'),str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_guard_direction_glitch_travel_gap_and_binary_window(self):
        self.run_c('guard',(ROOT/'tests/rundown_guard_host.c').read_text())

    def actual_switch_source(self,protected=False):
        text=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        enums='\n'.join(re.findall(r'typedef enum\s*\{[^}]+\}\s*(?:TighteningTestStage_t|TighteningOutcome_t);',text))
        block=extract_braces(text,text.index('switch (tightening_test_stage)',text.index('static void TighteningTask(void *argument)\n{')))
        return ('#define FOC_PROTECTED_CLOSED_LOOP 1\n' if protected else '')+(ROOT/'tests/rundown_fsm_host_prefix.h').read_text()+'\n'+enums+'''
static TighteningTestStage_t tightening_test_stage;
static TighteningOutcome_t tightening_last_outcome;
#include "tightening_rundown_binding.inc"
static TickType_t stage_start;
static uint32_t stop_confirm_ms;
static void step(uint32_t now,float ctrl,float det_rpm,float position,float demand) {
    uint32_t elapsed_ms=now-stage_start;
    float drive_iqref=demand,travel=fabsf(position),post_contact_travel=0;
    encoder_position_deg=position; encoder_speed_rpm=ctrl; foc_iq_ref_A=demand;
    tightening_test_elapsed_ms=elapsed_ms;
'''+block+'''
    if (tightening_contact_confirmed) contact_seen=1;
}
static void begin(void) {
    TightenRundown_Begin(&tightening_rundown);
    tightening_test_stage=TIGHTEN_STATE_RUNDOWN;
    tightening_last_outcome=TIGHTEN_OUTCOME_NONE;
    tightening_contact_candidate_ms=stop_confirm_ms=stage_start=0;
    tightening_contact_confirmed=tightening_result_printed=0;
    power_off=ok_events=contact_seen=iq_stages=0;
    recipe_state.params.rundown_rpm=20; recipe_state.params.contact_rpm=10;
    recipe_state.params.contact_iq_mA=300; recipe_state.params.contact_ms=250;
    recipe_state.params.rundown_timeout_ms=8000; recipe_state.params.max_travel_deg=3000;
    recipe_state.params.seating_iq_mA=80; recipe_state.params.t1_iq_mA=100;
    recipe_state.params.t2_iq_mA=120; recipe_state.params.t3_iq_mA=150;
    recipe_state.params.hold_iq_mA=150;
    recipe_state.params.seating_ms=recipe_state.params.t1_ms=300;
    recipe_state.params.t2_ms=recipe_state.params.t3_ms=300;
    recipe_state.params.hold_ms=500; recipe_state.params.torque_abort_rpm=30;
    recipe_state.params.post_travel_max_deg=90;
}
'''

    def test_actual_fsm_no_motion_cannot_contact_or_ok(self):
        self.run_c('no_motion',self.actual_switch_source()+'''
#include <assert.h>
int main(void) {
    for (unsigned scenario=0;scenario<3;++scenario) {
        begin();
        for (uint32_t t=0;t<=4000;t+=10) {
            float s=scenario==0 ? 0 : (scenario==1 ? 2.77f : (t==100 ? 100.0f:0.0f));
            step(t,s,s,t*.01662f,.35f);
            assert(!contact_seen && !ok_events && !iq_stages);
        }
        assert(tightening_last_outcome==TIGHTEN_OUTCOME_NO_ROTATION);
        assert(tightening_test_stage==TIGHTEN_STATE_FAULT && power_off==1);
    }
}
''')

    def test_actual_fsm_established_contact_full_sequence_ok(self):
        self.run_c('normal',self.actual_switch_source()+'''
#include <assert.h>
int main(void) {
    begin();
    for (uint32_t t=0;t<=200;t+=10) step(t,20,20,t*.12f,.2f);
    assert(tightening_rundown.state==RUNDOWN_ARMED);
    for (uint32_t t=210;t<=440;t+=10) step(t,0,0,24,.35f);
    assert(!contact_seen); step(450,0,0,24,.35f);
    assert(contact_seen && tightening_test_stage==TIGHTEN_STATE_CONTACT_STOP);
    for (uint32_t t=460;t<=3000;t+=10) step(t,0,0,24,.15f);
    assert(tightening_test_stage==TIGHTEN_STATE_DONE);
    assert(tightening_last_outcome==TIGHTEN_OUTCOME_OK && ok_events==1 && iq_stages==5);
    assert(power_off==0);
}
''')

    def test_actual_hold_ok_requires_both_latches(self):
        self.run_c('hold_gate',self.actual_switch_source()+'''
#include <assert.h>
int main(void) {
    for (unsigned armed=0;armed<2;++armed) for (unsigned contact=0;contact<2;++contact) {
        begin(); tightening_test_stage=TIGHTEN_STATE_HOLD;
        tightening_rundown.state=(uint8_t)armed; tightening_contact_confirmed=(uint8_t)contact;
        step(500,0,0,0,.15f);
        assert(ok_events==(armed && contact));
        if (!ok_events) assert(tightening_last_outcome==TIGHTEN_OUTCOME_NO_ROTATION);
    }
}
''')

    def test_existing_timeout_and_post_contact_abort_are_preserved(self):
        self.run_c('old_failures',self.actual_switch_source()+'''
#include <assert.h>
int main(void) {
    begin();
    for (uint32_t t=0;t<=8000;t+=10) step(t,0,0,0,.1f);
    assert(tightening_last_outcome==TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT && power_off==1);
    begin(); tightening_rundown.state=RUNDOWN_ARMED;
    tightening_test_stage=TIGHTEN_STATE_CONTACT_STOP;
    for (uint32_t t=0;t<=2000;t+=10) step(t,3,3,0,.15f);
    assert(tightening_last_outcome==TIGHTEN_OUTCOME_STOP_TIMEOUT);
    begin(); tightening_rundown.state=RUNDOWN_ARMED; tightening_contact_confirmed=1;
    tightening_test_stage=TIGHTEN_STATE_HOLD; step(100,31,31,0,.15f);
    assert(tightening_last_outcome==TIGHTEN_OUTCOME_ABORT && !ok_events);
}
''')

    def test_protected_no_rotation_uses_existing_atomic_session_stop(self):
        self.run_c('protected_stop',self.actual_switch_source(protected=True)+'''
#include <assert.h>
int main(void) {
    begin();
    for (uint32_t t=0;t<=1500;t+=10) step(t,0,0,0,.35f);
    assert(power_off==1 && foc_iq_ref_A==0);
    assert(tightening_test_stage==TIGHTEN_STATE_FAULT);
    assert(tightening_last_outcome==TIGHTEN_OUTCOME_NO_ROTATION);
    assert(!contact_seen && !iq_stages && !ok_events);
}
''')

    def test_sub_100ms_motion_or_short_high_demand_cannot_be_credited(self):
        self.run_c('intervals','''
#include <assert.h>
#include "tightening_rundown_guard.h"
int main(void) {
    TightenRundownGuard g={0};
    for (unsigned t=0;t<100;t+=10)
        TightenRundown_Update(&g,t,20,20,20,t*.12f,.2f,1);
    assert(!TightenRundown_CanContact(&g));
    TightenRundown_Update(&g,100,20,0,0,12,.2f,1);
    assert(!TightenRundown_CanContact(&g));
    for (unsigned t=110;t<=1600;t+=10) {
        float demand=t>=1450 ? .35f:.1f;
        assert(!TightenRundown_Update(&g,t,20,0,0,12,demand,1));
    }
    for (unsigned t=1610;t<1700;t+=10)
        assert(!TightenRundown_Update(&g,t,20,0,0,12,.35f,1));
    assert(TightenRundown_Update(&g,1700,20,0,0,12,.35f,1));
    TightenRundown_Begin(&g); assert(!TightenRundown_CanContact(&g));
}
''')

    def test_both_slots_identical_fsm_and_reset_before_start(self):
        texts=[(ROOT/f'foc2_app_{s}/Core/Src/main.c').read_text() for s in 'ab']
        blocks=[extract_braces(x,x.index('static void TighteningTask(void *argument)\n{')) for x in texts]
        self.assertEqual(*blocks)
        for text in texts:
            reset=extract_braces(text,text.index('static void TighteningRepeat_ResetCurrentCycle(void)\n{'))
            self.assertIn('TightenRundown_Begin',reset)
            self.assertIn('TIGHTEN_OUTCOME_NO_ROTATION',text)
            self.assertEqual(text.count('TIGHTEN_OUTCOME_OK;'),1)


if __name__=='__main__': unittest.main()

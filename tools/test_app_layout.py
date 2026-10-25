"""Focused offline suite for the App A layout change; never invokes board tools."""
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODULES=(
    'test_app_source_layout', 'test_tightening_intent_fsm',
    'test_current_pi_identified_candidate', 'test_current_protection_layers',
    'test_foc_adc_clock', 'test_foc_timeout_diagnostics',
    'test_speed_pi_anti_windup', 'test_speed_accel_feedforward',
    'test_speed_friction_compensation', 'test_speed_scurve',
    'test_foc_dq_decoupling', 'test_load_speed_contact_hold',
    'test_load_speed_scheduler', 'test_load_speed_host',
    'test_load_speed_contact_port', 'test_load_gain', 'test_load_gain_opt',
    'test_dob_saturation_continue', 'test_dob_source_gap',
)


def main():
    sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools')]
    output=ROOT/'tmp';output.mkdir(exist_ok=True)
    started=time.monotonic();rows=[]
    with (output/'app-layout-focused.log').open('w',encoding='utf-8') as stream:
        for module in MODULES:
            suite=unittest.TestLoader().loadTestsFromName(module)
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
            stream.flush()
            rows.append(dict(module=module,tests=result.testsRun,failures=len(result.failures),
                errors=len(result.errors),skipped=len(result.skipped),passed=result.wasSuccessful()))
            summary=dict(modules=rows,tests=sum(x['tests'] for x in rows),
                failures=sum(x['failures'] for x in rows),errors=sum(x['errors'] for x in rows),
                passed=all(x['passed'] for x in rows),seconds=time.monotonic()-started)
            (output/'app-layout-focused.json').write_text(json.dumps(summary,indent=2)+'\n')
            print(module,rows[-1],flush=True)
    return 0 if summary['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

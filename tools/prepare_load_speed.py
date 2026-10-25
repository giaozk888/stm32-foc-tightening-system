"""Build software-only load-speed scheduler DLL; never configures hardware."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import prepare_low_recovery as reviewed

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'simulation/dob_simulink/native'
COMMON = ROOT / 'firmware_common'
WORK = ROOT / 'simulation/dob_simulink/load_speed_work'
FLAGS = [x for x in reviewed.FLAGS if not x.startswith('DOB_FB_GAIN=')] + [
    'DOB_FB_GAIN=dob_host_gain', 'FOC_DOB_TREND_WINDOW75=1',
    'FOC_RUNDOWN240_CANDIDATE=1', 'FOC_INTENT_FSM_CANDIDATE=1',
    'FOC_PWM_COMMON_MODE_ENABLE=1', 'FOC_LOADED_FSM_TRIAL=1',
    'FOC_PWM_PIPELINE_CLOSED_LOOP=1', 'FOC_RUNDOWN240_TRAVEL20000=1']
EXTRA = ('base_target_rpm selected_target_rpm schedule_slow schedule_reason schedule_transitions '
         'schedule_high_us schedule_release_us load_level load_valid load_mean_a load_trend_state '
         'load_trend_valid load_trend_a_s fsm_state fsm_reason contact_pending contact_confirmed '
         'fsm_outcome rundown_armed rundown_peak_rpm contact_pending_ms control_mode iq_limit_a '
         'dob_gain schedule_enabled schedule_last_good_us reset_integrator contact_rpm '
         'contact_iq_ma contact_dwell_ms fsm_transitions').split()
BASE = ('speed_ref_rpm speed_meas_rpm accel_ref_rpm_s iq_pi_a iq_acc_ff_a iq_friction_a iq_raw_a '
        'iq_cmd_a speed_integrator_a iq_dob_a dob_estimate_a dob_valid dob_status abs_id_lpf_a '
        'id_lpf_before_a lpf_updated quality_reason admission_decision reset_count epoch_resets '
        'reset_reason warmup_s id_bad_us observer_age_us observer_source_us feedback_state adc_seq '
        'id_raw_a iq_meas_a simulation_guard_fault travel_deg observer_omega_rad_s iq_matched_a').split()
INPUT = ('target_rpm omega_true_rad_s iq_true_a speed_noise_rpm iq_noise_a id_meas_a current_valid '
         'voltage_sat encoder_age_us running schedule_enable position_deg direction fixture_truth stop protection_fault').split()


def build():
    from app_a_source_layout import app_source_files
    WORK.mkdir(exist_ok=True)
    sources = [NATIVE / 'load_speed_host.c', COMMON / 'mechanical_dob_monitor.c',
               COMMON / 'speed_scurve.c', COMMON / 'speed_accel_feedforward.c',
               COMMON / 'speed_friction_compensation.c', COMMON / 'tightening_intent_fsm.c',
               COMMON / 'dob_trend_shadow.c', COMMON / 'tighten_params.cpp']
    objects = []
    for source in sources:
        obj = WORK / (source.name + '.o'); objects.append(obj)
        compiler = reviewed.GCC.with_name('g++.exe') if source.suffix == '.cpp' else reviewed.GCC
        command = [str(compiler), '-std=c++17' if source.suffix == '.cpp' else '-std=c11',
                   '-O2', '-Wall', '-Wextra', '-Werror', '-include', str(NATIVE / 'host_compat.h'),
                   '-I', str(COMMON), '-I', str(NATIVE), *['-D' + x for x in FLAGS], '-c', str(source), '-o', str(obj)]
        p = subprocess.run(command, capture_output=True, text=True)
        if p.returncode: raise RuntimeError(p.stderr)
    dll = WORK / 'load_speed_host.dll'
    subprocess.run([str(reviewed.GCC.with_name('g++.exe')), '-shared', *map(str, objects), '-lm', '-o', str(dll)], check=True)
    files = sources + [NATIVE / 'dob_host.c', NATIVE / 'load_speed_scheduler.h', NATIVE / 'load_speed_plant_sfun.c',
                       ROOT / 'foc2_app_a/Core/Src/main.c', ROOT / 'foc2_app_b/Core/Src/main.c']
    files += [p for p in app_source_files() if p not in files]
    files += list(COMMON.glob('*.h'))
    files += [NATIVE / 'dob_controller_sfun.c', Path(__file__)]
    files += [ROOT / 'simulation/dob_simulink' / name for name in
              ('build_load_speed.m', 'load_speed_inputs.m', 'run_load_speed.m')]
    files += list((ROOT / 'foc2_app_a').glob('CMake*')) + list((ROOT / 'foc2_app_b').glob('CMake*'))
    schema = dict(output_names=BASE + EXTRA, input_names=INPUT, flags=FLAGS, dll=str(dll),
                  stop_s=10, dt=.001, pwm_dt=.00005, seeds=[1,2,3,4,5,61,62,63,64,65],
                  plant=[.000386049,.00155158,.11945168237076952,.0005496600325149542,.001],
                  schedule=dict(slow_target_rpm=120, high_dwell_ms=30, release_dwell_ms=200,
                                minimum_slow_ms=300, invalid_fallback_ms=200, phase='RUNDOWN only'),
                  sources=[dict(path=str(x), sha256=hashlib.sha256(x.read_bytes()).hexdigest()) for x in files if x.is_file()],
                  hardware_access=False, physical_performance_validated=False)
    assert len(BASE + EXTRA) == 64 and len(INPUT) == 16
    (WORK / 'manifest.json').write_text(json.dumps(schema, indent=2) + '\n')
    print('BUILT software-only scheduler, original C controller/classifier/FSM,64 outputs')


if __name__ == '__main__': build()

"""One supervised +600 rpm DOB SHADOW test. FILES ONLY by default.

No observer feedback, parameter changes, retries or automatic negative test.
Retains original A-only stage, calibration, timing/stack preflight, safe
shutdown and preserved-B restoration. Fresh physical OFF/ON gates required.
"""
import json
from pathlib import Path
import sys
import time
import mechanical_reverse_batch as previous
import mechanical_dob_report as dob_report

low = previous.low
ROOT_RESTORE = low.TMP/'mechanical-ident-restore-1792713878339933000.json'
IMAGE = low.base.old.ROOT/'foc2_app_a/build/MechanicalDobShadowCandidate/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '74d53cf4e47743ccfa8bfbe5ca73ed4d58dcc0332ca59b785bfe8b54bb84e770'
ELF_SHA = '6ab8d8f68708e9b65dec79a8bac3a1319080068f506823d7586bb3dd63003654'
SIZE = 213620
POINTS = (600,)
ORIGINAL_SETUP = previous.setup
ORIGINAL_RUN = previous.ORIGINAL_RUN
# ReadinessBoard, NOT ReverseBoard (whose exact negative whitelist is frozen).
ORIGINAL_BOARD = previous.ORIGINAL_BOARD
ORIGINAL_STAGED = previous.ORIGINAL_STAGED
MODEL = dict(SHADOW='1', FEEDBACK='0', J_NA_S2_RAD='378290', B_NA_S_RAD='1567686',
             IC_UA='119451', BIAS_UA='549', BW_MRAD_S='12566', MIN_W_MRAD_S='2094')


def image():
    data = previous.previous.previous.previous.validate_image(IMAGE, ELF, SHA, ELF_SHA, SIZE,
        extra_flags=('FOC_OUTER_OBSERVE_AFTER_ACK=1', 'FOC_READY_TIMESTAMP_SNAPSHOT=1',
                     'FOC_MECHANICAL_DOB_SHADOW=1'),
        extra_markers=(b'OBS_AFTER_ACK=1', b'OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX',
                       b'DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
                       b'OK DOB MODEL SHADOW=1 FEEDBACK=0', b'OK DOB STATS SHADOW=1 FEEDBACK=0'))
    symbols = low.base.symbols(ELF)
    for key, size in (('outer_completion_trace', 644), ('cl_ready_check', 20),
                      ('cl_ready_reject', 32), ('cl_ready_attempts', 4),
                      ('mechanical_dob_monitor', dob_report.SIZE),
                      ('mechanical_dob_identified_model', 28)):
        if symbols.get(key, (0, 0))[1] != size:
            raise ValueError('DOB / timing ABI mismatch: '+key)
    cmd = next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
               if c['file'].endswith('/Core/Src/main.c'))
    if '-DFOC_MECHANICAL_REVERSE_IDENT_DIAG' in cmd:
        raise ValueError('Not the isolated DOB observer profile')
    return data


def check_values(reply, expected, label):
    values = low.base.hw.fields(reply)
    if any(values.get(k) != v for k, v in expected.items()):
        raise RuntimeError(label+' identity absent; no motion / no retry')
    return values


class DobBoard(ORIGINAL_BOARD):
    def command(self, command, timeout=2):
        if command.startswith('MOTOR TEST MECH RUN '):
            if command != 'MOTOR TEST MECH RUN POS 600':
                raise ValueError('Only one explicit +600 rpm shadow test; no motion')
            identity = super().command('MOTOR TEST MECH DIRECTION', .8)
            self.record['dob_direction'] = check_values(identity,
                dict(DOB_SHADOW='1', SIGNS='POS,NEG', GRID_RPM='600', DOB_CONTROL='0'), 'DOB')
            model = super().command('MOTOR TEST MECH DOB MODEL', .8)
            self.record['dob_model_before_start'] = check_values(model, MODEL, 'DOB model')
            self.record['dob_before_start'] = check_values(
                super().command('MOTOR TEST MECH DOB', .8),
                dict(SHADOW='1', FEEDBACK='0', LIVE='0', VALID='0'), 'DOB rest')
            reply = super().command(command, timeout)  # Existing readiness check and one RUN.
            self.dob_started = True
            self.dob_next = 0.
            return reply
        reply = super().command(command, timeout)
        if (command == 'MOTOR TEST MECH STATUS' and getattr(self, 'dob_started', False)
                and time.monotonic() >= self.dob_next):
            views = {}
            for suffix, key in (('', 'frame'), (' ADC', 'adc'), (' STATS', 'stats')):
                response = super().command('MOTOR TEST MECH DOB'+suffix, .8)
                values = check_values(response, dict(SHADOW='1', FEEDBACK='0'), 'DOB readonly')
                views[key] = dict(reply=response, values=values)
            self.record.setdefault('dob_samples', []).append(dict(at=time.monotonic(), **views))
            self.dob_next = time.monotonic()+.25
        return reply


def run_point(row, *args):
    try:
        ORIGINAL_RUN(row, *args)
        # ORIGINAL_RUN checkpoints the actual same-session hashes and closure
        # before this files-only observer decode. Never bypass board acceptance.
        row['dob_capture'] = dob_report.decode(Path(row['receipt_path']), ELF)
        meta = row['dob_capture']['meta']
        row['dob_summary'] = dict(valid_samples=meta['valid_samples'],
            observations=meta['observations'], rejected_samples=meta['rejected_samples'],
            valid_fraction=meta['valid_samples']/meta['observations'] if meta['observations'] else 0.,
            mean_positive_a=row['dob_capture']['positive_mean_a'],
            max_abs_disturbance_a=meta['disturbance_abs_peak'], max_compute_us=meta['max_compute_us'],
            observation_available=meta['valid_samples'] > 0, feedback_enabled=False,
            closed_loop_dob_effect_tested=False, model_reidentified=False)
    finally:
        if row.get('ram_capture'):
            row['outer_completion_trace'] = previous.previous.previous.decode_trace(row, elf=ELF, elf_sha=ELF_SHA)
            row['readiness_capture'] = previous.previous.decode_readiness(row, elf=ELF, elf_sha=ELF_SHA)


def staged(path, data):
    source, raw = ORIGINAL_STAGED(path, data)
    r = json.loads(path.read_text())
    if (r.get('speeds_rpm') != list(POINTS) or r.get('ka_a_per_rpm_s') != low.KA or
            r.get('overspeed_trip_rpm') != 1000 or r.get('travel_limit_deg') != 30000 or
            r.get('activation') is not False or r.get('motor_commands') != 0 or
            r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True):
        raise ValueError('Exact single-point DOB SHADOW OFF stage required')
    return source, raw


def setup(path):
    # First prove the ACTUAL reverse-image B1039 restore under its old identity.
    ORIGINAL_SETUP(ROOT_RESTORE)
    low.base.baseline()
    low.IMAGE, low.ELF, low.SHA, low.ELF_SHA, low.SIZE = IMAGE, ELF, SHA, ELF_SHA, SIZE
    low.image, low.run_point, low.MechanicalBoard = image, run_point, DobBoard
    low.base.staged = staged
    for obj in (low.base, low.previous.gain, low.fitted):
        obj.IMAGE, obj.ELF, obj.SHA, obj.ELF_SHA = IMAGE, ELF, SHA, ELF_SHA
        obj.image = image
    low.previous.gain.SIZE = low.fitted.SIZE = SIZE
    if path.resolve() != ROOT_RESTORE.resolve():
        low.base.configure_baseline(path)
    return image()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--execute-positive' in args:
        args[args.index('--execute-positive')] = '--execute-six'
    if '--baseline-restore' not in args and not any(x in args for x in ('--execute-six', '--restore-b-drive-off')):
        args += ['--baseline-restore', str(ROOT_RESTORE)]
    low.setup, low.POINTS = setup, POINTS
    low.TRIP_RPM, low.TRAVEL_DEG, low.CLOSURE_SECONDS, low.LIMITS_QUERY = 1000, 30000, 11., True
    low.LIMITS_EXTRA = dict(PLAUSIBLE_RPM='1000', REJECT_BUSY='1', OBS_AFTER_ACK='1')
    return low.main(args)


if __name__ == '__main__':
    raise SystemExit(main())

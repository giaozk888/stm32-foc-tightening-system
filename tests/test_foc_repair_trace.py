"""Repair fault evidence: production C, mocked binding and linked hard-off ELF."""
import hashlib
import json
import subprocess
import unittest

import test_zero_all_rejected_compact as prior
import foc_repair_window_capture as capture
import foc_repair_window_board_test as board

ROOT, COMMON = prior.ROOT, prior.COMMON
FLAGS = prior.FLAGS + ['-DFOC_REPAIR_WINDOW_TRACE=1']
PRESET = 'RepairWindowDiagnostic'
PINS = dict(a='9dff17fff93046487193fb23c6c07aef1940e4e715b0df0b85b3747961a754d1',
            b='b4a0b545e3eead8cf19375dd3e114bbf56c0c842b7309fc58f424e1f92f5a0dd')


def host(name, source, flags=FLAGS, opt='-O2'):
    try:
        return prior.compact.host('repair_trace_' + name,
            [ROOT / 'tests' / source, *prior.SOURCES, COMMON / 'foc_repair_trace.c'], flags, opt=opt)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr or error.stdout) from error


class RepairTraceTests(unittest.TestCase):
    def test_ring_pack_freeze_causes_and_format(self):
        for opt in ('-Os', '-O2'):
            self.assertIn('PASS', host('ring_' + opt, 'foc_repair_trace_host.c', opt=opt))

    def test_actual_fault_window_and_immutable_binding(self):
        for opt in ('-Os', '-O2'):
            text = host('binding_' + opt, 'foc_repair_binding_host.c', opt=opt)
            self.assertIn('PASS actual repair fault', text)
            lines = text.splitlines()
            summary = capture.base.fields(lines[0])
            rows = [capture.base.fields(line) for line in lines[1:33]]
            result = capture.validate(summary, rows)
            self.assertEqual((result['cause'], result['window_hits'], result['consecutive']), ('WINDOW', 7, 1))
            self.assertFalse(result['motor_acceptance'])
            for field, value in (('GAP', '1'), ('HITS', '6'), ('WIN', '0x0'), ('STREAK', '2'),
                                 ('FROZEN', '0'), ('REASON', '3'), ('CAUSE', '2')):
                with self.assertRaises(ValueError):
                    capture.validate(dict(summary, **{field: value}), rows)
            with self.assertRaises(ValueError):
                capture.validate(summary, rows[:-1])
            wrong = [dict(r) for r in rows]
            wrong[5]['SRC'] = '0'
            with self.assertRaises(ValueError):
                capture.validate(summary, wrong)

    def test_capture_is_read_only_and_preserves_partial_evidence(self):
        class Fake:
            READ = capture.Console.READ
            def __init__(self):
                self.commands = []
            def query(self, command):
                self.commands.append(command)
                return 'OK REPAIR ENABLED=1 HARD_OFF=1 N=32 FROZEN=0'
        fake, evidence = Fake(), {}
        with self.assertRaises(ValueError):
            capture.collect(fake, evidence)
        self.assertIn('summary_line', evidence)
        self.assertEqual(fake.commands, ['MOTOR TEST REPAIR'])
        for command in ('START', 'FW END', 'ANALOG SAFE', 'RESET', 'MOTOR TEST SPEED',
                        'MOTOR TEST REPAIR ROW 32', 'MOTOR TEST REPAIR ROW -1'):
            with self.assertRaises(ValueError):
                capture.Console.query(fake, command)

    def test_board_image_and_scoped_commands(self):
        image = board.pinned_image()
        self.assertEqual(len(image), 209820)
        folder = ROOT / 'safety_backups/protected-closed-loop-20261014/private'
        commands = board.stage_commands(folder/'live.bin', folder/'prior.bin', folder/'staged.bin')
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].endswith(' 0x08008000 bin'))
        self.assertNotIn('reset run', commands)
        self.assertNotIn('resume', commands)
        trial = board.trial_commands(folder/'live.bin', folder/'prior.bin')
        self.assertEqual(trial.count('reset run'), 1)
        self.assertFalse(any(c.startswith('flash ') for c in trial))
        self.assertFalse(any(c.startswith('mww 0x080') for c in trial))
        self.assertEqual(board.META[2:6], (2, 1, 1, 555))

    def test_original_guardian_and_adc_decisions_unchanged(self):
        for opt in ('-Os', '-O2'):
            self.assertEqual(prior.host('repair_guard_ref_' + opt, 'foc_compact_guard_host.c', prior.FLAGS, opt),
                             host('guard_' + opt, 'foc_compact_guard_host.c', opt=opt))
        self.assertIn('PASS', host('adc', 'protected_adc_irq_host.c'))
        self.assertIn('PASS', host('locked', 'foc_adaptive_binding_host.c'))

    def test_formal_or_incomplete_profiles_rejected(self):
        for flags in ([f for f in FLAGS if f != '-DFOC_ZERO_ALL_REJECTED_DIAG=1'],
                      FLAGS + ['-DFOC_LATEST_ORIGINAL_FSM=1'], FLAGS + ['-DFOC_COMPACT_CLOSED_LOOP=1']):
            p = subprocess.run([str(prior.compact.GCC), '-std=c11', '-fsyntax-only', '-I', str(COMMON),
                                *flags, str(COMMON / 'foc_repair_trace.c')], capture_output=True)
            self.assertNotEqual(p.returncode, 0)

    def test_only_after_output_closure_and_separate_artifacts(self):
        binding = (COMMON / 'protected_closed_loop.inc').read_text('utf-8')
        emergency = binding[binding.index('void ProtectedLoop_EmergencyOff'):binding.index('static void ProtectedLoop_Stop')]
        self.assertLess(emergency.index('FocFeedbackGuard_OutputOff'), emergency.index('FocRepairTrace_Freeze'))
        for slot in 'ab':
            base = ROOT / f'foc2_app_{slot}'
            self.assertEqual(hashlib.sha256((base / 'build/ZeroAllRejectedCompact/foc2.bin').read_bytes()).hexdigest(), PINS[slot])
            presets = json.loads((base / 'CMakePresets.json').read_text('utf-8'))
            p = next(x for x in presets['configurePresets'] if x['name'] == PRESET)
            self.assertEqual(p['inherits'], 'ZeroAllRejectedCompact')
            self.assertEqual(p['cacheVariables'], {'FOC_REPAIR_WINDOW_TRACE': 'ON'})
            data = (base / f'build/{PRESET}/foc2.bin').read_bytes()
            for identity in (b'OK REPAIR ENABLED=1 HARD_OFF=1 N=32', b'MOTOR TEST REPAIR ROW ',
                             b'COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50'):
                self.assertIn(identity, data)
            self.assertLessEqual(len(data), 224 * 1024)


if __name__ == '__main__':
    unittest.main()

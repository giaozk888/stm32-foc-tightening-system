"""No-device regression tests for the automatic-confirmation reset window."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import encoder_health_board_test as board
from health_confirmation_wait import StartupFault, wait_health_confirmation


FW = dict(CURRENT='A', CONFIRMED='A', PENDING='-', ATTEMPTS='0', ACTIVE='0', GEN='610')
TRIAL = dict(FW, CONFIRMED='B', PENDING='A', ATTEMPTS='1', GEN='609')
READY = dict(STATE='1', ZERO='3', SD='0', MOE='0', CCER='0', FLAGS='0', FAULT='0')
ROLLBACK = dict(FW, CURRENT='B', CONFIRMED='B')


def fw(value=FW):
    return ('FW STATUS', value)


def state(value=READY):
    return ('MOTOR TEST STATUS', value)


def wire(value):
    return '15001 OK ' + ' '.join(f'{key}={item}' for key, item in value.items())


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeConsole:
    def __init__(self, clock, events=(), always_timeout=False):
        self.clock = clock
        self.events = list(events)
        self.always_timeout = always_timeout
        self.commands = []
        self.timeouts = []
        self.lines = []
        self.starts = self.ends = 0

    def query(self, command, timeout):
        self.commands.append(command)
        self.timeouts.append(timeout)
        if command not in ('FW STATUS', 'MOTOR TEST STATUS'):
            raise AssertionError('Wait attempted a non-read command: ' + command)
        if self.always_timeout:
            result = TimeoutError('reset silence')
        else:
            if not self.events:
                raise AssertionError('Unexpected extra query: ' + command)
            expected, result = self.events.pop(0)
            if expected != command:
                raise AssertionError((expected, command))
        self.clock.now += timeout if isinstance(result, TimeoutError) else .001
        if isinstance(result, BaseException):
            raise result
        return wire(result)

    def poll(self, timeout):
        self.clock.now += timeout


class ConfirmationWaitTests(unittest.TestCase):
    def run_wait(self, events, timeout=60):
        clock = Clock()
        uart = FakeConsole(clock, events)
        row = {}
        wait_health_confirmation(uart, row, board.base.prior.fields,
                                 timeout=timeout, clock=clock)
        self.assertFalse(uart.events)
        self.assertEqual(set(uart.commands), {'FW STATUS', 'MOTOR TEST STATUS'})
        return row, uart, clock

    def test_normal_confirmed_ready_requires_fresh_fw_recheck(self):
        row, uart, _ = self.run_wait([fw(), state(), fw()])
        self.assertTrue(row['normally_confirmed'])
        self.assertEqual(row['health_wait']['confirmed_generation'], '610')
        self.assertEqual(uart.commands, ['FW STATUS', 'MOTOR TEST STATUS', 'FW STATUS'])

    def test_reset_between_fw_and_state_is_recoverable(self):
        row, _, _ = self.run_wait([
            fw(TRIAL), state(TimeoutError('No ACK, never resend: MOTOR TEST STATUS')),
            fw(TimeoutError('bootloader')), fw(), state(), fw()])
        self.assertEqual(row['health_wait']['read_timeout_count'], 2)
        self.assertEqual(row['health_wait']['state_timeout_count'], 1)
        self.assertEqual(row['health_wait']['fw_timeout_count'], 1)
        self.assertTrue(row['normally_confirmed'])

    def test_confirmation_recheck_can_overlap_reset_too(self):
        row, _, _ = self.run_wait([
            fw(), state(), fw(TimeoutError('reset')), fw(), state(), fw()])
        self.assertTrue(row['health_wait']['confirmed'])
        self.assertEqual(row['health_wait']['fw_timeout_count'], 1)

    def test_initial_silence_and_calibration_do_not_start_observation(self):
        row, _, _ = self.run_wait([
            fw(TimeoutError('initial boot')), fw(TRIAL), state(dict(READY, STATE='0', ZERO='1')),
            fw(), state(dict(READY, ZERO='1')), fw(), state(), fw()])
        self.assertTrue(row['normally_confirmed'])

    def test_mixed_generations_are_not_accepted(self):
        next_fw = dict(FW, GEN='611')
        row, _, _ = self.run_wait([fw(), state(), fw(next_fw), fw(next_fw), state(), fw(next_fw)])
        self.assertEqual(row['health_wait']['generation_rechecks'], 1)
        self.assertEqual(row['health_wait']['confirmed_generation'], '611')

    def test_incomplete_confirmation_is_not_success(self):
        for broken in (dict(FW, ACTIVE='1'), dict(FW, ATTEMPTS='1'),
                       dict(FW, PENDING='A'), dict(FW, CONFIRMED='B'),
                       {k: v for k, v in FW.items() if k != 'GEN'}):
            with self.subTest(fw=broken):
                row, _, _ = self.run_wait([fw(broken), state(), fw(), state(), fw()])
                self.assertTrue(row['normally_confirmed'])

    def test_rollback_before_or_after_state_fails_without_retry(self):
        for events in ([fw(ROLLBACK)], [fw(), state(), fw(ROLLBACK)]):
            clock = Clock()
            uart = FakeConsole(clock, events)
            row = {}
            with self.assertRaisesRegex(RuntimeError, 'rolled back'):
                wait_health_confirmation(uart, row, board.base.prior.fields, clock=clock)
            self.assertFalse(uart.events)
            self.assertNotIn('normally_confirmed', row)

    def test_reported_fault_is_not_swallowed_as_a_reboot(self):
        clock = Clock()
        uart = FakeConsole(clock, [fw(TRIAL), state(dict(READY, STATE='4', FAULT='8'))])
        row = {}
        with self.assertRaises(StartupFault):
            wait_health_confirmation(uart, row, board.base.prior.fields, clock=clock)
        self.assertEqual(row['last_state']['FAULT'], '8')
        self.assertEqual(row['health_wait']['read_timeout_count'], 0)

    def test_unsafe_or_faulted_state_is_not_confirmation(self):
        for key in ('SD', 'MOE', 'CCER', 'FLAGS', 'FAULT'):
            with self.subTest(key=key):
                clock = Clock()
                uart = FakeConsole(clock, [fw(), state(dict(READY, **{key: '1'}))])
                with self.assertRaisesRegex(RuntimeError, 'not locked'):
                    wait_health_confirmation(uart, {}, board.base.prior.fields, clock=clock)

    def test_permanent_silence_has_one_absolute_deadline(self):
        clock = Clock()
        uart = FakeConsole(clock, always_timeout=True)
        row = {'normally_confirmed': True}
        with self.assertRaisesRegex(TimeoutError, 'startup deadline'):
            wait_health_confirmation(uart, row, board.base.prior.fields, timeout=2, clock=clock)
        self.assertAlmostEqual(clock.now, 2)
        self.assertTrue(all(0 < budget <= .6 for budget in uart.timeouts))
        self.assertLessEqual(len(uart.commands), 4)
        self.assertNotIn('normally_confirmed', row)
        self.assertFalse(row['health_wait']['confirmed'])

    def test_non_timeout_protocol_error_is_fatal(self):
        clock = Clock()
        uart = FakeConsole(clock, [fw(RuntimeError('invalid ACK'))])
        with self.assertRaisesRegex(RuntimeError, 'invalid ACK'):
            wait_health_confirmation(uart, {}, board.base.prior.fields, clock=clock)

    def test_reply_past_deadline_is_not_accepted(self):
        clock = Clock()
        uart = FakeConsole(clock, [fw()])
        row = {}
        with self.assertRaises(TimeoutError):
            wait_health_confirmation(uart, row, board.base.prior.fields, timeout=.0001, clock=clock)
        self.assertNotIn('normally_confirmed', row)

    def test_confirmation_is_not_inferred_from_boot_logs(self):
        clock = Clock()
        uart = FakeConsole(clock, always_timeout=True)
        uart.lines = ['BOOT HEALTH: PASS 5s', 'CONFIRM REQUESTED SLOT=A -> RESETTING']
        with self.assertRaises(TimeoutError):
            wait_health_confirmation(uart, {}, board.base.prior.fields, timeout=.1, clock=clock)

    def test_wrapper_preserves_fault_capture_and_does_not_retry_it(self):
        uart = SimpleNamespace()
        row = {}
        with patch.object(board, 'wait_health_confirmation', side_effect=StartupFault('fault')) as wait, \
             patch.object(board.base.prior, 'sample', side_effect=TimeoutError('fault capture unavailable')) as sample:
            with self.assertRaisesRegex(TimeoutError, 'fault capture unavailable'):
                board.wait_confirmation(uart, row)
        wait.assert_called_once()
        sample.assert_called_once_with(uart)

    def exercise_trial_failure(self, wait_error=None):
        # Exercise the actual trial transaction and finally block, mocking ALL
        # device/file calls. A post-confirmation collection failure stays fatal.
        base = board.base
        uart = SimpleNamespace(lines=[], starts=0, ends=0)
        uart.query = lambda command, timeout: 'off' if command == 'ANALOG SAFE' else None
        port = SimpleNamespace(is_open=True)
        port.close = lambda: setattr(port, 'is_open', False)
        row = {'samples': []}
        def waited(console, result):
            if wait_error is not None:
                raise wait_error
            result['normally_confirmed'] = True
        with patch.object(base.tx, 'load_stage', return_value=(Path('unused'), b'before')), \
             patch.object(base.prior, 'open_port', return_value=port), \
             patch.object(base.prior, 'Console', return_value=uart), \
             patch.object(base.prior, 'debug') as debug, \
             patch.object(base.prior, 'full_compare_commands', return_value=[]), \
             patch.object(base.prior, 'write_mailbox', return_value=['mailbox-once']) as mailbox, \
             patch.object(base.tx, 'mailbox', return_value=()), \
             patch.object(base, 'wait_confirmation', side_effect=waited) as wait, \
             patch.object(base.prior, 'sample', side_effect=TimeoutError('runtime read failed')) as sample, \
             patch.object(base.prior, 'emergency_off') as off, \
             patch.object(Path, 'read_bytes', return_value=b'final'), \
             patch.object(base.tx, 'compare_final', return_value=(1, 2, 3)):
            error_type = type(wait_error) if wait_error is not None else TimeoutError
            error_text = str(wait_error) if wait_error is not None else 'runtime read failed'
            with self.assertRaisesRegex(error_type, error_text):
                base.trial(row, 'offline-only', b'image', Path('unused.json'))
        self.assertEqual(row['trial_requests'], 1)
        self.assertTrue(row['activation_submitted'])
        self.assertEqual(sum(c == 'reset run' for call in debug.call_args_list
                             for c in call.args[1]), 1)
        mailbox.assert_called_once()
        wait.assert_called_once()
        self.assertEqual(sample.call_count, 0 if wait_error is not None else 1)
        off.assert_called_once()
        self.assertFalse(port.is_open)
        self.assertEqual(row['host_motor_commands'], 0)
        self.assertEqual(row['host_uart_trial_commits'], 0)

    def test_trial_runtime_timeout_still_cleans_up_without_reactivation(self):
        self.exercise_trial_failure()

    def test_trial_wait_timeout_still_cleans_up_without_reactivation(self):
        self.exercise_trial_failure(TimeoutError('startup deadline'))

    def test_trial_rollback_still_cleans_up_without_reactivation(self):
        self.exercise_trial_failure(RuntimeError('rolled back'))


if __name__ == '__main__':
    unittest.main()

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import current_pi_board_preflight as preflight


class PiPreflightTests(unittest.TestCase):
    def test_files_only_validates_pins_and_no_device_access(self):
        with patch.object(preflight.base.hw,'debug',side_effect=AssertionError('device')):
            self.assertEqual(preflight.main([]),0)

    def test_missing_power_state_never_opens_device(self):
        with patch.object(preflight.base.hw,'debug',side_effect=AssertionError('device')):
            for args in (['--stage-off'],['--execute-powered','tmp/not-used.json']):
                with self.assertRaises(SystemExit):preflight.main(args)

    def test_profile_must_be_compiled_hard_off(self):
        self.assertEqual(preflight.profile('1 OK MOTOR TEST PROFILE NAME=FAST_CURRENT_REJECT HARD_OFF=1 FSM=ORIGINAL')['HARD_OFF'],'1')
        with self.assertRaises(RuntimeError):
            preflight.profile('1 OK MOTOR TEST PROFILE NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL')

    def test_missing_or_bad_same_run_evidence_fails(self):
        good=dict(preflight_pass=True,outputs={'VTOR':0x08008000},snapshot=dict(first_fault={'valid':0},
            cur_confirm={'fault':0},timing=dict(wall_max_us=30.,deadline_miss=0,actual_late_count=0,
                actual_margin_min_us=10.,actual_commit_count=120000)))
        preflight.accept_snapshot(good);self.assertTrue(good['pass_'])
        for key,value in (('wall_max_us',51.),('actual_late_count',1),('deadline_miss',1),('actual_margin_min_us',0)):
            bad=copy.deepcopy(good);bad['snapshot']['timing'][key]=value
            with self.assertRaises(RuntimeError):preflight.accept_snapshot(bad)
        with self.assertRaises(RuntimeError):preflight.accept_snapshot({})

    def test_actual_saved_zero_reply_uses_fixture_abi_not_robust_counters(self):
        import json
        path=Path(__file__).resolve().parents[1]/'tmp/current-pi-hard-off-run-1792565379314959400.json'
        row=json.loads(path.read_text())
        line=next(s for s in reversed(row['startup_uart']) if ' OK MOTOR TEST ZERO ' in s)
        out=preflight.zero_report(line)
        self.assertEqual(out['schema'],'LEGACY_MEDIAN_ZERO_REPORT')
        self.assertEqual(out['fields']['U0'],'1561');self.assertEqual(out['fields']['V0'],'1563')
        self.assertEqual(out['fields']['RAW_STATE'],'4')
        self.assertNotIn('valid',out['fields'])
        for broken in (line.replace('STATE=3','STATE=4',1),line.replace('N=4000','N=3000'),
                       line.replace('REASON=0','REASON=2',1),line.replace('U0=1561','U0=6000')):
            with self.assertRaises(ValueError):preflight.zero_report(broken)

    def test_cleanup_uses_allowed_stop_and_attempts_safe_after_stop_error(self):
        from unittest.mock import Mock
        uart=Mock(spec=preflight.base.TokenConsole)
        uart.query.side_effect=[TimeoutError('lost'),'2 OK ANALOG SAFE']
        row={};preflight.cleanup_uart(uart,row)
        self.assertEqual([c.args[0] for c in uart.query.call_args_list],['STOP','ANALOG SAFE'])
        self.assertEqual(row['safe_ack'],'2 OK ANALOG SAFE');self.assertIn('lost',row['stop_error'])

    def test_ram_timing_alone_cannot_upgrade_incomplete_preflight(self):
        row=dict(outputs={'VTOR':0x08008000},snapshot=dict(first_fault={'valid':0},
            timing=dict(wall_max_us=30.,deadline_miss=0,actual_late_count=0,actual_margin_min_us=10.)))
        with self.assertRaises(RuntimeError):preflight.accept_snapshot(row)

    def test_cleanup_against_actual_console_query_not_mock_invented_api(self):
        class Port:
            def __init__(self):self.sent=[];self.lines=[]
            def write(self,data):
                self.sent.append(data)
                self.lines.append(data.decode().split()[0]+' OK STOPPED')
        uart=object.__new__(preflight.base.TokenConsole)
        uart.request=0;uart.port=Port()
        uart.read_line=lambda seconds:uart.port.lines.pop(0) if uart.port.lines else None
        uart.dispatch=lambda line:None
        row={};preflight.cleanup_uart(uart,row)
        self.assertNotIn('stop_error',row)
        self.assertEqual(uart.port.sent,[b'1 STOP\r\n',b'2 ANALOG SAFE\r\n'])

    def test_ready_observation_without_optional_monitor_lines(self):
        class Clock:
            value=0.
            def __call__(self):return self.value
        clock=Clock()
        class UART:
            lines=[]
            def poll(self,seconds):clock.value+=seconds
            def query(self,cmd,timeout):
                return ('1 OK STATE=1 USED=0 QUEUED=0 ARMED=1 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0')
        row={};preflight.wait_ready_window(UART(),row,clock)
        self.assertGreaterEqual(len(row['ready_observation']),8)
        self.assertIn('RAM_TIMING',row['preflight_basis'])
        self.assertNotIn('preflight_pass',row)
        for field in ('FAULT','FLAGS','SD','MOE','CCER'):
            with self.assertRaises(RuntimeError):
                preflight.ready_state(UART().query('',0).replace(field+'=0',field+'=1'))

    def test_saved_timing_observations_remain_failed_original_run(self):
        import json
        root=Path(__file__).resolve().parents[1]
        row=json.loads((root/'tmp/current-pi-hard-off-run-1792565813793821900.json').read_text())
        self.assertFalse(row['pass_'])
        with self.assertRaises(RuntimeError):preflight.accept_snapshot(row)

    def test_host_has_no_motion_or_fault_clear_commands(self):
        import inspect
        src=inspect.getsource(preflight.execute)
        for forbidden in ("'START'",'MOTOR TEST IDENT RS','MOTOR TEST TORQUE','CLEAR','CONFIRM_CURRENT'):
            self.assertNotIn(forbidden,src)


if __name__=='__main__':unittest.main()

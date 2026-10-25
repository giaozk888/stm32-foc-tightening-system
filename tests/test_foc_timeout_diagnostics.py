"""Offline only. Never imports a board runner or opens hardware."""

from app_source_view import read_app_source
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path
import test_foc_fast_current_reject as fast

ROOT=Path(__file__).resolve().parents[1]

class TimeoutDiagnostics(unittest.TestCase):
    def test_actual_snapshot_binding_and_boundaries(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('timeout_diagnostics'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,
                ROOT/'tests/foc_timeout_snapshot_host.c',fast.COMMON/'foc_current_zero.c',
                fast.COMMON/'foc_zero_median.c',fast.COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('snapshot=204 bytes',fast.run(exe))

    def test_fault_path_has_no_log_heap_or_loop(self):
        src=(fast.COMMON/'foc_fault_snapshot.inc').read_text('utf-8')
        capture=src.split('static void FaultDiag_Capture',1)[1].split('static void FaultDiag_Clear',1)[0]
        code=re.sub(r'/\*.*?\*/','',capture,flags=re.S)
        self.assertNotRegex(code,r'\b(?:printf|UART_\w+|malloc|free|for|while)\s*\(')
        self.assertLess(code.index('__DMB()'),code.index('s->valid=1U'))

    def test_discriminator_frozen(self):
        # Frozen at the start of this diagnostics-only change.
        digest=hashlib.sha256((fast.COMMON/'foc_current_fast_reject.h').read_bytes()).hexdigest()
        self.assertEqual(digest,'a77bf47b2fb3082bf331b0c54782488e253b644cb0f289f4c94b47150288275d')

    def test_timeout_limits_not_relaxed(self):
        main=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c','utf-8')
        for name,value in (('RUN_ZERO_TIMEOUT_MS','1500U'),('PREFLIGHT_CHAIN_MAX_STALE_MS','(50U)'),
                           ('TIGHTEN_RUNDOWN_TIMEOUT_MS','8000U'),('TIGHTEN_STOP_TIMEOUT_MS','2000U'),
                           ('STALL_TIMEOUT_S','1.5f'),('MOTOR_SPEED_STALL_TIMEOUT_S','2.0f')):
            self.assertRegex(main,r'#define\s+'+name+r'\s+'+re.escape(value))
        enc=(fast.COMMON/'as5047p_timing_policy.h').read_text('utf-8')
        for name,value in (('AS_DMA_TRANSACTION_US',200),('AS_DMA_SAMPLE_MAX_AGE_US',1500),
                           ('AS_DMA_CONTROL_WATCHDOG_US',2500),('AS_DMA_PERIOD_US',1000)):
            self.assertRegex(enc,r'#define\s+'+name+r'\s+'+str(value)+'U')
        for file in ('protected_closed_loop.inc','foc_feedback_binding_stm32.inc','bridge_feedback_filter_core.h'):
            src=(fast.COMMON/file).read_text('utf-8')
            self.assertNotRegex(src,r'FocFp_Trip\([^;]*,\s*FOC_FP_TIMEOUT\s*[,)]')

    def test_legacy_diagnostic_binding_syntax(self):
        # The active release profiles are linked elsewhere. Also check the
        # older read-only binding, both with and without its control lease.
        for slot in 'ab':
            build=ROOT/f'foc2_app_{slot}/build/ControlChainReconnect'
            commands=json.loads((build/'compile_commands.json').read_text('utf-8'))
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            cmd=re.sub(r' -o \S+ -c ', ' -fsyntax-only ',cmd)
            for command in (cmd,cmd.replace('-DFOC_CONTROL_CHAIN_RECONNECT=1 ','')):
                p=subprocess.run(command,cwd=build,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assertNotRegex(p.stderr,r'warning:.*(?:FaultDiag|fault_snapshot|current_hold)')

if __name__=='__main__': unittest.main()

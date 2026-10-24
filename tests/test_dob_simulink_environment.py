"""Offline host-only harness checks. Never imports a board executor.

Run build_dob_simulink in MATLAB first. This loads only the host DLL created
in simulation/dob_simulink/build, not an MCU image or hardware transport.
"""
import ast
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / 'simulation/dob_simulink'


class DobSimulinkEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ENV / 'build/dob_host.dll'
        if not path.exists():
            raise unittest.SkipTest('Build MATLAB/Simulink host DLL first')
        cls.dll = C.CDLL(str(path))
        cls.dll.dob_host_reset.argtypes = [C.POINTER(C.c_double)]
        cls.dll.dob_host_step.argtypes = [C.c_double, C.POINTER(C.c_double), C.POINTER(C.c_double)]
        cls.dll.dob_host_state_size.restype = C.c_uint
        cls.dll.dob_host_save.argtypes = [C.c_void_p]
        cls.dll.dob_host_restore.argtypes = [C.c_void_p]

    def reset(self, gain=.25):
        self.dll.dob_host_reset((C.c_double * 3)(gain != 0, gain, .025))

    def step(self, k, u):
        output = (C.c_double * 33)()
        self.dll.dob_host_step(k / 1000, (C.c_double * 10)(*u), output)
        return list(output)

    def steady(self):
        self.reset()
        w = 20
        iq = .0015676864325576986 * w + .11945168237076952 + .0005496600325149542 + .02
        u = [w * 30 / math.pi, w, iq, 0, 0, .005, 1, 0, 0, 1]
        for k in range(3000):
            y = self.step(k, u)
        self.assertEqual(y[11], 1)
        return u, y

    def test_complete_snapshot_restores_cached_epoch_filters_counters_and_integrators(self):
        u, _ = self.steady()
        state = C.create_string_buffer(self.dll.dob_host_state_size())
        self.dll.dob_host_save(state)
        expected = [self.step(k, u) for k in range(3000, 3050)]
        self.dll.dob_host_restore(state)
        actual = [self.step(k, u) for k in range(3000, 3050)]
        self.assertEqual(actual, expected)

    def test_reproduced_signed_id_sequence_does_not_admit_700ma(self):
        u, y = self.steady()
        for k, id_a in enumerate([-.0775, .0452, .6998, .0307], 3000):
            u[5] = id_a
            old = y
            y = self.step(k, u)
            self.assertEqual(y[19], 0, 'single suspect cannot reset full observer')
            if id_a == .6998:
                self.assertEqual(y[15], 0)
                self.assertEqual(y[13], old[13])
                self.assertEqual(y[21], old[21])
        self.assertLess(y[13], .02)

    def test_locked_mechanical_input_cannot_bypass_original_total_current_limit(self):
        self.reset(1)
        u = [240, 0, 0, 0, 0, .005, 1, 0, 0, 1]
        saturated = False
        for k in range(3000):
            y = self.step(k, u)
            self.assertLessEqual(abs(y[7]), .5000001)
            self.assertLessEqual(abs(y[8]), .3500001)
            saturated |= abs(y[7]) >= .4999999
        self.assertTrue(saturated)

    def test_manifest_pins_current_firmware_and_matlab_host_sources(self):
        m = json.loads((ENV / 'build/source_manifest.json').read_text())
        self.assertFalse(m['hardware_access'])
        self.assertFalse(m['physical_performance_validated'])
        self.assertTrue(any(x['path'].endswith('foc2_app_b/Core/Src/main.c') or
                            x['path'].endswith(r'foc2_app_b\Core\Src\main.c') for x in m['sources']))
        for item in m['sources']:
            self.assertEqual(hashlib.sha256(Path(item['path']).read_bytes()).hexdigest(), item['sha256'], item['path'])

    def test_historical_exporter_has_no_hardware_import_and_refuses_fake_truth(self):
        source = (ENV / 'tools/export_historical_evidence.py').read_text()
        tree = ast.parse(source)
        modules = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names]
        self.assertFalse(any('board' in m or m in ('serial', 'pyocd', 'pylink') for m in modules))
        meta = json.loads((ENV / 'results/historical/historical_metadata.json').read_text())
        self.assertTrue(meta['board_provenance_verified'])
        self.assertFalse(meta['ground_truth_available'])
        self.assertFalse(meta['dense_epoch_replay_allowed'])
        self.assertIsNone(meta['load_rmse_a'])


if __name__ == '__main__':
    unittest.main()

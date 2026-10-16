"""Host-only actual C adapter/CRC tests; no board IO or aperture-skew proof."""
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_parallel_report as report
GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"
class Summary(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint16) for n in ("min_u","max_u","min_v","max_v","min_w","max_w")] + [("crc32",ctypes.c_uint32)]
def status(crc=0):
    return ("1 OK ADC3PAR CH=3 REAL_W=1 W_ADC=5 W_PIN=PA8 W_DELAY=NONE SYNC=COMMON_EVENT W_READY=1 "
            "LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 STATE=4 REASON=0 NU=4096 NV=4096 NW=4096 "
            f"IRQ=1,1,1 ERR=0,0,0 RESTORE=1 CRC={crc:08X} CAP=4096")
class ParallelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=ROOT/"tests/adc_parallel_build"; cls.directory.mkdir(exist_ok=True)
        cls.exe=cls.directory/"adapter.exe"
        common=[GCC,"-std=c11","-O2","-Wall","-Wextra","-Werror","-pedantic"]
        subprocess.run(common+["-UNDEBUG","-I",str(ROOT/"tests/adc_dma_mock"),"-I",str(ROOT/"firmware_common"),
            str(ROOT/"tests/adc_parallel_adapter_host.c"),str(ROOT/"firmware_common/adc_raw_report.c"),"-o",str(cls.exe)],check=True)
        dll=cls.directory/"report.dll"
        subprocess.run(common+["-shared",str(ROOT/"firmware_common/adc_raw_report.c"),"-o",str(dll)],check=True)
        cls.lib=ctypes.CDLL(str(dll)); cls.summarize=cls.lib.AdcRaw_SummarizeParallel
        cls.summarize.argtypes=[ctypes.POINTER(ctypes.c_uint16)]*3+[ctypes.c_size_t,ctypes.POINTER(Summary)]
        cls.summarize.restype=ctypes.c_int
    def test_actual_c_scenarios(self):
        for case in list(range(19))+list(range(20,23))+list(range(30,36))+list(range(101,115))+list(range(215,222)):
            with self.subTest(case=case):
                subprocess.run([str(self.exe),str(case)],check=True,capture_output=True,text=True)
    def test_crc_minmax_separate_arrays(self):
        rng=random.Random(10010)
        for n in (1,8,4096):
            triples=[tuple(rng.randrange(4096) for _ in range(3)) for _ in range(n)]
            arrays=[(ctypes.c_uint16*n)(*(t[p] for t in triples)) for p in range(3)]
            result=Summary(); self.assertEqual(self.summarize(*arrays,n,ctypes.byref(result)),1)
            self.assertEqual(result.crc32,zlib.crc32(b"".join(struct.pack("<HHH",*t) for t in triples)))
            for p,name in enumerate("uvw"):
                self.assertEqual(getattr(result,"min_"+name),min(t[p] for t in triples))
                self.assertEqual(getattr(result,"max_"+name),max(t[p] for t in triples))
            arrays[2][0]=4096; self.assertEqual(self.summarize(*arrays,n,ctypes.byref(result)),0)
    def test_parser_refuses_seq_incomplete_or_unsafe(self):
        report.require_status(status(),terminal=True)
        for old,new in (("W_ADC=5","W_ADC=1"),("W_PIN=PA8","W_PIN=PC3"),("W_DELAY=NONE","W_DELAY=SEQ"),
                        ("W_READY=1","W_READY=0"),("IRQ=1,1,1","IRQ=1,1,0"),("ERR=0,0,0","ERR=0,0,1"),
                        ("SYNC=COMMON_EVENT","SYNC=SEQUENTIAL"),("LOCK=1","LOCK=0"),("FOC=0","FOC=1"),
                        ("NW=4096","NW=4095"),("SD=0","SD=1"),("RESTORE=1","RESTORE=0")):
            with self.assertRaises(ValueError): report.require_status(status().replace(old,new),terminal=True)
    def test_full_transcript_and_crc(self):
        triples=[(1500,1600,1700)]*4096; crc=zlib.crc32(struct.pack("<HHH",1500,1600,1700)*4096)
        lines=[status(crc)]+[f"2 OK ADC3PAR_DATA I={i} N=8 UVW="+"05DC064006A4"*8 for i in range(0,4096,8)]
        self.assertEqual(report.read_transcript("\n".join(lines))[1],triples)
        for bad in (lines[:-1],lines+[lines[1]],lines[:1]+[lines[1].replace("05DC","05DD",1)]+lines[2:]):
            with self.assertRaises(ValueError): report.read_transcript("\n".join(bad))
        self.assertFalse(report.analyze(triples)["zero_aperture_skew_verified"])
        self.assertFalse(report.analyze(triples)["motor_qualified"])
if __name__=="__main__": unittest.main()

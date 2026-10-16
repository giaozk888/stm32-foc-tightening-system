import io
from pathlib import Path
import sys
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import pwm_six_channel_qualification as tool

def capture(fault=None):
    # 1200 samples at 24 MHz = 50 us; each gap 30 samples = 1.25 us.
    cycle=bytearray(1200)
    cycle[30:600]=bytes([0x15])*570
    cycle[630:1200]=bytes([0x2a])*570
    data=bytearray(bytes(cycle)*3600+b'\0'*100)
    if fault=='overlap': data[35]=0x3f
    if fault=='sd': data[35]|=0x40
    if fault=='phase': data[100:110]=bytes([0x11])*10
    if fault=='static': data=bytearray(v&~0x30 for v in data)
    meta='[global]\nsigrok version=0.5.2\n[device 1]\nunitsize=1\nsamplerate=24 MHz\ncapturefile=logic-1\n'
    for i,label in enumerate(tool.LABELS): meta+=f'probe{i+1}={label}\n'
    if fault=='labels': meta=meta.replace('UH_PC0','D0')
    if fault=='rate': meta=meta.replace('24 MHz','12 MHz')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('metadata',meta)
        z.writestr('logic-1-1',data)
    archive.seek(0); return archive

class SixSignalTests(unittest.TestCase):
    def test_good_is_logic_only(self):
        row=tool.analyze(capture())
        self.assertTrue(row['six_signal_checks_pass'])
        self.assertFalse(row['bridge_admitted'])
        self.assertFalse(row['motor_qualified'])
        self.assertFalse(row['power_transistor_deadtime_verified'])
    def test_overlap_sd_phase_and_static_fail(self):
        for fault in ('overlap','sd','phase','static'):
            with self.subTest(fault=fault):
                self.assertFalse(tool.analyze(capture(fault))['six_signal_checks_pass'])
    def test_labels_and_low_rate_rejected(self):
        for fault in ('labels','rate'):
            with self.assertRaises(ValueError): tool.analyze(capture(fault))
    def test_run_spanning_chunks(self):
        rule=tool.RunLimit(); rule.feed(b'\0\1\1'); rule.feed(b'\1\1\1\0')
        self.assertEqual((rule.total,rule.maximum),(5,5))
    def test_receipt_cannot_be_unrelated_pass(self):
        manifest={'sha256':'pinned'}
        receipt=dict(pass_=True,mode='SD_LOW_SIX_SIGNALS',image_sha256='pinned',bridge_enabled=False,
                     capture=dict(BRIDGE_COMPILED='0',MODE='2',N='3600'),final_safe_locked=True)
        tool.require_receipt(receipt,manifest)
        for key,value in (('image_sha256','other'),('bridge_enabled',True),('final_safe_locked',False)):
            wrong=dict(receipt); wrong[key]=value
            with self.assertRaises(ValueError): tool.require_receipt(wrong,manifest)

if __name__=='__main__': unittest.main()

"""Host-only validation of exact original B recovery; no hardware access."""
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import median_control_restore_b as r
import median_control_acceptance as a


class RestoreTests(unittest.TestCase):
    def synthetic(self):
        b=r.original_image('B')[1]
        failed=a.image()
        data=bytearray(b'\xff'*0x80000)
        data[0x8000:0x8000+len(failed)]=failed
        data[0x40000:0x40000+len(b)]=b
        self.meta(data,1,411,len(failed),zlib.crc32(failed),len(b),zlib.crc32(b))
        return data,b

    def meta(self,data,current,generation,*images):
        raw=struct.pack('<11I',0x424F4F54,3,current,0,0,generation,*images,0)
        data[0x7F000:0x7F030]=raw+struct.pack('<I',zlib.crc32(raw))

    def test_exact_baseline(self):
        data,b=self.synthetic()
        self.assertEqual(r.baseline(data,bytes(data))[1],b)
        changed=bytearray(data); changed[0x40010]^=1
        with self.assertRaises(RuntimeError): r.baseline(changed,data)
        with self.assertRaises(RuntimeError): r.baseline(changed,changed)
        meta=r.latest_meta(data)
        self.meta(data,2,411,*meta[6:10])
        with self.assertRaises(RuntimeError): r.baseline(data,data)

    def test_only_start_trial_for_original_b(self):
        data,b=self.synthetic()
        words=r.mailbox(b)
        self.assertEqual(words[:5],(0x584F424D,1,2,1,2))
        self.assertEqual(words[5:7],(len(b),zlib.crc32(b)))
        self.assertEqual(words[-1],zlib.crc32(struct.pack('<7I',*words[:-1])))
        with self.assertRaises(RuntimeError): r.mailbox(b[:-1])

    def test_packet_matches_actual_c_mailbox_field_order(self):
        import re
        root=Path(__file__).resolve().parents[1]
        expected=('magic','version','command','requester_slot','target_slot',
                  'image_size','image_crc32','crc32')
        for file in ('foc2_bootloader/Core/Src/main.c',
                     'foc2_app_a/Core/Src/main.c','foc2_app_b/Core/Src/main.c'):
            src=(root/file).read_text(encoding='utf-8')
            structs=re.findall(r'typedef struct[^;]*?\{([^}]+)\}\s*BootMailbox_t;',src,re.S)
            self.assertEqual(len(structs),1,file)
            names=tuple(re.findall(r'uint32_t\s+(\w+)\s*;',structs[0]))
            self.assertEqual(names,expected,file)
            wire=dict(zip(names,r.mailbox(r.original_image('B')[1])))
            self.assertEqual(wire['command'],2)
            self.assertEqual(wire['requester_slot'],1)
            self.assertEqual(wire['target_slot'],2)

    def test_every_byte_except_metadata_preserved(self):
        before,b=self.synthetic(); after=bytearray(before)
        old=r.latest_meta(before)
        self.meta(after,2,414,*old[6:10])
        self.assertEqual(r.require_protected(before,after,b)['confirmed'],'B')
        for offset in (0,0x8000,0x40000,0x78000,0x7F800):
            changed=bytearray(after); changed[offset]^=1
            with self.assertRaises(RuntimeError): r.require_protected(before,changed,b)


if __name__=='__main__': unittest.main()

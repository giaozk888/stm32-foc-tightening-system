"""Offline pinned-image, baseline and clock admission tests; no hardware."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import zero_async_clock_acceptance as accept


class AsyncAcceptanceTests(unittest.TestCase):
    def test_both_new_artifacts_are_exact_slot_images(self):
        for slot in "AB":
            path, image = accept.pinned_image(slot)
            self.assertTrue(path.is_file())
            self.assertEqual(accept.image_info(image)[0], slot)
            self.assertIn(hashlib.sha256(image).hexdigest(), accept.KNOWN[slot])

    def test_old_and_span100_images_still_admitted_for_safe_fallback(self):
        for slot in "AB":
            self.assertIn(accept.ORIGINAL_PINNED[slot], accept.KNOWN[slot])
            self.assertIn(accept.SPAN100_PINNED[slot], accept.KNOWN[slot])

    def test_baseline_requires_two_known_images_and_confirmed_idle_metadata(self):
        images = {s: struct.pack("<II", 0x2001FFC0, base + 9) + bytes(64)
                  for s, base in accept.BASES.items()}
        known = {s: {hashlib.sha256(image).hexdigest()} for s, image in images.items()}
        data = bytearray(b"\xff" * 0x80000)
        for slot, image in images.items():
            start = accept.BASES[slot] - 0x08000000
            data[start:start + len(image)] = image

        def metadata(confirmed=1, pending=0, attempts=0):
            words = [0x424F4F54, 3, confirmed, pending, attempts, 359,
                     len(images["A"]), zlib.crc32(images["A"]),
                     len(images["B"]), zlib.crc32(images["B"]), 0]
            payload = struct.pack("<11I", *words)
            data[0x7F000:0x7F030] = payload + struct.pack("<I", zlib.crc32(payload))

        for slot_id, slot in ((1, "A"), (2, "B")):
            metadata(slot_id)
            self.assertEqual(accept.locked_baseline(data, known)["current"], slot)
        for condition in ((0, 0, 0), (1, 2, 0), (1, 0, 1)):
            metadata(*condition)
            with self.assertRaises(RuntimeError):
                accept.locked_baseline(data, known)
        metadata()
        data[0x800A] ^= 1
        with self.assertRaises(RuntimeError):
            accept.locked_baseline(data, known)
        with self.assertRaises(RuntimeError):
            accept.locked_baseline(bytes(100))

    def test_async_readback_rejects_old_clock_missing_registers_or_geometry(self):
        values = [0x00480000, 0x20000000, 0, 4249]
        def render(items):
            return "\n".join(f"0x{address:08X} : {value:08X}"
                             for address, value in zip(accept.CLOCK_ADDRESSES, items))
        accept.require_async_registers(render(values))
        for index, bad in enumerate((0x00430000, 0x10000000, 3, 4248)):
            changed = values.copy()
            changed[index] = bad
            with self.assertRaises(RuntimeError):
                accept.require_async_registers(render(changed))
        with self.assertRaises(RuntimeError):
            accept.require_async_registers(render(values[:-1]))

    def test_no_sample_unlock_swd_reset_force_confirm_or_alternate_image(self):
        source = Path(accept.__file__).read_text(encoding="utf-8")
        for command in ('"ZERO SAMPLE"', '"START"', '"CLEAR"', '"FW CONFIRM"',
                        '"-rst"', '"BOOT A"', '"BOOT B"', '"FW ABORT"'):
            self.assertNotIn(command, source)
        self.assertIn("allow_reset=False", source)
        self.assertLess(source.index('result["staged_flash"]'), source.index('uart.command("FW END"'))
        self.assertLess(source.index('"/inheritance:r"'), source.index('before = capture("before")'))
        self.assertNotIn('parser.add_argument("--image"', source)


if __name__ == "__main__":
    unittest.main()

"""Offline tests with upstream Pigweed; no serial or motor access."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from detokenize_hmi_logs import decode_record, convert, ROOT
from pw_tokenizer import detokenize, tokens


class DecoderTest(unittest.TestCase):
    def setUp(self):
        self.decoder = detokenize.Detokenizer(tokens.Database([
            tokens.TokenizedStringEntry(0x12345678, "known message")]))
        self.item = {"kind": "pigweed_log", "tokenized": True,
                     "message": "$" + base64.b64encode(b"\x78\x56\x34\x12").decode(),
                     "token_bytes": 4, "raw": "original raw evidence"}

    def test_known_token_keeps_evidence(self):
        result = decode_record(self.item, self.decoder)
        self.assertEqual(result["decoded_message"], "known message")
        self.assertEqual(result["raw"], self.item["raw"])
        self.assertNotIn("decode_status", self.item)

    def test_unknown_malformed_and_wrong_length(self):
        for message, size in [("$AAAAAA==", 4), ("$!bad", 4),
                              (self.item["message"], 5)]:
            with self.subTest(message=message, size=size):
                result = decode_record(dict(self.item, message=message, token_bytes=size), self.decoder)
                self.assertEqual(result["decode_status"], "failed")
                self.assertNotIn("decoded_message", result)

    def test_text_unchanged(self):
        item = {"kind": "pigweed_log", "tokenized": False, "message": "real text"}
        self.assertEqual(decode_record(item, self.decoder), item)

    def test_elf_provenance_and_no_overwrite(self):
        elf = ROOT / "third_party/pigweed/pw_tokenizer/py/example_binary_with_tokenized_strings.elf"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.jsonl"
            target = Path(directory) / "decoded.jsonl"
            with source.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps({"kind": "pigweed_capture", "schema": 1}) + "\n")
                stream.write(json.dumps(self.item) + "\n")
            self.assertEqual(convert(source, elf, target), (0, 1))
            original = target.read_bytes()
            header = json.loads(original.splitlines()[0])
            self.assertEqual(len(header["dictionary_sha256"]), 64)
            self.assertFalse(header["dictionary_match_verified"])
            with self.assertRaises(FileExistsError):
                convert(source, elf, target)
            self.assertEqual(original, target.read_bytes())


if __name__ == "__main__":
    unittest.main()

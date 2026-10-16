"""Read-only Pigweed decoder for HMI JSONL exports (Python >= 3.10).

Preserves raw records, adds dictionary provenance and explicit decode results.
Never opens serial ports, resets a device, or overwrites an existing output.
The selected ELF must belong to the firmware that produced the capture.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "third_party/pigweed/pw_tokenizer/py"),
                str(ROOT / "third_party/pigweed/pw_elf/py")]


def decode_record(item: dict, decoder) -> dict:
    result = dict(item)
    if item.get("kind") != "pigweed_log" or not item.get("tokenized"):
        return result
    result["decode_status"] = "failed"
    try:
        message = item["message"]
        if not isinstance(message, str) or not message.startswith("$"):
            raise ValueError("missing Base64 prefix")
        payload = base64.b64decode(message[1:], validate=True)
        if not 1 <= len(payload) <= 64 or len(payload) != item["token_bytes"]:
            raise ValueError("token byte count mismatch")
        decoded = decoder.detokenize(payload)
        if not decoded.ok():
            raise ValueError(decoded.error_message())
        result["decoded_message"] = str(decoded)
        result["decode_status"] = "decoded"
    except (ValueError, TypeError, KeyError) as exc:
        result["decode_error"] = str(exc)
    return result


def convert(source: Path, elf: Path, output: Path) -> tuple[int, int]:
    from pw_tokenizer.detokenize import Detokenizer

    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("capture exceeds 8 MiB")
    # Validate all input before creating any output. Exclusive creation below
    # prevents silently replacing the original capture or a previous decode.
    records = []
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("capture entries must be JSON objects")
                records.append(item)
    if not records or records[0].get("kind") != "pigweed_capture" or records[0].get("schema") != 1:
        raise ValueError("expected HMI pigweed_capture schema 1")
    decoder = Detokenizer(str(elf))
    hasher = hashlib.sha256()
    with elf.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    converted = [decode_record(item, decoder) for item in records]
    converted[0].update(dictionary_elf=elf.name, dictionary_sha256=digest,
                        dictionary_match_verified=False)
    # A successful lookup is not proof that the ELF matches the running image.
    decoded = sum(item.get("decode_status") == "decoded" for item in converted)
    failed = sum(item.get("decode_status") == "failed" for item in converted)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        for item in converted:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    return decoded, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        decoded, failed = convert(args.capture, args.elf, args.output)
    except (OSError, ValueError, ImportError) as exc:
        print(f"decode failed: {exc}", file=sys.stderr)
        return 1
    print(f"decoded={decoded} unresolved={failed}; dictionary match requires firmware verification")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

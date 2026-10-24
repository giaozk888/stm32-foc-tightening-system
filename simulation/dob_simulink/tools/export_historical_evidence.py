"""FILES ONLY. Validate existing receipt/ELF/Flash/RAM; export sparse evidence.

Never fabricates 1kHz observations or load ground truth. Does not import any
board executor, UART, debugger, flashing or hardware transport module.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import dob_id_trace_report
import mechanical_dob_report


def export(receipt: Path, elf: Path, output: Path, trace: bool = False):
    decoded = (dob_id_trace_report if trace else mechanical_dob_report).decode(receipt, elf)
    rows = decoded['rows']
    output.mkdir(parents=True, exist_ok=True)
    destination = output / 'historical_sparse.csv'
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with destination.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    info = dict(source_receipt=str(receipt.resolve()), elf=str(elf.resolve()),
                rows=len(rows), board_provenance_verified=decoded['board_verified'],
                ground_truth_available=False, physical_performance_validated=False,
                dense_epoch_replay_allowed=False, load_rmse_a=None,
                note='Sparse historical evidence only; no resampling/interpolation or ground-truth load inference.',
                decoder_note=decoded.get('note'))
    (output / 'historical_metadata.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    return info


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt', required=True, type=Path)
    p.add_argument('--elf', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--trace', action='store_true')
    a = p.parse_args()
    print(json.dumps(export(a.receipt, a.elf, a.out, a.trace), indent=2))

"""Decode only the loaded-FSM B ELF and a halted SRAM capture; no devices."""
import argparse
import json
from pathlib import Path
import struct
from foc_path_profile_report import symbols

ROOT = Path(__file__).resolve().parents[1]


def decode(ram, elf=None):
    table = symbols(elf or ROOT/'foc2_app_b/build/LoadedFsmTrial/foc2.elf')
    def words(name, size):
        address, actual = table[name]
        if actual != size:
            raise ValueError('ELF schema mismatch: '+name)
        return struct.unpack_from('<'+'I'*(size//4), ram, address-0x20000000)
    head = 'valid timestamp_ms domain fault_reason timeout_reason motor_mode tightening_state state_elapsed_ms'.split()
    floats = ('position_deg position_target_deg position_error_deg speed_raw_rpm '
              'speed_filtered_rpm speed_command_rpm iq_ref_A iq_measured_A '
              'id_measured_A stall_elapsed_s').split()
    tail = ('contact_candidate_ms encoder_valid encoder_errors current_validator_state '
            'current_suspect_total current_confirmed_spike current_confirmed_transition '
            'current_unresolved_total current_unresolved_consecutive current_unresolved_max_consecutive '
            'foc_cycles_max foc_normal_cycles_max foc_suspect_cycles_max foc_unresolved_cycles_max '
            'foc_deadline_miss_count adc_sample_count foc_exec_count current_hold_total '
            'hold_window_count hold_window_max hold_rate_per_mille hold_window_ms '
            'evidence_present protection_flags').split()
    evidence = ('reason now_us reference_us elapsed_us limit_us last_sample_us '
                'pending_since_us pending misses').split()
    address, size = table['foc_fault_snapshot']
    if size != 204:
        raise ValueError('Fault snapshot schema mismatch')
    values = struct.unpack_from('<8I10f33I', ram, address-0x20000000)
    timing = words('foc_preempt_timing', 140)
    probe = words('foc_pwm_write_profile', 128)
    margin = struct.unpack('<i', struct.pack('<I',probe[5]))[0]
    return dict(first_fault=dict(zip(head+floats+tail+['timeout_'+n for n in evidence],values)),
                timing=dict(wall_max_us=timing[2]/170, deadline_miss=timing[5],
                    actual_commit_count=probe[0], actual_margin_min_us=margin/170,
                    actual_late_count=words('foc_ccr_probe_hard_late',4)[0]),
                cur_confirm=dict(zip(('enter','clear','fault','max_cycles','max_elapsed_us'),
                    struct.unpack_from('<5I',ram,table['cl_safety'][0]-0x20000000+124))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ram', type=Path)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--flash', type=Path)
    args = parser.parse_args()
    if args.elf:
        if not args.flash:
            parser.error('Explicit ELF requires its matching full Flash capture')
        image=args.elf.with_suffix('.bin').read_bytes()
        captured=args.flash.read_bytes()
        table=symbols(args.elf)
        reset=struct.unpack_from('<I',image,4)[0]
        if (len(captured)!=0x80000 or reset!=(table['Reset_Handler'][0]|1)
                or not any(captured[off:off+len(image)]==image for off in (0x8000,0x40000))):
            parser.error('ELF/image/full Flash identity mismatch')
    report = decode(args.ram.read_bytes(),args.elf)
    args.ram.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

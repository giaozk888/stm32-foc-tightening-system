"""Read frozen B's first phase-trip snapshot, no reset/resume or motion."""
import json
import struct
import time

import original_closed_loop_updated_stage as stage


def decode(raw):
    if len(raw) != 96:
        raise ValueError('Exact original B snapshot and fault words required')
    unsigned = struct.unpack_from('<8I', raw)
    currents = struct.unpack_from('<4i', raw, 32)
    adc = struct.unpack_from('<13H', raw, 48)
    filter_on, median_count, vbus_valid, valid = struct.unpack_from('<4B', raw, 74)
    trip_w, trip_v, trip_u, reason = struct.unpack_from('<3iI', raw, 80)
    return dict(valid=valid, reason=reason, tick_ms=unsigned[0], adc_seq=unsigned[1],
        vbus_age_ms=unsigned[2], accepted_count=unsigned[3], rejected_count=unsigned[4],
        reject_streak=unsigned[5], analog_count=unsigned[6], analog_errors=unsigned[7],
        current_mA=list(currents[:3]), last_rejected_step=currents[3],
        accepted_adc=list(adc[:2]), physical_adc=list(adc[2:4]), zero_adc=list(adc[4:6]),
        vbus_raw=adc[6], median_u=list(adc[7:10]), median_v=list(adc[10:13]),
        filter_on=filter_on, median_count=median_count, vbus_valid=vbus_valid,
        trip_current_mA=[trip_u, trip_v, trip_w])


def main():
    stage.pinned_image()
    run = 'original-updated-fault-' + str(time.time_ns())
    path = stage.PRIVATE / (run + '.bin')
    controller = stage.PRIVATE / (run + '-controller.bin')
    receipt = stage.OUTPUT / (run + '.json')
    row = dict(pass_=False, steps=[], resets=0, writes=0, motor_commands=0)
    try:
        out = stage.debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0 || [mrw 0xE000ED08] != 0x08040000} {error "Not frozen B; snapshot addresses invalid"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Output not off"}',
            *stage.off_report(), f'dump_image {{{path.as_posix()}}} 0x20002760 0x60',
            f'dump_image {{{controller.as_posix()}}} 0x2000271c 0x20', 'shutdown'])
        row['outputs'] = stage.check_off(out, (0x08040000,))
        row['snapshot'] = decode(path.read_bytes())
        if row['snapshot']['valid'] != 1 or row['snapshot']['reason'] != 1:
            raise RuntimeError('No committed first phase-current trip')
        row['controller'] = dict(zip(('integrator_q_V', 'integrator_d_V', 'vq_V', 'vd_V',
            'iq_A', 'id_A', 'iq_ref_A', 'id_ref_A'), struct.unpack('<8f', controller.read_bytes())))
        row['pass_'] = True
        print(json.dumps(row['snapshot'], ensure_ascii=False, indent=2))
        print(json.dumps(row['controller'], ensure_ascii=False, indent=2))
    except BaseException as error:
        row['failure'] = str(error)
        raise
    finally:
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt))


if __name__ == '__main__':
    main()

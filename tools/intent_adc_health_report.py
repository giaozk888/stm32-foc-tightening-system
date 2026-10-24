"""Offline A728 SRAM/Flash evidence only; no hardware or firmware changes."""
import json
import struct
from pathlib import Path
import intent_fsm_board_acceptance as old
from foc_path_profile_report import symbols

RECEIPT=old.TMP/'intent-fsm-run-1792411352445848100.json'


def report(path=RECEIPT):
    receipt=json.loads(path.read_text('utf-8'))
    if (receipt.get('image_sha256')!=old.SHA or receipt.get('elf_sha256')!=old.ELF_SHA or
            receipt.get('final_cpu_halted') is not True):
        raise ValueError('Expected stopped A728 receipt')
    flash_path=Path(receipt['final_capture']).resolve()
    ram_path=Path(receipt['ram_capture']).resolve()
    if flash_path.parent!=old.TMP.resolve() or ram_path.parent!=old.TMP.resolve():
        raise ValueError('Local evidence directory required')
    flash=flash_path.read_bytes(); ram=ram_path.read_bytes(); binary=old.image()
    if (len(flash)!=0x80000 or old.old.zero.digest(flash)!=receipt['final_sha256'] or
            flash[0x8000:0x8000+len(binary)]!=binary or len(ram)!=0x20000 or
            receipt.get('outputs',{}).get('VTOR')!=0x08008000):
        raise ValueError('Capture/ELF/image mismatch')
    table=symbols(old.ELF)

    def read(name,size,fmt,rom=False):
        address,actual=table[name]
        if actual!=size: raise ValueError('A728 ABI mismatch: '+name)
        source=flash if rom else ram
        offset=address-(0x08000000 if rom else 0x20000000)
        if offset<0 or offset+size>len(source): raise ValueError('Capture bounds')
        return struct.unpack_from(fmt,source,offset)

    # Exact ARM -fshort-enums config layout, checked against this pinned ELF.
    cfg=read('config',16,'<5HBBHBB',True)
    if cfg!=(4249,85,85,14,50,2,0,1700,1,0):
        raise ValueError('Unexpected retained sampling geometry')
    address,size=table['stats']
    if size!=132: raise ValueError('Timing stats ABI mismatch')
    stats=struct.unpack_from('<10I6H4B',ram,address-0x20000000)
    duties=[read('foc_duty_'+axis,4,'<f')[0] for axis in 'uvw']
    # Non-boundary rounding checked with real C -Os/-O2 replay regression.
    phases=[int(duty*4250) for duty in duties]
    required=max(phases[:2])+cfg[1]+cfg[7]
    latest=cfg[0]-1-cfg[3]-cfg[4]
    return dict(offline_only=True,hardware_access=False,capture_identity_verified=True,
        image_sha256=old.SHA,elf_sha256=old.ELF_SHA,
        adc_pairs=stats[1],adc_pair_misses=stats[2],plan_failures=stats[3],
        last_plan_status=stats[16],last_plan_status_name='TOO_SHORT' if stats[16]==3 else 'OTHER',
        last_retained_duty_uvw=duties,replayed_phase_ccr_uvw=phases,
        configured_min_low_on_ticks=cfg[7],configured_dead_ticks=cfg[1],
        configured_latency_ticks=cfg[3],configured_aperture_ticks=cfg[4],
        required_earliest_tick=required,latest_tick=latest,
        deficit_ticks=max(0,required-latest),deficit_us=max(0,required-latest)/170,
        uv_max_legal_ccr=latest-cfg[1]-cfg[7],fixed_trigger=stats[14],
        interpretation=[
            'One plan failure, not a paired-ADC miss or measured FOC deadline overrun.',
            'Retained final duty replays TOO_SHORT with unchanged planner/constraints.',
            'Rejected phase plan was not independently latched; retained duty is not a new on-board sample.',
            '2 ticks is a geometric deficit, not a justification to shorten analog recovery.',
            'The prior FSM TIMEOUT label hid an already latched HEALTH/CL_BAD_ADC fault.',
            'No protection, frequency, PI, voltage/current limit or PWM strategy changed by this decoder.'])


if __name__=='__main__':
    print(json.dumps(report(),indent=2,ensure_ascii=False))

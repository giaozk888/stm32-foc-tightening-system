"""Offline historical reference vs new PI FSM observation; no hardware access."""
import hashlib
import json
from pathlib import Path
import struct
from foc_path_profile_report import symbols
from loaded_fsm_snapshot_report import decode

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'tmp/friction-fsm-run-1792494625353182000.json'
NEW=ROOT/'tmp/current-pi-fsm-run-1792566696767741900.json'


def observation(path,preset,expected_bin,expected_elf):
    row=json.loads(path.read_text('utf-8'))
    image=ROOT/'foc2_app_a/build'/preset/'foc2.bin';elf=image.with_suffix('.elf')
    data=image.read_bytes();flash=Path(row['final_capture']).read_bytes();ram=Path(row['ram_capture']).read_bytes()
    digest=lambda b:hashlib.sha256(b).hexdigest()
    if (digest(data)!=expected_bin or digest(elf.read_bytes())!=expected_elf or
        row['image_sha256']!=expected_bin or row['elf_sha256']!=expected_elf or
        digest(flash)!=row['final_sha256'] or flash[0x8000:0x8000+len(data)]!=data or
        len(ram)!=0x20000 or row['outputs']['VTOR']!=0x08008000 or
        row.get('start_attempts')!=1 or not row.get('fsm_observation_complete') or
        not row.get('final_cpu_halted') or not row.get('final_outputs_off') or
        not row.get('all_app_private_unchanged') or row['terminal_status']['OUTCOME']!='RUNDOWN_TIMEOUT'):
        raise ValueError('Exact stopped single-START no-load capture required')
    recipe=row['effective_ram_recipe']
    if any(recipe[k]!=v for k,v in dict(RUNDOWN_RPM=240,MAX_TRAVEL_DEG=20000,RUNDOWN_TIMEOUT_MS=8000).items()):
        raise ValueError('Different recipe; not a reference comparison')
    table=symbols(elf)
    addr,size=table['speed_accel_ff_stats']
    if size!=84:raise ValueError('FF stats ABI mismatch')
    values=struct.unpack_from('<2I18f4B',ram,addr-0x20000000)
    aff_keys=('samples segment time_s max_error_rpm accel_error_integral accel_time_s '
        'decel_error_integral decel_time_s overshoot_rpm iq_peak_a integrator_peak_a '
        'iq_measured_peak_a saturation_s saturation_run_s saturation_run_max_s '
        'command_rpm direction segment_time_s settle_candidate_s settling_time_s '
        'settling settled reserved0 reserved1').split()
    aff=dict(zip(aff_keys,values))
    if aff!=row['accel_ff_ram_stats']:raise ValueError('Stored FF statistics differ from RAM')
    addr,size=table['speed_friction_stats']
    if size!=120:raise ValueError('Friction stats ABI mismatch')
    fr_keys=('samples elapsed_s low_error_integral low_time_s cruise_error_integral cruise_time_s '
        'integrator_peak_a pi_peak_a iq_peak_a iq_measured_peak_a speed_integral '
        'wrong_direction_time_s start_delay_s').split()
    fr=dict(zip(fr_keys,struct.unpack_from('<I12f',ram,addr-0x20000000)))
    if fr!=row['friction_ram_stats']['POS']:raise ValueError('Stored friction statistics differ from RAM')
    snap=decode(ram,elf)
    if snap!=row['snapshot']:raise ValueError('Snapshot differs from exact-ELF decode')
    if (snap['timing']['deadline_miss'] or snap['timing']['actual_late_count'] or
        snap['cur_confirm']['fault'] or snap['first_fault']['domain']!=3 or
        snap['first_fault']['fault_reason']!=3 or snap['first_fault']['protection_flags']):
        raise ValueError('Unexpected protection fault; not just process rundown timeout')
    return dict(receipt=str(path),flash_sha256=digest(flash),ram_sha256=digest(ram),
        recipe=recipe,terminal='RUNDOWN_TIMEOUT',contact=row['terminal_status']['CONTACT'],
        metrics=dict(start_delay_ms=fr['start_delay_s']*1000,
            accel_mae_rpm=aff['accel_error_integral']/aff['accel_time_s'],
            cruise_mae_rpm=fr['cruise_error_integral']/fr['cruise_time_s'],
            low_speed_mae_rpm=fr['low_error_integral']/fr['low_time_s'],
            max_speed_error_rpm=aff['max_error_rpm'],overshoot_rpm=aff['overshoot_rpm'],
            project_settling_ms=aff['settling_time_s']*1000,
            iq_ref_peak_a=aff['iq_peak_a'],iq_feedback_peak_a=aff['iq_measured_peak_a'],
            speed_integrator_peak_a=aff['integrator_peak_a'],saturation_s=aff['saturation_s'],
            tail_mean_rpm=row['speed_summary']['tail_mean_rpm'],
            net_observed_travel_deg=row['speed_summary']['net_observed_travel_deg']),
        timing=snap['timing'],cur_confirm=snap['cur_confirm'])


def report():
    old=observation(OLD,'CurrentPiLegacyCompare',
        '3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899',
        '362662765bc56615f6d264e1356eeae9585603ecbf0693ca960cdbdb44cad406')
    new=observation(NEW,'CurrentPiIdentifiedCandidate',
        'aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e',
        'd015db4a488cefb4d17af5d59631731163c22a54d14aa41baef91708f19c3b77')
    if old['recipe']!=new['recipe']:raise ValueError('Not the same full RAM recipe')
    return dict(offline_only=True,hardware_access=False,same_batch_ab=False,
        parameter_identification_qualified=False,old=old,new=new,
        qualification='One current no-load run vs historical same-recipe run, not repeated randomized A/B, not torque/current-loop identification validation')


if __name__=='__main__':print(json.dumps(report(),indent=2))

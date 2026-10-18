"""File-only SB2 current-command/voltage-limit diagnosis. No board imports."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
ELF=ROOT/'foc2_app_a/build/SpeedBumplessTrial/foc2.elf'
IMAGE_SHA='b78864f64ff417d4cfc3101f9d6f22292a96e89807359f4154aa8ee6ba0f8488'
ELF_SHA='e214429a993cd852affdf5a3d849c35a51740c79fe108b601a5bb3c8ad314110'
FULL=ROOT/'tmp/sb2-fsm-fsm-1792312823013155000.json'
SHORT=ROOT/'tmp/sb2-speed-speed-1792312170760143300.json'


def digest(data): return hashlib.sha256(data).hexdigest()


def summarize_active(rows):
    # The recorded tail straddles STOP. Exclude all zero-demand frames rather
    # than attributing their residual current to active HOLD or SPEED tracking.
    active=[row for row in rows if row['iq_ref_A']>.14]
    if not active: raise ValueError('No retained active-current tail')
    voltage=[math.hypot(r['vd_V'],r['vq_V']) for r in active]
    error=[r['iq_ref_A']-r['iq_A'] for r in active]
    return dict(frames=len(active),first_ms=active[0]['elapsed_us']/1000,
        last_ms=active[-1]['elapsed_us']/1000,
        means={n:statistics.mean(r[n] for r in active) for n in
               ('iq_ref_A','iq_A','id_A','vd_V','vq_V','filtered_rpm')},
        iq_error_mean_A=statistics.mean(error),
        voltage_vector_min_V=min(voltage),voltage_vector_max_V=max(voltage),
        at_0p8V_limit_frames=sum(abs(v-.8)<1e-5 for v in voltage),
        above_99pct_limit_frames=sum(v>=.8*.99 for v in voltage),
        max_abs_integrator_V={n:max(abs(r[n]) for r in active) for n in
                              ('current_int_d_V','current_int_q_V')},
        # Saved voltages and PI state should be mutually consistent with the
        # unchanged .080 V/A P term, including vector tracking anti-windup.
        pi_output_residual_max_V=max(max(
            abs(r['vd_V']-(r['current_int_d_V']-.080*r['id_A'])),
            abs(r['vq_V']-(r['current_int_q_V']+.080*(r['iq_ref_A']-r['iq_A']))))
            for r in active))


def analyze(path,table):
    r=json.loads(path.read_text('utf-8'))
    image=ELF.with_suffix('.bin').read_bytes()
    flash=Path(r['final_capture']).read_bytes(); ram=Path(r['ram_capture']).read_bytes()
    if (r.get('image_sha256')!=IMAGE_SHA or r.get('elf_sha256')!=ELF_SHA or
            len(flash)!=0x80000 or len(ram)!=0x20000 or
            flash[0x8000:0x8000+len(image)]!=image or
            digest(flash)!=r['final_sha256'] or r.get('start_attempts')!=1 or
            not r.get('final_cpu_halted') or not r.get('final_outputs_off') or
            r['outputs']['VTOR']!=0x08008000):
        raise ValueError('Exact stopped SB2 image/receipt required')

    def scalar(name,fmt):
        address,size=table[name]
        if size!=struct.calcsize('<'+fmt): raise ValueError('ELF scalar size: '+name)
        return struct.unpack_from('<'+fmt,ram,address-0x20000000)[0]

    interval={n:scalar(n,'f') for n in ('speed_diag_time_s','speed_diag_speed_integral',
                                      'speed_diag_min_rpm','speed_diag_max_rpm')}
    if scalar('speed_diag_valid','B')!=1 or interval['speed_diag_time_s']<=0:
        raise ValueError('No SPEED diagnostic interval')
    interval['mean_filtered_rpm']=interval['speed_diag_speed_integral']/interval['speed_diag_time_s']
    address,size=table['cl_startup']; offset=address-0x20000000
    if size!=2000: raise ValueError('Exact startup-trace schema required')
    head=dict(zip(('start_us','flags','off_us','total','active','frozen','fault_valid','pad'),
                  struct.unpack_from('<4I4B',ram,offset+1980)))
    if head['active'] or not head['frozen'] or head['fault_valid'] or head['total']<32:
        raise ValueError('Expected frozen nonfaulting startup trace')
    rows=[]
    for seq in range(head['total']-32,head['total']):
        values=struct.unpack_from('<3I4H10f',ram,offset+seq%32*60)
        rows.append(dict(zip(('elapsed_us','adc_seq','encoder_us','angle_raw','adc_u','adc_v',
            'reserved','ref_rpm','instant_rpm','filtered_rpm','iq_ref_A','id_A','iq_A',
            'vd_V','vq_V','current_int_d_V','current_int_q_V'),values)))
    analog={n:scalar(n,fmt) for n,fmt in
        (('analog_live_pc4_raw','H'),('analog_live_valid','B'),
         ('analog_live_last_tick_ms','I'),('analog_live_sample_count','I'),
         ('analog_vdda_boot_mv','H'),('analog_vdda_boot_valid','B'))}
    analog['post_stop_vbus_est_V']=analog['analog_live_pc4_raw']*analog['analog_vdda_boot_mv']*25/(4095*1000)
    return dict(receipt=str(path),ram_sha256=digest(ram),trace_header=head,
        speed_interval=interval,active_tail=summarize_active(rows),tail_rows=rows,
        analog_post_stop=analog,software_counts={n:scalar(n,'I') for n in
            ('foc_pending_generated','foc_pending_held','foc_pending_empty',
             'current_valid_count','foc_control_count','cl_outer_n')},
        board_snapshot=r['snapshot'],full_cycle=bool(r.get('cycle_pass')),
        limits=dict(iq_output_A=.4,voltage_vector_V=.8,integrator_V=.75,
                    contact_demand_A=.3,contact_speed_rpm=10,contact_confirm_ms=250))


def main():
    if digest(ELF.read_bytes())!=ELF_SHA or digest(ELF.with_suffix('.bin').read_bytes())!=IMAGE_SHA:
        raise ValueError('Pinned SB2 BIN/ELF identity changed')
    table=symbols(ELF)
    result=dict(offline_only=True,hardware_operations=0,firmware_modified=False,
        image_sha256=IMAGE_SHA,elf_sha256=ELF_SHA,
        full=analyze(FULL,table),short=analyze(SHORT,table))
    output=ROOT/'tmp/sb2-no-load-diagnosis-20261018.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),full_tail=result['full']['active_tail'],
        short_tail=result['short']['active_tail'],
        analog_post_stop=result['full']['analog_post_stop']),indent=2))
    return result


if __name__=='__main__': main()

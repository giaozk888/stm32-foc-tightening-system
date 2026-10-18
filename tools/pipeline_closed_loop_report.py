"""Re-decode the saved LIGHT candidate evidence; no device access.

Keep the original acquisition receipt immutable. Its first decoder exposed
unmaintained heavy counters as zero. Publish corrected light semantics with
source hashes in a separate derived receipt, not fabricated MCU measurements.
"""
import json
import time
import pipeline_closed_loop_trial as trial


def main():
    data=trial.candidate.image()
    source=trial.candidate.OUTPUT/'protected-pipeline-trial-1792228438430412700.json'
    raw=source.read_bytes()
    row=json.loads(raw.decode('utf-8'))
    if (row.get('image_sha256') != trial.candidate.SHA or
            row.get('elf_sha256') != trial.candidate.ELF_SHA or
            row.get('final_outputs_off') is not True or row.get('final_cpu_halted') is not True):
        raise ValueError('Exact stopped candidate evidence required')
    flash=trial.candidate.tx.prior.private_path(row['final_backup']).read_bytes()
    if trial.candidate.digest(flash) != row['final_sha256']:
        raise ValueError('Captured full Flash hash mismatch')
    ram=trial.candidate.tx.prior.private_path(row['ram_backup']).read_bytes()
    trial.decode(row,data)
    report=dict(derived_from=str(source),source_sha256=trial.candidate.digest(raw),
        ram_sha256=trial.candidate.digest(ram),full_flash_sha256=trial.candidate.digest(flash),
        image_sha256=trial.candidate.SHA,elf_sha256=trial.candidate.ELF_SHA,
        hardware_access=False,new_trial=False,new_motor_commands=0,
        candidate_pass=row['pass_'],timing_pass=row.get('timing_pass'),
        preflight_pass=row.get('preflight_pass'),normally_confirmed=row.get('normally_confirmed'),
        failure=row.get('failure'),measured=row.get('measured'),first_fault=row.get('first_fault'),
        cur_confirm=row.get('cur_confirm'),
        note='Heavy frames/writes/geometry are not retained in LIGHT; points counts real 3-store commits.')
    path=trial.candidate.OUTPUT/('protected-pipeline-analysis-'+str(time.time_ns())+'.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Derived report: '+str(path),flush=True)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())

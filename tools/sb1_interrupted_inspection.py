"""Capture an interrupted run WITHOUT reset, resume, START or boot selection."""
import json
import sys
from pathlib import Path

from original_closed_loop_updated_stage import debug,off_report
from loaded_fsm_snapshot_report import decode
from tighten_synthetic_swd_recovery import latest_meta
from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
PREFIX=ROOT/'tmp/sb1-speed-interrupted-final'
ELF=ROOT/'foc2_app_a/build/ZeroValidAdmissionTrial/foc2.elf'
row={'steps':[],'reset':False,'start':False}
try:
    debug(row,['init','halt',*off_report(),'reg pc',
        f'dump_image {{{PREFIX.as_posix()}-ram.bin}} 0x20000000 0x20000','shutdown'])
except Exception as error:
    row['capture_error']=str(error)
flash=Path(str(PREFIX)+'-flash.bin').read_bytes()
row['metadata']=list(latest_meta(flash))
ram_path=Path(str(PREFIX)+'-ram.bin')
if ram_path.exists():
    ram=ram_path.read_bytes(); table=symbols(ELF)
    if flash[0x8000:0x8000+len(ELF.with_suffix('.bin').read_bytes())]==ELF.with_suffix('.bin').read_bytes():
        row['snapshot']=decode(ram,ELF)
        row['symbols']={n:table[n] for n in ('cl_session','cl_zero','cl_zero_filter','cl_startup')}
        row['ram_hex']={n:ram[a-0x20000000:a-0x20000000+s].hex() for n,(a,s) in row['symbols'].items()}
Path(str(PREFIX)+'.json').write_text(json.dumps(row,indent=2)+'\n',encoding='utf-8')
print(json.dumps(row,indent=2))
sys.exit(bool(row.get('capture_error')))

"""Offline source/compiled-body comparison with the frozen pre-refactor build."""
from pathlib import Path
import json
import re
import struct
import subprocess
from app_a_source_layout import ROOT,read_app_source

BASE=ROOT/'refactor_backups/20261025_app_layout'
FUNCTIONS=('FOC_EncoderSpeedUpdate','HAL_ADCEx_InjectedConvCpltCallback','HAL_ADC_ErrorCallback',
    'EncoderDma_FaultFromISR','PowerStage_Disable','PWM_SetDuty','FOC_ResetController','OuterObservation_Flush',
    'MotorControlTask')


def object_sections(path):
    data=path.read_bytes()
    header=struct.unpack_from('<16sHHIIIIIHHHHHH',data)
    if header[0][:6]!=b'\x7fELF\x01\x01':raise ValueError('Expected little-endian ELF32')
    offset,size,count,names=header[6],header[11],header[12],header[13]
    rows=[struct.unpack_from('<IIIIIIIIII',data,offset+i*size) for i in range(count)]
    strings=rows[names];strings=data[strings[4]:strings[4]+strings[5]]
    return {strings[row[0]:strings.index(0,row[0])].decode():data[row[4]:row[4]+row[5]] for row in rows}


def audit_object():
    before=BASE/'reviewed_before.main.o'
    after=ROOT/'foc2_app_a/build/AppLayoutCandidate/CMakeFiles/foc2.dir/Core/Src/main.c.obj'
    a,b=object_sections(before),object_sections(after)
    names=[name for name in a if name.startswith('.text.') and name in b]
    changed=[name for name in names if a[name]!=b[name]]
    missing=[name for name in a if name.startswith('.text.') and name not in b]
    # main loses inlined MX bodies; SystemClock_Config moves to the board C file.
    allowed_changes={'.text.startup.main'}
    allowed_missing={'.text.SystemClock_Config'}
    return dict(compared=len(names),identical=sum(a[name]==b[name] for name in names),
        changed=changed,moved=missing,
        passed=set(changed)<=allowed_changes and set(missing)<=allowed_missing,
        scope='Unlinked instruction/literal bytes only; not linked addresses or measured WCET')


def function(source,name):
    m=re.search(r'\b'+name+r'\([^;{}]*\)\s*\{',source)
    if not m:return None
    start=m.start();depth=0
    # A token scanner prevents braces inside comments/string literals altering nesting.
    pattern=r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*|[{}]'
    for t in re.finditer(pattern,source[m.end()-1:],re.S):
        token=t.group()
        if token=='{':depth+=1
        elif token=='}':
            depth-=1
            if not depth:return re.sub(r'\s+','',source[start:m.end()-1+t.end()])
    raise ValueError('Unbalanced function '+name)


def audit():
    assert read_app_source(ROOT/'foc2_app_a/Core/Src/main.c')==(BASE/'foc2_app_a/Core/Src/main.c').read_text()
    rows=[]
    for preset in ('DobLoadSpeedContactHoldCandidate','TighteningDob025Trip500','FastCurrentRejectComputeOnly'):
        c=json.loads((BASE/(preset+'.compile.json')).read_text())
        p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',c['command']),cwd=c['directory'],text=True,capture_output=True)
        if p.returncode:raise RuntimeError(p.stderr)
        before=(BASE/(preset+'.before.i')).read_text();checks={}
        for name in FUNCTIONS:
            a,b=function(before,name),function(p.stdout,name)
            if a is None and b is None:continue
            checks[name]=a==b
        (ROOT/'tmp'/('app-layout-'+preset+'.after.i')).write_text(p.stdout)
        # Compile the real new board boundary with exactly the same profile flags.
        command=re.sub(r' -o \S+ -c ',' -fsyntax-only ',c['command'])
        board_file=ROOT/'foc2_app_a/Core/Src/App/board/app_board.c'
        command=command.replace(c['file'].replace('/','\\'),str(board_file).replace('/','\\'))
        if 'App\\board\\app_board.c' not in command:
            command=command.replace(c['file'],board_file.as_posix())
        if 'app_board.c' not in command:raise ValueError('Board compile source replacement failed')
        board=subprocess.run(command,cwd=c['directory'],text=True,capture_output=True)
        rows.append(dict(profile=preset,main_preprocessed=True,board_syntax=board.returncode==0,
            board_errors=board.stderr if board.returncode else '',functions=checks))
    machine=audit_object()
    result=dict(logical_source_equal=True,profiles=rows,object_code=machine,hardware_access=False,
        passed=machine['passed'] and all(r['board_syntax'] and all(r['functions'].values()) for r in rows))
    (ROOT/'tmp/app-layout-preprocess-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':audit()

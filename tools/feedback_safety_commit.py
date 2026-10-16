"""One staged hard-OFF B trial + independent stopped-ADC timeout diagnosis.

No motor/PWM/bridge enable, direct metadata write, force-confirm, fault clear,
host retry or second FW END. Powered current-sense inputs and disconnected
U/V/W required. Existing bootloader may perform its own bounded trial retries.
"""
import argparse
import json
import re
from pathlib import Path
import subprocess
import time
import zlib
import feedback_safety_stage as staging
from firmware_transfer_iap import fields, Uart
from median_control_acceptance import Console as BaseConsole, require_zero
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, latest_meta
from zero_span100_acceptance import ADDRESSES, require_registers
from tighten_synthetic_acceptance import locked, confirmed, require_stopped

READ = frozenset(('FW STATUS', 'ANALOG SAFE STATUS', 'STATUS', 'BENCH STATUS',
                  'BENCH ZERO', 'BENCH STACK', 'BENCH PROTECTION',
                  'BENCH PROTECTION TIMING', 'BENCH PROTECTION FAULT'))
# Includes Flash CRC/boot initialization as well as two 12 s health trials.
# This is an observation bound, not permission to resend END or reset a board.
OBSERVE_SECONDS = 90
OBSERVE_POLL_SECONDS = .2

class Console(BaseConsole):
    def __init__(self, port):
        super().__init__(port, commit=True)
        self.timeout_tests = 0

    def query(self, text, timeout=2):
        if text == 'BENCH PROTECTION TEST TIMEOUT':
            if self.timeout_tests: raise ValueError('One stopped-stream injection only')
            self.timeout_tests += 1
        elif text not in READ and text != 'BENCH STOP':
            raise ValueError('No actuation, fault clearing or restart')
        # Own whitelist, same base parser; no mutation of historical runner.
        self.request += 1; request = self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        until = time.monotonic()+timeout
        while time.monotonic() < until:
            line = self.read_line(.05)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                print(line, flush=True)
                return line
        raise TimeoutError('No ACK; no resend: '+text)

    def dispatch(self, line):
        # Preserve first failure data instead of aborting on a banner before
        # the guardian fault query can be collected. No change to boot health.
        if line: self.lines.append(line)
        Uart.dispatch(self, line)
        if line and any(s in line for s in ('BOOT HEALTH:', 'ISOLATED ZERO', 'ISOLATED CONCURRENCY:')):
            print(line, flush=True)

def stage_evidence(path, profile=staging):
    path = path.resolve()
    if path.parent != profile.OUTPUT.resolve(): raise RuntimeError('Stage evidence outside exact directory')
    row = json.loads(path.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('image_sha256') != profile.SHA or
            row.get('stage_only') is not True or not row.get('all_bytes_outside_b_unchanged')):
        raise RuntimeError('Exact complete successful stage required')
    backup = Path(row['before_backup']).resolve()
    if backup.parent != (profile.OUTPUT/'private').resolve(): raise RuntimeError('Private baseline path changed')
    original = backup.read_bytes(); profile.baseline(original)
    return original

def protection(line, running=True, repair_budget=None):
    row = fields(line)
    required = dict(HARD_OFF='1', MOTOR_QUALIFIED='0', RAW='VALIDITY_ONLY', FILTERED='2_OF_3', GUARD_US='25')
    if running: required.update(STATE='0', REASON='0', FLAGS='0', ARMED='1', ZERO='1')
    if repair_budget is not None:
        required.update(REPAIR_MAX=str(repair_budget[0]),STREAK_MAX=str(repair_budget[1]))
    if any(row.get(k) != v for k,v in required.items()): raise RuntimeError('Guardian not healthy: '+line)
    return row

def timing(line):
    row = fields(line)
    if any(row.get(k) != v for k,v in dict(MOTOR_QUALIFIED='0',CLOCK_HZ='1000000',
            SCOPE='PAIR_CHECK_TO_FOC_END',LATE='0',BUDGET_US='50',TEST_USED='0').items()):
        raise RuntimeError('Wrong/late compute timing')
    if int(row.get('N','0')) <= 0 or not 0 <= int(row.get('MAX_US','50')) < 50:
        raise RuntimeError('No within-period timing evidence')
    return row

def fault_fields(line):
    # Legacy generic fields() excludes digits and therefore cannot read CR1.
    pairs = re.findall(r'\b([A-Z][A-Z0-9_]*)=([^\s]+)', line)
    fault = dict(pairs)
    if len(fault) != len(pairs): raise RuntimeError('Duplicate fault field')
    return fault

def timeout_result(state_line, fault_line, timing_line):
    state = protection(state_line, running=False); t = fields(timing_line)
    fault = fault_fields(fault_line)
    if any(state.get(k) != v for k,v in dict(STATE='2',REASON='6',ARMED='0',ZERO='0').items()):
        raise RuntimeError('Not a latched independent timeout')
    if any(fault.get(k) != v for k,v in dict(VALID='1',REASON='6',SD='0',MOTOR_QUALIFIED='0').items()):
        raise RuntimeError('No preserved timeout shutdown snapshot')
    if (int(fault['BDTR'],16)&0xC000 or int(fault['CCER'],16) or int(fault['CR1'],16)&1 or
            t.get('TEST_USED') != '1'):
        raise RuntimeError('Output shutdown/test mismatch')
    delay = (int(fault['OFF_US'])-int(fault['LAST_VALID_US'])) & 0xFFFFFFFF
    if not 100 < delay <= 175 or int(fault['GUARD_IRQ']) <= 0:
        raise RuntimeError('Independent timeout response outside diagnostic bound')
    # 175 us is this diagnostic acceptance bound, not verified hardware safety.
    return dict(state=state, fault=fault, timing=t, register_mark_delay_us=delay,
                physical_shutdown_timing_verified=False, motor_qualified=False)

def rollback(original, actual, data, profile=staging):
    old, new = latest_meta(original), latest_meta(actual)
    if new[2:6] != (1,0,0,profile.GEN+4) or new[8:10] != (0,0):
        raise RuntimeError('Not the existing bootloader exhausted B trial rollback')
    if old[6:8] != new[6:8] or actual[0x40000:0x40000+len(data)] != data:
        raise RuntimeError('Fallback metadata or staged bytes changed')
    for start,end in ((0,0x40000),(0x78000,0x7e800),(0x7f800,0x80000)):
        if original[start:end] != actual[start:end]: raise RuntimeError('Protected rollback region changed')
    return dict(current='A',generation=new[5],protected_regions_unchanged=True)

def main(profile=staging):
    staging=profile
    repair_budget=getattr(profile,'REPAIR_BUDGET',None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-evidence', required=True, type=Path)
    parser.add_argument('--powered-open-load-ready', action='store_true')
    args = parser.parse_args()
    if not args.powered_open_load_ready: parser.error('Powered sensing and disconnected motor required')
    original = stage_evidence(args.stage_evidence,profile); data = staging.image()
    run = str(time.time_ns()); target = staging.OUTPUT/f'commit-{run}.json'
    record = dict(pass_=False, image_sha256=staging.SHA, motion_commands=False,
                  bridge_enabled=False, force_confirm=False, motor_qualified=False,
                  host_retry=False, automatic_bootloader_attempts_possible=2, steps=[])
    port = uart = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only SWD')
        p = subprocess.run([CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+SN,*map(str,tokens)],
                           capture_output=True,text=True,errors='replace',timeout=30)
        out=p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read failed; no reset/retry')
        return out
    def capture(name):
        p=staging.OUTPUT/'private'/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',p)
        raw=p.read_bytes()
        if len(raw)!=0x80000: raise RuntimeError('Incomplete Flash capture')
        record[name+'_backup']=str(p); return raw
    def outputs(slot):
        return require_registers(cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    try:
        record['precommit_flash']=compare_flash(original,capture('precommit'),data,'B',staged=True)
        record['precommit_outputs']=outputs('A')
        import serial
        port=serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=Console(port)
        staging.require_staged(uart.query('FW STATUS'),staging.GEN,data)
        # FW ACTIVE gates diagnostic queries. Exact known hard-OFF A449,
        # full protected-byte comparison and fresh SD/MOE/AOE/CCER/CEN SWD
        # proof above qualify precommit OFF without modifying the app gate.
        record['precommit_output_proof_source']='INDEPENDENT_SWD'
        record['commit_attempted']=True
        try: record['commit_reply']=uart.command('FW END',20)
        except TimeoutError: record['commit_ack_uncertain']=True # Never resend.
        end=time.monotonic()+OBSERVE_SECONDS; seen=False; generations=set(); rolled_back=False
        while time.monotonic()<end:
            try: fw=fields(uart.query('FW STATUS',.5))
            except TimeoutError: continue
            record['last_fw']=fw
            if fw.get('CURRENT')=='B':
                seen=True
                # Once this generation's sticky fault and OFF state have been
                # captured/stopped, observe FW only until normal rollback.
                if fw.get('GEN') not in generations:
                    if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('B lock absent')
                    p=fields(uart.query('BENCH PROTECTION'))
                    if p.get('STATE')=='2':
                        generations.add(fw.get('GEN'))
                        record.setdefault('trial_faults',[]).append(dict(fw=fw,protection=p,
                            fault=fault_fields(uart.query('BENCH PROTECTION FAULT')),
                            timing=fields(uart.query('BENCH PROTECTION TIMING'))))
                        require_stopped(uart.query('BENCH STOP'))
                if confirmed(fw,'B'): break
            elif confirmed(fw,'A') and (seen or int(fw.get('GEN','0'))>staging.GEN):
                rolled_back=True; break
            uart.poll(OBSERVE_POLL_SECONDS)
        else: raise TimeoutError('No normal confirmation/rollback; no forced confirmation')
        if rolled_back:
            record['rollback_flash']=rollback(original,capture('rollback'),data,profile)
            record['final_outputs']=outputs('A')
            require_stopped(uart.query('BENCH STATUS'))
            record['failure']='B rejected by normal health gate; rolled back to locked A'
            print('GUARDIAN DIAGNOSIS FAIL: normal rollback to locked A; no motion.',flush=True)
            return
        record['confirmed_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        if record.get('trial_faults'): raise RuntimeError('Trial fault observed; no pass')
        record['zero']=require_zero(uart.query('BENCH ZERO'))
        record['before_protection']=before=protection(uart.query('BENCH PROTECTION'),repair_budget=repair_budget)
        record['before_timing']=timing(uart.query('BENCH PROTECTION TIMING'))
        start=time.monotonic()
        while time.monotonic()-start<1.0: uart.poll(.04)
        record['after_protection']=after=protection(uart.query('BENCH PROTECTION'),repair_budget=repair_budget)
        record['after_timing']=timing(uart.query('BENCH PROTECTION TIMING'))
        elapsed=time.monotonic()-start
        if int(after['IRQ'])<=int(before['IRQ']) or int(after['FEEDBACK_N'])<=int(before['FEEDBACK_N']):
            raise RuntimeError('No independent guard/feedback progress')
        record['diagnostic_feedback_rate_hz']=(int(after['FEEDBACK_N'])-int(before['FEEDBACK_N']))/elapsed
        if not 18000 <= record['diagnostic_feedback_rate_hz'] <= 22000:
            raise RuntimeError('Diagnostic compute rate failed')
        record['stacks']=fields(uart.query('BENCH STACK'))
        if any(int(record['stacks'].get(k,'0'))<256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
            raise RuntimeError('Task stack margin failed')
        record['injection_reply']=uart.query('BENCH PROTECTION TEST TIMEOUT')
        until=time.monotonic()+.02
        while time.monotonic()<until: uart.poll(.002)
        record['timeout_result']=timeout_result(uart.query('BENCH PROTECTION'),
            uart.query('BENCH PROTECTION FAULT'),uart.query('BENCH PROTECTION TIMING'))
        require_stopped(uart.query('BENCH STATUS'))
        record['final_outputs']=outputs('B')
        record['final_flash']=compare_flash(original,capture('final'),data,'B')
        record['final_fw']=require_confirmed(uart.query('FW STATUS'),'B')
        record['pass_']=True
        print('HARD-OFF GUARDIAN PASS: FOC progress and independent timeout register shutdown; NOT motor qualification.',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart and record.get('commit_attempted'):
            try:
                fw=fields(uart.query('FW STATUS')); slot=fw.get('CURRENT')
                if slot in ('A','B'):
                    if slot=='B': record['cleanup_fault']=fault_fields(uart.query('BENCH PROTECTION FAULT'))
                    require_stopped(uart.query('BENCH STOP'))
                    if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Final lock absent')
                    record['cleanup_outputs']=outputs(slot); record['final_safe_locked']=True
            except BaseException as error:
                record['pass_']=False; record['cleanup_failure']=str(error)
                print('Final state unverified; keep motor disconnected: '+str(error),flush=True)
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__=='__main__': main()

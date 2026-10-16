"""Read-only closeout of the exact rejected B guardian trial; never reset.

This does not turn the failed trial into a pass. It separately verifies the
normal A rollback, protected Flash and output registers. No sampling command.
"""
import json
import subprocess
import time
from pathlib import Path
import feedback_safety_stage as staging
from feedback_safety_commit import Console, stage_evidence, rollback
from zero_retest_deploy import CLI, SN, require_confirmed
from zero_span100_acceptance import ADDRESSES, require_registers
from tighten_synthetic_acceptance import locked, require_stopped
from firmware_transfer_iap import fields

PRIOR = staging.OUTPUT / 'commit-1791888174546226000.json'
STAGE = staging.OUTPUT / 'stage-audit-1791887912313022000.json'
READ = frozenset(('FW STATUS', 'BENCH STATUS', 'ANALOG SAFE STATUS'))

def prior_failure(row):
    if (row.get('pass_') is not False or row.get('image_sha256') != staging.SHA or
            row.get('failure') != 'No normal confirmation/rollback; no forced confirmation' or
            row.get('cleanup_failure') != 'No ACK; no resend: FW STATUS' or
            row.get('commit_attempted') is not True or row.get('motion_commands') is not False or
            row.get('bridge_enabled') is not False or row.get('force_confirm') is not False):
        raise RuntimeError('Only the exact rejected diagnostic trial admitted')
    trials = row.get('trial_faults', [])
    if len(trials) != 2 or any(t['protection'].get('REASON') != '9' for t in trials):
        raise RuntimeError('Missing both preserved repair-budget faults')

class ReadConsole(Console):
    def command(self, *args, **kwargs):
        raise ValueError('Read-only rollback audit')
    def query(self, text, timeout=3):
        if text not in READ: raise ValueError('No sampling/reset/stop/commit')
        return super().query(text, timeout)

def main():
    prior_failure(json.loads(PRIOR.read_text('utf-8')))
    original = stage_evidence(STAGE); data = staging.image()
    run = str(time.time_ns())
    target = staging.OUTPUT / f'rollback-audit-{run}.json'
    record = dict(pass_=False, read_only_closeout=True, prior_trial_pass=False,
                  prior_evidence=str(PRIOR), image_sha256=staging.SHA,
                  resets=0, activation=False, motion_commands=False,
                  sampling_commands=False, motor_qualified=False, steps=[])
    port = uart = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u', '-r32'): raise ValueError('Read-only SWD')
        p = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000',
                            'sn='+SN, *map(str,tokens)], capture_output=True,
                           text=True, errors='replace', timeout=30)
        out = p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read failed; no reset/retry')
        return out
    try:
        path = staging.OUTPUT/'private'/f'{run}-rollback-audit.bin'
        cli('-u','0x08000000','0x80000',path)
        actual = path.read_bytes()
        if len(actual) != 0x80000: raise RuntimeError('Incomplete private Flash capture')
        record['rollback_backup'] = str(path)
        record['rollback_flash'] = rollback(original, actual, data)
        record['outputs'] = require_registers(
            cli(*(x for a in ADDRESSES for x in ('-r32',hex(a),'4'))), 'A')
        import serial
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=ReadConsole(port)
        fw = require_confirmed(uart.query('FW STATUS'),'A')
        if fw.get('GEN') != str(staging.GEN+4): raise RuntimeError('Unexpected generation')
        record['fw'] = fw
        line = uart.query('BENCH STATUS'); require_stopped(line)
        record['bench'] = fields(line)
        record['safe'] = fields(uart.query('ANALOG SAFE STATUS'))
        if not locked(record['safe']): raise RuntimeError('Final output lock absent')
        record['pass_'] = True
        print('ROLLBACK CLOSEOUT PASS: confirmed locked A; B trial still FAIL.',flush=True)
    except BaseException as error:
        record['failure']=str(error); raise
    finally:
        if uart: record['uart']=uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__ == '__main__': main()

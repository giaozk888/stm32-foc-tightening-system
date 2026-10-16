"""Read-only completion analysis after the SPD/SPEED host assertion error.

No firmware activation/reset, Flash writing, sampling or test commands. The
original failed runner receipt is preserved, not relabeled as full PASS.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path
import serial
import control_chain_reconnect_acceptance as live

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-evidence', type=Path, required=True)
    args = parser.parse_args()
    path = args.trial_evidence.resolve()
    if path.parent != live.OUTPUT.resolve(): raise RuntimeError('Exact evidence directory required')
    receipt = json.loads(path.read_text('utf-8'))
    if (receipt.get('image_sha256') != live.SHA or receipt.get('failure') != 'No original speed PI to Iq execution evidence' or
        receipt.get('confirmed_fw', {}).get('GEN') != '466' or not receipt.get('final_safe_locked')):
        raise RuntimeError('Only the saved host-spelling-error receipt can be analyzed')
    data = live.image()
    original, _ = live.stage_evidence(Path(receipt['stage_evidence']), data)
    run = str(time.time_ns()); target = live.OUTPUT/f'readback-{run}.json'
    record = dict(readback_pass=False, full_acceptance_pass=False, motor_qualified=False,
                  mutation_commands=False, resets=0, flash_writes=0,
                  independent_timeout_test_executed=False, tightening_stack_measured=False,
                  original_trial_receipt=str(path), steps=[])
    record['chain_result'] = live.original_chain_result(receipt['chain_observations'], receipt['chain_final'])
    port = uart = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only probe')
        p = subprocess.run([live.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000','sn='+live.SN,
            *map(str,tokens)], capture_output=True,text=True,errors='replace',timeout=30)
        out = p.stdout+p.stderr
        record['steps'].append(dict(args=list(map(str,tokens)),code=p.returncode,output=out))
        if p.returncode or 'Error:' in out: raise RuntimeError('Read-only probe failed')
        return out
    try:
        record['registers'] = live.require_registers(cli(*(x for a in live.ADDRESSES for x in ('-r32',hex(a),'4'))),'A')
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr=port.rts=False; port.port='COM5'; port.open(); uart=live.Console(port)
        record['fw'] = live.require_confirmed(uart.query('FW STATUS'),'A')
        if record['fw'].get('GEN') != '466': raise RuntimeError('Generation changed')
        record['chain_now'] = current = live.chain(uart.query('BENCH CHAIN STATUS'))
        if current.get('ACTIVE') != '0' or current.get('USED') != '1': raise RuntimeError('Chain was restarted/lost')
        record['status'] = uart.query('STATUS')
        record['timing'] = live.timing(uart.query('BENCH PROTECTION TIMING'))
        record['stacks'] = stacks = live.fields(uart.query('BENCH STACK'))
        if any(int(stacks.get(k,'0')) < 256 for k in ('MOTOR','ROUTER','PROTO','TRANSFER')):
            raise RuntimeError('Reported task stack margin failed')
        record['protection'] = p = live.protection(uart.query('BENCH PROTECTION'), running=False,repair_budget=(6,4))
        if any(p.get(k) != v for k,v in dict(STATE='0',REASON='0',FLAGS='0',ARMED='0').items()):
            raise RuntimeError('Not fault-free/disarmed after completed chain')
        record['fault'] = f = live.fault_fields(uart.query('BENCH PROTECTION FAULT'))
        if f.get('VALID') != '0': raise RuntimeError('Sticky fault exists')
        record['bench'] = uart.query('BENCH STATUS'); live.require_stopped(record['bench'])
        if not live.locked(live.fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Latch absent')
        backup = live.OUTPUT/'private'/f'{run}-final.bin'; cli('-u','0x08000000','0x80000',backup)
        record['final_backup'] = str(backup)
        record['flash'] = live.compare_flash(original,backup.read_bytes(),data,'A')
        if record['flash']['generation'] != 466: raise RuntimeError('Flash/UART mismatch')
        record['readback_pass'] = True
        print('READBACK PASS: original control tasks completed, hard-OFF, image/protected regions exact.',flush=True)
        print('Independent stopped-ADC injection NOT executed this boot; not full acceptance or motor qualification.',flush=True)
    except BaseException as error:
        record['failure'] = str(error); raise
    finally:
        if uart: record['uart'] = uart.lines
        if port: port.close()
        target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(target),flush=True)

if __name__ == '__main__': main()

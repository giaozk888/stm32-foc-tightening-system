"""Offline summary of the one pinned ComputeOnly trial's private RAM capture.

No hardware access. Layout is pinned to this exact ELF/map and FreeRTOS build;
only validated numeric/stack results are printed, never arbitrary RAM contents.
"""
import json
import argparse
import hashlib
import math
from pathlib import Path
import statistics
import struct
import fast_current_reject_board_test as board

TRIAL=board.OUTPUT/'fast-reject-trial-1792149041071958600.json'


def pair_distribution(path):
    """Offline adjacent RAW-pair statistics, never filtered/selected samples.

    Includes the impulses and their return edges. A quiet subset selected by
    the jump gate is explicitly conditional, NOT a labelled normal dataset.
    Neither dataset qualifies thresholds under real running motor current.
    """
    raw=path.read_bytes()
    row=json.loads(raw)
    pairs=row['samples']
    if (row.get('pass_') is not True or len(pairs)<2 or
            any(len(p)!=2 or any(type(x) is not int or not 0<=x<=4095 for x in p) for p in pairs)):
        raise ValueError('Successful, complete 12-bit U/V raw capture required')
    if int(row['capture']['N'])!=len(pairs):
        raise ValueError('Capture count mismatch')
    def distance(a,b): return max(abs(a[0]-b[0]),abs(a[1]-b[1]))
    def distribution(values):
        values=sorted(values)
        if not values: raise ValueError('Empty distribution')
        return dict(n=len(values),median=statistics.median(values),
            p95=values[math.ceil(len(values)*.95)-1],
            p99=values[math.ceil(len(values)*.99)-1],
            p99_9=values[math.ceil(len(values)*.999)-1],maximum=values[-1])
    adjacent=[distance(a,b) for a,b in zip(pairs,pairs[1:])]
    return dict(source=str(path),sha256=hashlib.sha256(raw).hexdigest(),
        pairs=len(pairs),quantile='nearest-rank; median arithmetic',
        all_adjacent=distribution(adjacent),
        conditional_adjacent_le_jump60=distribution([x for x in adjacent if x<=60]),
        adjacent_le20=sum(x<=20 for x in adjacent),
        limitation='Unlabelled output-off capture, not normal/running-current calibration')


def summarize():
    receipt=json.loads(TRIAL.read_text('utf-8'))
    if receipt.get('image_sha256')!=board.SHA or not receipt.get('final_cpu_halted'):
        raise ValueError('Exact stopped ComputeOnly image required')
    path=board.transaction.prior.private_path(receipt['ram_backup'])
    ram=path.read_bytes()
    if len(ram)!=0x20000: raise ValueError('Full RAM required')
    def word(address):
        if address&3 or not 0x20000000<=address<=0x2001fffc:
            raise ValueError('Invalid SRAM word address')
        return struct.unpack_from('<I',ram,address-0x20000000)[0]
    # sizeof(FocFeedbackSafety)=248; validation @208, raw_trip_counts @244.
    base=0x20005a98+208
    counts=struct.unpack_from('<7I2HB',ram,base-0x20000000)
    stats=receipt['current_validation'][-1]
    if tuple(map(int,(stats['samples'],stats['invalid'],stats['isolated'],
            stats['two_sample_runs'],stats['three_plus_runs'],stats['run'],stats['max_run'])))!=counts[:7]:
        raise ValueError('Validation layout does not agree with UART')
    result=dict(trial=str(TRIAL),samples=counts[0],invalid=counts[1],
        invalid_percent=100*counts[1]/counts[0],isolated_runs=counts[2],
        two_sample_runs=counts[3],three_plus_runs=counts[4],
        last_valid_u=counts[7],last_valid_v=counts[8],last_invalid=counts[9],
        normal_max_us=int(stats['normal_max_cycles'])/170,
        invalid_max_us=int(stats['invalid_max_cycles'])/170,
        all_path_max_us=int(stats['max_cycles'])/170,
        deadline_miss=int(stats['deadline_miss']),stacks=[])
    raw_u,raw_v=map(int,receipt['sample']['fault']['RAW'].split(','))
    result.update(fault_raw_u=raw_u,fault_raw_v=raw_v,
        fault_delta_u=raw_u-counts[7],fault_delta_v=raw_v-counts[8])
    lists=[0x2000b608,0x2000b620,0x2000b634,0x2000b650,0x2000b664]
    lists.extend(0x2000b678+20*i for i in range(8))
    owners=set()
    for header in lists:
        length=word(header)
        if length>32: raise ValueError('Invalid task list length')
        end=header+8
        node=word(header+12)
        for _ in range(length):
            if node==end or word(node+16)!=header:
                raise ValueError('Invalid task state list link')
            owners.add(word(node+12))
            node=word(node+4)
        if node!=end: raise ValueError('Task list did not terminate')
    owners.add(word(0x2000b718))
    if len(owners)!=word(0x2000b604): raise ValueError('Incomplete task enumeration')
    for tcb in sorted(owners):
        name=ram[tcb-0x20000000+52:tcb-0x20000000+68].split(b'\0')[0].decode('ascii')
        start=word(tcb+48)
        if not (0x20000000<=start<0x2001ffc0 and re_name(name)):
            raise ValueError('Unexpected task/stack allocation')
        at=start-0x20000000
        top=word(tcb)
        if not start<top<0x2001ffc0: raise ValueError('Invalid saved stack pointer')
        limit=top-start
        free=0
        while free<limit and ram[at+free]==0xa5: free+=1
        result['stacks'].append(dict(task=name,untouched_stack_bytes=free,
            watermark_bounded=free<limit))
    return result


def re_name(name):
    # Bounded printable identifiers from validated task-list owners only.
    return bool(name) and len(name)<=15 and all(c.isalnum() or c in '_-' for c in name)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-distribution',type=Path,action='append')
    args=parser.parse_args()
    if args.pair_distribution:
        row=[pair_distribution(p) for p in args.pair_distribution]
    else:
        row=summarize()
        output=board.OUTPUT/'fast-reject-measurement-summary.json'
        output.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(row,ensure_ascii=False,indent=2))

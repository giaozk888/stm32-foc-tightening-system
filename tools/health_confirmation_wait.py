"""Read-only, bounded wait across the application's health-confirmation reset.

This helper never activates, resets, confirms, clears a fault or starts a motor.
Only read ACK timeouts during startup are recoverable. Once it returns, normal
runtime collection retains its existing fail-on-timeout policy.
"""
import time


class StartupFault(RuntimeError):
    """A reported application fault, not a transient missing read ACK."""


def wait_health_confirmation(uart, row, fields, *, timeout=60.0, clock=None):
    clock = clock or time.monotonic
    if timeout <= 0:
        raise ValueError('Positive confirmation timeout required')
    started = clock()
    deadline = started + timeout  # Never extended by a reset or missing ACK.
    stats = dict(policy='bounded-read-only-confirm-reset', timeout_seconds=timeout,
                 read_timeout_count=0, fw_timeout_count=0, state_timeout_count=0,
                 generation_rechecks=0, confirmed=False)
    row['health_wait'] = stats
    # A prior receipt/status must never count as confirmation of this wait.
    row.pop('normally_confirmed', None)

    def remaining():
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError('Normal A health confirmation absent within startup deadline')
        return left

    def read(command):
        budget = min(.6, remaining())
        try:
            result = uart.query(command, budget)
        except TimeoutError:
            stats['read_timeout_count'] += 1
            key = 'fw_timeout_count' if command == 'FW STATUS' else 'state_timeout_count'
            stats[key] += 1
            return None
        remaining()  # Do not accept a late reply after the absolute deadline.
        return fields(result)

    def check_fw(fw):
        row['last_fw'] = fw
        if fw.get('CURRENT') == 'B' and fw.get('PENDING') == '-':
            raise RuntimeError('Probe A rolled back/rejected; no retry')

    def confirmed(fw):
        return (all(fw.get(k) == v for k, v in
                    (('CURRENT', 'A'), ('CONFIRMED', 'A'), ('PENDING', '-'),
                     ('ATTEMPTS', '0'), ('ACTIVE', '0'))) and
                fw.get('GEN', '').isdigit())

    try:
        while True:
            fw = read('FW STATUS')
            if fw is not None:
                check_fw(fw)
                if fw.get('CURRENT') == 'A':
                    state = read('MOTOR TEST STATUS')
                    if state is not None:
                        row['last_state'] = state
                        if state.get('STATE') == '4':
                            raise StartupFault('Probe startup/runtime fault; no retry')
                        if any(state.get(k) != '0' for k in
                               ('SD', 'MOE', 'CCER', 'FLAGS', 'FAULT')):
                            raise RuntimeError('Startup fault or outputs not locked; no retry')
                        if confirmed(fw) and state.get('STATE') == '1' and state.get('ZERO') == '3':
                            # Do not combine pre-reset FW with post-reset state. The
                            # second FW reply must still describe the same confirmed
                            # metadata generation. Request IDs reject stale ACKs in
                            # Console.query; no serial buffer/log evidence is erased.
                            after = read('FW STATUS')
                            if after is not None:
                                check_fw(after)
                                if confirmed(after) and after['GEN'] == fw['GEN']:
                                    row['normally_confirmed'] = True
                                    stats['confirmed'] = True
                                    stats['confirmed_generation'] = after['GEN']
                                    return
                                stats['generation_rechecks'] += 1
            # Poll even after immediate/no-app replies, avoiding an unbounded
            # busy spin. Only the original startup deadline governs this wait.
            uart.poll(min(.02, remaining()))
    finally:
        stats['elapsed_seconds'] = clock() - started

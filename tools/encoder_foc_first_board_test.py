"""Pinned hard-OFF EncoderFocFirst A trial; offline by default; never START."""
import json
import sys
import deadline_attribution_board_test as previous
import encoder_foc_first_report as report

pipeline, base = previous.pipeline, previous.base
ROOT, OUTPUT, PRIVATE = previous.ROOT, previous.OUTPUT, previous.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/EncoderReview/EncoderFocFirst/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '05457edae53ac0be14d702c24a8a99857f4b2d6c2df28fa8a5eb47c1a10a2b75'
ELF_SHA = 'ed504711d5bd424178584c89d5172f405cb1bea75ee91b69a6b38f6f70446ecc'
SIZE = 228964
PREFIX = 'encoder-foc-first-'
BASE_RECEIPT = OUTPUT/'deadline-attribution-restore-1792220106010424600.json'
BASE_SHA = '9d34055faf1a5f5ac3cc2586cf396afda8605129a1697fa6224b9baf70879f5b'
BASE_META = (1112493908,3,2,0,0,604,229348,1849918931,210916,453748590,0,1109670601)
_sample = base.prior.sample


def sample(uart):
    result = _sample(uart)
    result['encoder'] = base.prior.fields(uart.query('ENC DIAG'))
    return result


def image():
    data = IMAGE.read_bytes()
    receipt = json.loads((ROOT/'tests/foc_adaptive_build/encoder_foc_first_evidence/receipt.json').read_text())
    if (len(data) != SIZE or base.tx.digest(data) != SHA or
        base.tx.digest(ELF.read_bytes()) != ELF_SHA or base.prior.image_info(data)[0] != 'A' or
        receipt.get('hardware_access') is not False or receipt.get('test_count') != 127 or
        not any(b.get('app') == 'foc2_app_a' and b.get('profile') == 'EncoderFocFirst' and
            b.get('bin_sha256') == SHA and b.get('elf_sha256') == ELF_SHA for b in receipt['builds'])):
        raise ValueError('Exact offline-tested EncoderFocFirst A BIN/ELF/receipt required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1', b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4', b'PWM COMMIT', b'HYPOTHETICAL PWM',
                   b'SERVICE_WALL_INCLUDING_CHILDREN'):
        if marker not in data:
            raise ValueError('Missing hard-off/attribution identity')
    return data


def configure():
    values = {k: globals()[k] for k in ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX',
                                       'BASE_RECEIPT','BASE_SHA','BASE_META')}
    for module in (previous,pipeline,base,base.confirm,base.confirm.base,base.old,base.prior,base.tx):
        for key, value in values.items(): setattr(module, key, value)
        module.image = image
    base.report = report
    base.verify = verify
    base.decode = decode
    base.configure = configure
    base.prior.sample = sample


def verify():
    previous.verify()
    symbols = report.previous.pipeline.base.schema.symbols(ELF)
    for name in ('TIM6_DAC_IRQHandler', 'encoder_deferred_service_count',
                 'encoder_timer_event_count', 'encoder_rx_event_count', 'encoder_period_count'):
        if name not in symbols: raise ValueError('Missing deferred encoder symbol: ' + name)


def acceptance_failure(p):
    if not p['encoder_priority_verified']:
        return 'Encoder/ADC priority inventory invalid'
    if p['timing']['preempt_max_us'] != 0:
        return 'Unexpected ADC preemption attribution'
    e = p['encoder_events']
    if (not e['deferred_service_count'] or not e['rx_event_count'] or
        not e['period_count'] or e['tx_error_count']):
        return 'Deferred encoder acquisition absent or TX error present'
    return None


def decode(row, data):
    previous.decode(row, data)
    p = row.get('preempt_commit')
    if not p: return
    reason = acceptance_failure(p)
    row['encoder_foc_first_acceptance_failure'] = reason
    row['encoder_foc_first_pass'] = bool(row['pass_'] and reason is None)
    if row['pass_'] and reason: row.update(pass_=False, failure=reason)


def main():
    configure()
    if len(sys.argv) == 1:
        image(); verify()
        print('OFFLINE PASS: pinned EncoderFocFirst A / B604 fallback / no devices')
        return 0
    return base.main()


if __name__ == '__main__': raise SystemExit(main())

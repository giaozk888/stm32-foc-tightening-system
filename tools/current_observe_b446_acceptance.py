"""Re-run the pinned hard-off real-feedback FOC fixture from exact B446.

Reuses the reviewed official UART stage/one-commit/normal-health path.
Stage requires physical drive OFF; commit is separate after sensing supply
is ready and motor U/V/W remain disconnected. No motor START or bridge.
Historical tools and evidence retain their original baseline pins.
"""
import current_observe_acceptance as observe
from switch_trend_compare_deploy import SHA as FALLBACK_SHA
from zero_async_clock_acceptance import locked_baseline

OUTPUT=observe.ROOT/'safety_backups/current-observe-b446-20261013'
GEN=446

def baseline(data):
    row=locked_baseline(data,known={'A':frozenset((observe.SHA,)),
                                    'B':frozenset((FALLBACK_SHA,))})
    if row['current']!='B' or row['generation']!=GEN:
        raise RuntimeError('Only exact confirmed B446 and pinned hard-off A admitted')
    return row

def configure():
    # Only this fresh process adapts the reviewed runner to today's exact
    # normally confirmed baseline. No image or firmware protection changes.
    observe.GEN=GEN
    observe.OUTPUT=OUTPUT
    observe.baseline=baseline

def main():
    configure()
    observe.main()

if __name__=='__main__': main()

#include "telemetry_history.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main()
{
    telemetry_history::History history;
    assert(history.empty());
    assert(history.accept({0, -40, 0, 65535}));
    assert(history.accept({100, -35, 1, 0}));  // 16-bit sequence rollover.
    assert(!history.accept({200, -30, 2, 0})); // Duplicate.
    assert(!history.accept({200, -30, 2, 65535})); // Backward sequence.
    assert(!history.accept({50, -30, 2, 1})); // Regressing monotonic time.
    assert(history.samples().size() == 2);
    assert(history.accept({30101, 100, 20, 1}));
    assert(history.samples().size() == 1); // Older than the 30 s window.
    assert(history.samples().front().angleMdeg == 100);
    for (std::uint16_t seq = 2; seq < 610; ++seq) {
        assert(history.accept({30101 + seq, seq, 0, seq}));
    }
    assert(history.samples().size() == telemetry_history::kMaxSamples);
    history.clear();
    assert(history.empty());
    assert(history.accept({0, 0, 0, 1})); // A new STM32 run may restart sequence.
}

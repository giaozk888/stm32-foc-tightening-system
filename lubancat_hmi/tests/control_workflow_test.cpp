#include "control_workflow.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

using namespace control_workflow;

static Evidence ready()
{
    Evidence in;
    in.canUp = true;
    in.statusFresh = true;
    in.motorFresh = true;
    in.electricalFresh = true;
    in.status = {0U, 0x0DU, 0U, 10U};
    in.motor = {0, 0, 10U};
    in.electrical = {12000U, 0, 10U, true, true};
    in.firmwareControlVerified = true;
    in.estopFeedbackReleased = true;
    in.powerStageFeedbackReady = true;
    in.recipeVerified = true;
    in.sensingVerified = true; // Synthetic policy fixture, not physical acceptance.
    return in;
}

int main()
{
    auto in = ready();
    assert(missing(in) == 0U);
    in.sensingVerified = false;
    assert(missing(in) == VerifiedSensing);
    in = ready();
    in.firmwareControlVerified = false;
    assert(missing(in) == FirmwareControl);
    in = ready();
    in.estopFeedbackReleased = false;
    assert(missing(in) == EstopFeedback);
    in = ready();
    in.powerStageFeedbackReady = false;
    assert(missing(in) == PowerFeedback);
    in = ready();
    in.electrical.sequence = 9U;
    assert((missing(in) & FreshTelemetry) != 0U);
    in = ready();
    in.status.flags = 0x0FU;
    assert((missing(in) & SoftwareHealthy) != 0U);
    in = ready();
    in.electrical.speedDeciRpm = 21;
    assert((missing(in) & IdleAndStationary) != 0U);

    Transaction tx;
    std::array<std::uint8_t, 8> bytes{};
    CanControlV0_Request arm{CAN_CONTROL_V0_ARM, 1U, 7U, 1U};
    assert(!tx.begin(arm, 1000, 10U, FirmwareControl, bytes));
    assert(tx.phase() == Phase::Locked);
    assert(tx.begin(arm, 1000, 10U, 0U, bytes));
    assert(bytes[0] == 1U && bytes[1] == CAN_CONTROL_V0_ARM);
    CanControlV0_Reply reply{CAN_CONTROL_V0_ARM, 2U, CAN_CONTROL_V0_ARMED, 0U, 7U};
    assert(!tx.accept(reply, 1100));
    reply.sequence = 1U;
    assert(tx.accept(reply, 1100));
    assert(tx.phase() == Phase::IntentAccepted);

    CanControlV0_Request start{CAN_CONTROL_V0_START, 2U, 7U, 1U};
    assert(tx.begin(start, 1200, 10U, 0U, bytes));
    reply = {CAN_CONTROL_V0_START, 2U, CAN_CONTROL_V0_START_INTENT, 0U, 7U};
    assert(tx.accept(reply, 1250));
    assert(tx.phase() == Phase::IntentAccepted);
    auto status = in.status;
    status.mode = 2U;
    tx.observe(status, true);
    assert(tx.phase() == Phase::IntentAccepted); // Old status cannot prove execution.
    status.sequence = 11U;
    tx.observe(status, true);
    assert(tx.phase() == Phase::RunningObserved); // Observation, not cycle result.

    CanControlV0_Request stop{CAN_CONTROL_V0_STOP, 3U, 0U, 0U};
    assert(tx.begin(start, 1300, 11U, 0U, bytes));
    assert(tx.begin(stop, 1310, 11U, FreshTelemetry | SoftwareHealthy, bytes));
    reply = {CAN_CONTROL_V0_STOP, 3U, CAN_CONTROL_V0_STOP_INTENT, 2U, 0U};
    assert(tx.accept(reply, 1320));
    status.mode = 0U;
    status.sequence = 12U;
    tx.observe(status, true);
    assert(tx.phase() == Phase::IdleObserved);

    assert(tx.begin(start, 2000, 12U, 0U, bytes));
    tx.tick(2501);
    assert(tx.phase() == Phase::TimedOut);
    assert(tx.stopRecommended());
    assert(!tx.accept({CAN_CONTROL_V0_START, 2U,
                       CAN_CONTROL_V0_START_INTENT, 0U, 7U}, 2502));
    tx.lock();
    assert(tx.phase() == Phase::Locked);
    assert(!tx.begin(stop, 3000, 12U, FirmwareControl, bytes));

    assert(tx.begin(start, 4000, 12U, 0U, bytes));
    reply = {CAN_CONTROL_V0_START, 2U, CAN_CONTROL_V0_START_INTENT, 0U, 7U};
    assert(tx.accept(reply, 4050));
    tx.tick(4100, false);
    assert(tx.phase() == Phase::LinkLost && tx.stopRecommended());
    assert(tx.begin(start, 5000, 12U, 0U, bytes));
    assert(tx.accept(reply, 5050));
    tx.tick(6501);
    assert(tx.phase() == Phase::TimedOut && tx.stopRecommended());
}

#include "can_log_receiver.h"
#include "pigweed_log.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cstring>

int main()
{
    assert(CanLog_Crc16(reinterpret_cast<const uint8_t *>("123456789"), 9) == 0x29b1);
    const std::string text = "[PW][42][123ms][INFO][TEST] can log";
    const auto *bytes = reinterpret_cast<const uint8_t *>(text.data());
    uint8_t header[8], data[8];
    assert(CanLog_EncodeStart(65535, 1, bytes, text.size(), header));
    can_log::Receiver receiver;
    assert(!receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 0));
    std::optional<can_log::Complete> result;
    for (unsigned i = 0; i * 5 < text.size(); ++i) {
        assert(CanLog_EncodeData(65535, uint8_t(i), bytes, text.size(), data));
        result = receiver.feed(CAN_LOG_DATA_ID, false, false, false, 8, data, 100 + i * 100);
    }
    assert(result && result->text == text && result->sessionStart);
    pigweed_log::Record record;
    assert(pigweed_log::parse(result->text, record) && record.sequence == 42);
    assert(!receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 1000)); // Duplicate.
    assert(!receiver.feed(CAN_LOG_START_ID, true, false, false, 8, header, 1000));
    assert(receiver.invalid() == 1);
    assert(CanLog_EncodeStart(0, 0, bytes, text.size(), header)); // Transport ID wrap.
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 2000);
    CanLog_EncodeData(0, 1, bytes, text.size(), data); // Missing fragment zero.
    assert(!receiver.feed(CAN_LOG_DATA_ID, false, false, false, 8, data, 2100));
    assert(receiver.incomplete() == 1);
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 2200);
    receiver.expire(12201);
    assert(receiver.incomplete() == 2);
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 13000);
    for (unsigned i = 0; i * 5 < text.size(); ++i) {
        CanLog_EncodeData(0, uint8_t(i), bytes, text.size(), data);
        if (i == 0) data[3] ^= 1;
        result = receiver.feed(CAN_LOG_DATA_ID, false, false, false, 8, data, 13100 + i * 100);
    }
    assert(!result && receiver.crcErrors() == 1);
    assert(!CanLog_EncodeStart(1, 2, bytes, text.size(), header));
    assert(!CanLog_EncodeStart(1, 0, bytes, 193, header));
    // Maximum size, last-fragment padding, and fresh session after explicit reset.
    const std::string maximum(192, 'x');
    receiver.reset();
    CanLog_EncodeStart(1, 1, reinterpret_cast<const uint8_t *>(maximum.data()), 192, header);
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 14000);
    for (unsigned i = 0; i * 5 < 192; ++i) {
        CanLog_EncodeData(1, uint8_t(i), reinterpret_cast<const uint8_t *>(maximum.data()), 192, data);
        result = receiver.feed(CAN_LOG_DATA_ID, false, false, false, 8, data, 14100 + i * 100);
    }
    assert(result && result->text.size() == 192);
    // Final padding is part of the wire contract, not payload or CRC data.
    receiver.reset();
    CanLog_EncodeStart(2, 0, reinterpret_cast<const uint8_t *>(maximum.data()), 192, header);
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 19000);
    for (unsigned i = 0; i * 5 < 192; ++i) {
        CanLog_EncodeData(2, uint8_t(i), reinterpret_cast<const uint8_t *>(maximum.data()), 192, data);
        if (i == 38) data[7] = 1; // Only bytes 3 and 4 are payload in this fragment.
        result = receiver.feed(CAN_LOG_DATA_ID, false, false, false, 8, data, 19100 + i * 100);
    }
    assert(!result && receiver.invalid() == 2);
    receiver.feed(CAN_LOG_START_ID, false, true, false, 8, header, 24000);
    receiver.feed(CAN_LOG_START_ID, false, false, true, 8, header, 24000);
    receiver.feed(CAN_LOG_START_ID, false, false, false, 7, header, 24000);
    assert(receiver.invalid() == 5);
    header[7] = 1;
    receiver.feed(CAN_LOG_START_ID, false, false, false, 8, header, 24000);
    assert(receiver.invalid() == 6);
}

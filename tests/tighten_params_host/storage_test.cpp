#include "tighten_params_storage.h"
#include <cstdarg>

#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {
using Bytes = std::array<uint8_t, 96>;
struct FakeStore {
    Bytes current{};
    Bytes old{};
    int load_result = 1;
    int save_result = 0;
    int reads = 0;
    int writes = 0;
    int legacy_reads = 0;
    bool corrupt_read = false;
    bool fail_readback = false;
};

uint32_t golden_crc(const Bytes &data) {
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < 88; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) {
            const uint32_t mask = 0U - (crc & 1U);
            crc = (crc >> 1U) ^ (0xEDB88320U & mask);
        }
    }
    return ~crc;
}
void put32(Bytes &data, size_t offset, uint32_t value) {
    for (size_t byte = 0; byte < 4; ++byte) {
        data[offset + byte] = static_cast<uint8_t>(value >> (byte * 8));
    }
}
Bytes default_record() {
    // Independent legacy V1 wire fixture, not production's descriptor table.
    constexpr uint32_t values[] = {80, 10, 300, 250, 8000, 3000,
        80, 100, 120, 150, 150, 300, 300, 300, 300, 500, 30, 90};
    Bytes record;
    record.fill(0xFF);
    put32(record, 0, 0x5041524D);
    put32(record, 4, 1);
    put32(record, 8, 72);
    put32(record, 12, 0);
    for (size_t i = 0; i < 18; ++i) put32(record, 16 + i * 4, values[i]);
    put32(record, 88, golden_crc(record));
    assert(golden_crc(record) == 0x224142E1U);
    return record;
}
int load(void *context, void *data, size_t length) {
    auto &store = *static_cast<FakeStore *>(context);
    ++store.reads;
    assert(length == 96);
    if (store.fail_readback && store.writes) return 2;
    if (store.load_result) return store.load_result;
    std::memcpy(data, store.current.data(), length);
    if (store.corrupt_read) static_cast<uint8_t *>(data)[20] ^= 1U;
    return 0;
}
int save(void *context, const void *data, size_t length) {
    auto &store = *static_cast<FakeStore *>(context);
    ++store.writes;
    assert(length == 96);
    if (store.save_result) return store.save_result;
    std::memcpy(store.current.data(), data, length);
    store.load_result = 0;
    return 0;
}
void read_legacy(void *context, void *data, size_t length) {
    auto &store = *static_cast<FakeStore *>(context);
    ++store.legacy_reads;
    assert(length == 96);
    std::memcpy(data, store.old.data(), length);
}
TightenParamsStoragePort_t port(FakeStore &store) {
    return {&store, load, save, read_legacy};
}
void expect_default(const TightenParamsState_t &state) {
    const TightenParams_t defaults = TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
    assert(std::memcmp(&state.params, &defaults, sizeof(defaults)) == 0);
}
void save_cases() {
    FakeStore store;
    auto io = port(store);
    TightenParamsState_t state = TIGHTEN_PARAMS_STATE_INITIALIZER;
    state.dirty = 1;
    assert(!TightenParams_StorageSave(&state, &io));
    assert(store.writes == 0 && state.dirty == 1);
    state.kvs_ready = 1;
    state.params.rundown_rpm = 0;
    assert(!TightenParams_StorageSave(&state, &io));
    assert(store.writes == 0 && state.dirty == 1);
    TightenParams_ResetDefaults(&state.params);
    assert(TightenParams_StorageSave(&state, &io));
    assert(store.current == default_record());
    assert(state.flash_valid == 1 && state.dirty == 0);
    assert(state.last_crc32 == 0x224142E1U);
    for (int failure = 0; failure < 3; ++failure) {
        store.save_result = failure == 0 ? 2 : 0;
        store.corrupt_read = failure == 1;
        store.fail_readback = failure == 2;
        state.dirty = 1;
        state.flash_valid = 1;
        state.last_crc32 = 123;
        assert(!TightenParams_StorageSave(&state, &io));
        assert(state.flash_valid == 0 && state.dirty == 1 && state.last_crc32 == 123);
        expect_default(state);
    }
}
void load_cases() {
    FakeStore store;
    store.current = default_record();
    store.old = default_record();
    auto io = port(store);
    TightenParamsState_t state = TIGHTEN_PARAMS_STATE_INITIALIZER;
    // Legacy only when KVS unavailable; no writes.
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_OK);
    assert(store.reads == 0 && store.writes == 0 && store.legacy_reads == 1);
    state.kvs_ready = 1;
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_OK);
    assert(store.writes == 1 && state.kvs_migrated == 1);
    assert(store.current == default_record());
    store.legacy_reads = 0;
    state.params.rundown_rpm = 99;
    state.dirty = 1;
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_OK);
    assert(state.dirty == 0 && store.legacy_reads == 0);
    expect_default(state);
    // KVS I/O error still falls back, without migration (old behavior).
    store.load_result = 2;
    const int writes = store.writes;
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_OK);
    assert(store.writes == writes);
    // Invalid present records never fall back, never overwrite runtime recipe.
    for (size_t offset : {size_t(0), size_t(4), size_t(8), size_t(20), size_t(88)}) {
        store.load_result = 0;
        store.current = default_record();
        store.current[offset] ^= 1U;
        store.legacy_reads = 0;
        state.params.rundown_rpm = 99;
        state.dirty = 1;
        assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_INVALID);
        assert(state.params.rundown_rpm == 99 && state.dirty == 1);
        assert(state.flash_valid == 0 && store.legacy_reads == 0);
    }
    // Correct CRC does not make an out-of-range recipe acceptable.
    store.current = default_record();
    put32(store.current, 16, 0);
    put32(store.current, 88, golden_crc(store.current));
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_INVALID);
    store.load_result = 1;
    store.old.fill(0xFF);
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_EMPTY);
    assert(state.last_crc32 == 0 && state.params.rundown_rpm == 99);
    store.old = default_record();
    store.old[88] ^= 1;
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_INVALID);
    // Failed migration preserves the legacy load result and reports not migrated.
    store.old = default_record();
    store.save_result = 2;
    state.kvs_migrated = 0;
    assert(TightenParams_StorageLoad(&state, &io) == PARAM_FLASH_LOAD_OK);
    assert(state.kvs_migrated == 0 && state.flash_valid == 0);
    expect_default(state);
    assert(TightenParams_StorageLoad(nullptr, &io) == PARAM_FLASH_LOAD_HAL_ERROR);
    assert(TightenParams_StorageLoad(&state, nullptr) == PARAM_FLASH_LOAD_HAL_ERROR);
    assert(!TightenParams_StorageSave(nullptr, &io));
}
std::vector<std::string> lines;
uint8_t capture(const char *message) { lines.emplace_back(message); return 1U; }
uint8_t capture_formatted(char *fallback, size_t capacity, const char *format, ...) {
    va_list args;
    va_start(args, format);
    const int n = std::vsnprintf(fallback, capacity, format, args);
    va_end(args);
    assert(n > 0 && static_cast<size_t>(n) < capacity);
    return capture(fallback);
}
void output_case() {
    TightenParamsState_t state = TIGHTEN_PARAMS_STATE_INITIALIZER;
    state.flash_valid = 1;
    state.dirty = 1;
    state.last_crc32 = 0x224142E1U;
    constexpr const char *names[] = {"RUNDOWN_RPM", "CONTACT_RPM", "CONTACT_IQ_MA",
        "CONTACT_MS", "RUNDOWN_TIMEOUT_MS", "MAX_TRAVEL_DEG", "SEATING_IQ_MA",
        "T1_IQ_MA", "T2_IQ_MA", "T3_IQ_MA", "HOLD_IQ_MA", "SEATING_MS",
        "T1_MS", "T2_MS", "T3_MS", "HOLD_MS", "TORQUE_ABORT_RPM", "POST_TRAVEL_MAX_DEG"};
    constexpr unsigned values[] = {80, 10, 300, 250, 8000, 3000,
        80, 100, 120, 150, 150, 300, 300, 300, 300, 500, 30, 90};
    TightenParams_EmitAll(&state, UINT32_MAX, capture);
    assert(lines.size() == 20);
    assert(lines.front() == "4294967295 OK PARAMS BACKEND=PW_KVS FLASH_VALID=1 DIRTY=1 CRC32=0x224142E1\r\n");
    for (size_t i = 0; i < 18; ++i) {
        assert(lines[i + 1] == std::string("4294967295 PARAM ") + names[i] + "=" +
               std::to_string(values[i]) + "\r\n");
    }
    assert(lines.back() == "4294967295 END PARAMS\r\n");
    TightenParams_EmitAll(nullptr, 0, capture);
    TightenParams_EmitAll(&state, 0, nullptr);
    assert(lines.size() == 20);
    const auto legacy = lines;
    lines.clear();
    TightenParams_EmitAllFormatted(&state, UINT32_MAX, capture_formatted);
    assert(lines == legacy);  // Includes all 18 names/values and wire framing.
    TightenParams_EmitAllFormatted(nullptr, 0, capture_formatted);
    TightenParams_EmitAllFormatted(&state, 0, nullptr);
    assert(lines == legacy);
}
}  // namespace

int main() {
    save_cases();
    load_cases();
    output_case();
    std::puts("PASS: V1 golden record/CRC, KVS save/readback failures, legacy migration, invalid load, 20 protocol lines");
}

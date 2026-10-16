#include "tighten_params_storage.h"

#include <array>
#include <cassert>
#include <cstring>
#include <cstdio>

namespace {
struct Store {
    std::array<uint8_t, 96> record{};
    unsigned writes = 0;
};

void put32(Store &store, size_t offset, uint32_t value) {
    for (size_t byte = 0; byte < 4; ++byte)
        store.record[offset + byte] = static_cast<uint8_t>(value >> (8U * byte));
}

int load(void *context, void *data, size_t length) {
    auto &store = *static_cast<Store *>(context);
    assert(length == store.record.size());
    std::memcpy(data, store.record.data(), length);
    return 0;
}
int save(void *context, const void *, size_t) {
    ++static_cast<Store *>(context)->writes;
    return 0;
}
void legacy(void *, void *data, size_t length) {
    std::memset(data, 0xFF, length);
}
}  // namespace

int main() {
    TightenParams_t params = TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
    assert(sizeof(params) == 72U);
    assert(params.rundown_rpm == 160U);
    assert(TightenParams_Validate(&params) == 1U);
    assert(TightenParams_TrySet(&params, "RUNDOWN_RPM", 240U, 0U) == TIGHTEN_PARAMS_OK);
    const TightenParams_t before = params;
    assert(TightenParams_TrySet(&params, "RUNDOWN_RPM", 241U, 0U) == TIGHTEN_PARAMS_OUT_OF_RANGE);
    assert(std::memcmp(&params, &before, sizeof(params)) == 0);
    assert(TightenParams_TrySet(&params, "RUNDOWN_RPM", 160U, 1U) == TIGHTEN_PARAMS_BUSY);
    assert(TightenParams_TrySet(&params, "T3_IQ_MA", 151U, 0U) == TIGHTEN_PARAMS_OUT_OF_RANGE);
    TightenParams_ResetDefaults(&params);
    assert(params.rundown_rpm == 160U && params.t3_iq_mA == 150U);

    // Independent V1 record with a previously saved 70 rpm recipe.
    constexpr uint32_t values[] = {70, 10, 300, 250, 8000, 3000,
        80, 100, 120, 150, 150, 300, 300, 300, 300, 500, 30, 90};
    Store store;
    store.record.fill(0xFF);
    put32(store, 0, 0x5041524DU);
    put32(store, 4, 1U);
    put32(store, 8, 72U);
    put32(store, 12, 0U);
    for (size_t i = 0; i < 18; ++i) put32(store, 16 + 4 * i, values[i]);
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < 88; ++i) {
        crc ^= store.record[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1U) ^ ((0U - (crc & 1U)) & 0xEDB88320U);
    }
    put32(store, 88, ~crc);
    TightenParamsStoragePort_t port = {&store, load, save, legacy};
    TightenParamsState_t state = TIGHTEN_PARAMS_STATE_INITIALIZER;
    state.kvs_ready = 1U;
    assert(TightenParams_StorageLoad(&state, &port) == PARAM_FLASH_LOAD_OK);
    assert(state.params.rundown_rpm == 70U && state.flash_valid == 1U);
    assert(TightenParams_StorageSave(&state, &port) == 0U);
    state.params.rundown_rpm = 160U;
    assert(TightenParams_StorageSave(&state, &port) == 0U);
    assert(store.writes == 0U);
    std::puts("PASS: 160/240 rpm opt-in, unchanged current ranges, old KVS preserved, no writes");
}

#include "tighten_params_storage.h"

#include <cstring>
#include <type_traits>

namespace {
constexpr uint32_t kMagic = 0x5041524DU;
constexpr uint32_t kVersion = 1U;
constexpr int kOk = 0;
constexpr int kNotFound = 1;

struct alignas(8) Record {
    uint32_t magic, version, payload_size, reserved0;
    TightenParams_t params;
    uint32_t crc32, reserved1;
};
static_assert(sizeof(Record) == 96U && offsetof(Record, params) == 16U &&
              offsetof(Record, crc32) == 88U, "V1 storage ABI changed");
static_assert(std::is_trivially_copyable<Record>::value, "Flash record");

uint32_t crc32(const Record &record) noexcept {
    const auto *bytes = reinterpret_cast<const uint8_t *>(&record);
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < offsetof(Record, crc32); ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1U) ^ ((crc & 1U) ? 0xEDB88320U : 0U);
        }
    }
    return ~crc;
}

bool valid(const Record &record) noexcept {
    return record.magic == kMagic && record.version == kVersion &&
           record.payload_size == sizeof(TightenParams_t) &&
           crc32(record) == record.crc32 &&
           TightenParams_Validate(&record.params) != 0U;
}

void accept(TightenParamsState_t &state, const Record &record) noexcept {
    state.params = record.params;
    state.flash_valid = 1U;
    state.dirty = 0U;
    state.last_crc32 = record.crc32;
}

TightenParamsFlashLoadStatus_t legacy(
    TightenParamsState_t &state, const TightenParamsStoragePort_t &port) {
    Record record;
    port.read_legacy(port.context, &record, sizeof(record));
    if (record.magic == 0xFFFFFFFFU && record.version == 0xFFFFFFFFU) {
        state.flash_valid = 0U;
        state.last_crc32 = 0U;
        return PARAM_FLASH_LOAD_EMPTY;
    }
    if (!valid(record)) {
        state.flash_valid = 0U;
        return PARAM_FLASH_LOAD_INVALID;
    }
    accept(state, record);
    return PARAM_FLASH_LOAD_OK;
}
}  // namespace

extern "C" uint8_t TightenParams_StorageSave(
    TightenParamsState_t *state, const TightenParamsStoragePort_t *port) {
#if defined(TIGHTEN_SPEED_X2_OFFLINE)
    /* Never persist experimental values into the shared normal V1 recipe. */
    (void)state;
    (void)port;
    return 0U;
#else
    if (state == nullptr || port == nullptr || port->load == nullptr ||
        port->save == nullptr || state->kvs_ready == 0U ||
        TightenParams_Validate(&state->params) == 0U) {
        return 0U;
    }
    Record record;
    std::memset(&record, 0xFF, sizeof(record));
    record.magic = kMagic;
    record.version = kVersion;
    record.payload_size = sizeof(TightenParams_t);
    record.reserved0 = 0U;
    record.params = state->params;
    record.crc32 = crc32(record);
    if (port->save(port->context, &record, sizeof(record)) != kOk) {
        state->flash_valid = 0U;
        return 0U;
    }
    Record verify{};
    if (port->load(port->context, &verify, sizeof(verify)) != kOk ||
        crc32(verify) != verify.crc32 ||
        std::memcmp(&record, &verify, sizeof(record)) != 0) {
        state->flash_valid = 0U;
        return 0U;
    }
    accept(*state, record);
    return 1U;
#endif
}

extern "C" TightenParamsFlashLoadStatus_t TightenParams_StorageLoad(
    TightenParamsState_t *state, const TightenParamsStoragePort_t *port) {
    if (state == nullptr || port == nullptr || port->read_legacy == nullptr ||
        (state->kvs_ready != 0U && (port->load == nullptr || port->save == nullptr))) {
        return PARAM_FLASH_LOAD_HAL_ERROR;
    }
    if (state->kvs_ready == 0U) {
        return legacy(*state, *port);
    }
    Record record{};
    const int result = port->load(port->context, &record, sizeof(record));
    if (result == kNotFound) {
        const auto status = legacy(*state, *port);
        if (status == PARAM_FLASH_LOAD_OK && TightenParams_StorageSave(state, port)) {
            state->kvs_migrated = 1U;
        }
        return status;
    }
    if (result != kOk) {
        return legacy(*state, *port);
    }
    /* Present-but-invalid KVS data must not resurrect old legacy parameters. */
    if (!valid(record)) {
        state->flash_valid = 0U;
        return PARAM_FLASH_LOAD_INVALID;
    }
    accept(*state, record);
    return PARAM_FLASH_LOAD_OK;
}

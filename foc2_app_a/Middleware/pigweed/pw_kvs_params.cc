#include "pw_kvs_params.h"

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "main.h"
#include "pw_kvs/crc16_checksum.h"
#include "pw_kvs/flash_memory.h"
#include "pw_kvs/key_value_store.h"
#include "pw_log/log.h"
#include "pw_span/span.h"

namespace {

constexpr uint32_t kFlashBase = 0x08078000UL;
constexpr uint32_t kFlashPage = 112U;
constexpr size_t kSectorSize = 0x800U;
constexpr size_t kSectorCount = 8U;
constexpr size_t kWriteAlignment = 8U;
constexpr char kParamsKey[] = "tighten.params.v1";

class Stm32KvsFlash final : public pw::kvs::FlashMemory {
 public:
  Stm32KvsFlash()
      : FlashMemory(kSectorSize,
                    kSectorCount,
                    kWriteAlignment,
                    kFlashBase,
                    0U,
                    std::byte{0xFF}) {}

  pw::Status Enable() override {
    if (enabled_) {
      return pw::OkStatus();
    }
    if (HAL_FLASH_Unlock() != HAL_OK) {
      return pw::Status::Unknown();
    }
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);
    enabled_ = true;
    return pw::OkStatus();
  }

  pw::Status Disable() override {
    if (!enabled_) {
      return pw::OkStatus();
    }
    const HAL_StatusTypeDef result = HAL_FLASH_Lock();
    enabled_ = false;
    return result == HAL_OK ? pw::OkStatus() : pw::Status::Unknown();
  }

  bool IsEnabled() const override { return enabled_; }

  pw::Status Erase(Address address, size_t sectors) override {
    if ((address < kFlashBase) ||
        ((address - kFlashBase) % kSectorSize != 0U) ||
        (sectors == 0U) ||
        (address + sectors * kSectorSize > kFlashBase + size_bytes())) {
      return pw::Status::InvalidArgument();
    }

    const bool was_enabled = enabled_;
    if (!was_enabled && !Enable().ok()) {
      return pw::Status::Unknown();
    }

    FLASH_EraseInitTypeDef erase = {};
    uint32_t page_error = 0U;
    erase.TypeErase = FLASH_TYPEERASE_PAGES;
    erase.Banks = FLASH_BANK_2;
    erase.Page = kFlashPage + (address - kFlashBase) / kSectorSize;
    erase.NbPages = static_cast<uint32_t>(sectors);
    const HAL_StatusTypeDef result = HAL_FLASHEx_Erase(&erase, &page_error);

    if (!was_enabled) {
      (void)Disable();
    }
    return result == HAL_OK ? pw::OkStatus() : pw::Status::Unknown();
  }

  pw::StatusWithSize Read(Address address,
                          pw::span<std::byte> output) override {
    if ((address < kFlashBase) ||
        (address + output.size() > kFlashBase + size_bytes())) {
      return pw::StatusWithSize::OutOfRange();
    }
    if (!output.empty()) {
      std::memcpy(output.data(),
                  reinterpret_cast<const void*>(address),
                  output.size());
    }
    return pw::StatusWithSize(output.size());
  }

  pw::StatusWithSize Write(Address address,
                           pw::span<const std::byte> data) override {
    if ((address < kFlashBase) ||
        (address + data.size() > kFlashBase + size_bytes())) {
      return pw::StatusWithSize::OutOfRange();
    }
    if (((address - kFlashBase) % kWriteAlignment != 0U) ||
        (data.size() % kWriteAlignment != 0U)) {
      return pw::StatusWithSize::InvalidArgument();
    }

    const bool was_enabled = enabled_;
    if (!was_enabled && !Enable().ok()) {
      return pw::StatusWithSize::Unknown();
    }

    size_t written = 0U;
    while (written < data.size()) {
      uint64_t double_word = 0U;
      std::memcpy(&double_word, data.data() + written, sizeof(double_word));
      if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD,
                            address + written,
                            double_word) != HAL_OK) {
        if (!was_enabled) {
          (void)Disable();
        }
        return pw::StatusWithSize(pw::Status::Unknown(), written);
      }
      written += sizeof(double_word);
    }

    if (!was_enabled) {
      (void)Disable();
    }
    return pw::StatusWithSize(written);
  }

  std::byte* FlashAddressToMcuAddress(Address address) const override {
    if ((address < kFlashBase) ||
        (address >= kFlashBase + size_bytes())) {
      return nullptr;
    }
    return reinterpret_cast<std::byte*>(address);
  }

 private:
  bool enabled_ = false;
};

Stm32KvsFlash flash;
pw::kvs::FlashPartition partition(&flash);
pw::kvs::ChecksumCrc16 checksum;
const pw::kvs::EntryFormat format = {
    .magic = 0x47564B53UL,
    .checksum = &checksum,
};
const pw::kvs::Options options = {
    .gc_on_write = pw::kvs::GargbageCollectOnWrite::kOneSector,
    .recovery = pw::kvs::ErrorRecovery::kImmediate,
    .verify_on_read = true,
    .verify_on_write = true,
};
pw::kvs::KeyValueStoreBuffer<4, kSectorCount, 2> kvs(
    &partition, format, options);

bool initialized = false;

}  // namespace

extern "C" int PW_Kvs_Init(void) {
  const pw::Status status = kvs.Init();
  initialized = status.ok() || status.IsDataLoss();
  if (!initialized) {
    PW_LOG_ERROR("KVS init failed status=%d", static_cast<int>(status.code()));
    return PW_KVS_RESULT_ERROR;
  }

  PW_LOG_INFO("KVS ready sectors=%u sector_size=%u redundancy=%u entries=%u",
              static_cast<unsigned>(kSectorCount),
              static_cast<unsigned>(kSectorSize),
              static_cast<unsigned>(kvs.redundancy()),
              static_cast<unsigned>(kvs.size()));
  return PW_KVS_RESULT_OK;
}

extern "C" int PW_Kvs_LoadParams(void* record, size_t record_size) {
  if (!initialized || record == nullptr || record_size == 0U) {
    return PW_KVS_RESULT_ERROR;
  }

  const pw::StatusWithSize result = kvs.Get(
      kParamsKey,
      pw::span<std::byte>(static_cast<std::byte*>(record), record_size));
  if (result.status().IsNotFound()) {
    return PW_KVS_RESULT_NOT_FOUND;
  }
  if (!result.ok() || result.size() != record_size) {
    return PW_KVS_RESULT_ERROR;
  }
  return PW_KVS_RESULT_OK;
}

extern "C" int PW_Kvs_SaveParams(const void* record, size_t record_size) {
  if (!initialized || record == nullptr || record_size == 0U) {
    return PW_KVS_RESULT_ERROR;
  }

  const auto bytes = pw::span<const std::byte>(
      static_cast<const std::byte*>(record), record_size);
  return kvs.Put(kParamsKey, bytes).ok() ? PW_KVS_RESULT_OK
                                        : PW_KVS_RESULT_ERROR;
}

extern "C" void PW_Kvs_GetDiagnostics(PW_KvsDiagnostics_t* diagnostics) {
  if (diagnostics == nullptr) {
    return;
  }
  std::memset(diagnostics, 0, sizeof(*diagnostics));
  diagnostics->initialized = initialized ? 1U : 0U;
  if (!initialized) {
    return;
  }

  const pw::kvs::KeyValueStore::StorageStats stats = kvs.GetStorageStats();
  diagnostics->entries = static_cast<uint32_t>(kvs.size());
  diagnostics->transaction_count = kvs.transaction_count();
  diagnostics->writable_bytes = static_cast<uint32_t>(stats.writable_bytes);
  diagnostics->in_use_bytes = static_cast<uint32_t>(stats.in_use_bytes);
  diagnostics->reclaimable_bytes =
      static_cast<uint32_t>(stats.reclaimable_bytes);
  diagnostics->sector_erase_count =
      static_cast<uint32_t>(stats.sector_erase_count);
  diagnostics->redundancy = static_cast<uint32_t>(kvs.redundancy());
}

#include "pw_log_backend.h"

#include <cstddef>
#include <cstdint>

#include "pw_log/levels.h"
#include "pw_log_tokenized/log_tokenized.h"

extern "C" void pw_log_tokenized_HandleLog(uint32_t metadata,
                                             const uint8_t buffer[],
                                             size_t size) {
  (void)PW_Log_EnqueueTokenized(metadata, buffer, size);
}

extern "C" uint32_t PW_Log_TokenizedTestBurst(uint32_t count) {
  PW_LogDiagnostics_t before{};
  PW_LogDiagnostics_t after{};

  if (count > 1000U) {
    count = 1000U;
  }

  PW_Log_GetDiagnostics(&before);
  for (uint32_t i = 0; i < count; ++i) {
    PW_LOG_TOKENIZED_TO_GLOBAL_HANDLER_WITH_METADATA(
        PW_LOG_LEVEL_INFO,
        "LOGTOK",
        0,
        "token burst index=%u value=%d",
        static_cast<unsigned int>(i),
        static_cast<int>(i * 3U) - 7);
  }
  PW_Log_GetDiagnostics(&after);
  return after.tokenized - before.tokenized;
}

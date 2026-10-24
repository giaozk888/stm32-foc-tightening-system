#pragma once
#include "pw_log_tokenized/config.h"
#include "pw_log_tokenized/log_tokenized.h"

/* Pigweed's tokenizer declares static dictionary entries. C++17/20 forbids
 * those declarations directly inside a constexpr function (including assert
 * branches in upstream headers). Use Pigweed's expression-token APIs, without
 * changing the assertion's caller, termination, filtering or wire codec.
 * Evaluate arguments at the call site: __func__ must not become operator(). */
#ifdef __cplusplus
#define PW_HANDLE_LOG(level, module, flags, message, ...)                    \
  do {                                                                     \
    const uintptr_t pw_diag_level = (level);                                \
    const uintptr_t pw_diag_module = PW_TOKENIZE_STRING_MASK_EXPR(          \
        "pw_log_module_names", ((1u << PW_LOG_TOKENIZED_MODULE_BITS) - 1u), \
        module);                                                           \
    if (0) {                                                               \
      pw_tokenizer_CheckFormatString(                                      \
          PW_LOG_TOKENIZED_FORMAT_STRING(module, message)                  \
              PW_COMMA_ARGS(__VA_ARGS__));                                \
    }                                                                      \
    _PW_TOKENIZE_VALIDATE_FORMAT_STRING(                                   \
        PW_LOG_TOKENIZED_FORMAT_STRING(module, message));                  \
    _pw_log_tokenized_EncodeTokenizedLog(                                  \
        _PW_LOG_TOKENIZED_LEVEL(pw_diag_level) |                           \
            _PW_LOG_TOKENIZED_MODULE(pw_diag_module) |                     \
            _PW_LOG_TOKENIZED_FLAGS(flags) | _PW_LOG_TOKENIZED_LINE(__LINE__), \
        PW_TOKENIZE_STRING_EXPR(PW_LOG_TOKENIZED_FORMAT_STRING(module, message)), \
        PW_TOKENIZER_ARG_TYPES(__VA_ARGS__) PW_COMMA_ARGS(__VA_ARGS__));    \
  } while (0)
#else
#define PW_HANDLE_LOG PW_LOG_TOKENIZED_TO_GLOBAL_HANDLER_WITH_METADATA
#endif
#define PW_LOG_FLAG_BITS PW_LOG_TOKENIZED_FLAG_BITS

#include "tighten_params.h"
#include "tighten_params_storage.h"

#include <array>
#include <cstring>
#include <cstdio>
#include <type_traits>

namespace tightening {
namespace {
struct Range {
    uint32_t low;
    uint32_t high;

    constexpr bool contains(uint32_t value) const noexcept {
        return value >= low && value <= high;
    }
};

struct Field {
    const char *name;
    uint32_t TightenParams_t::*member;
    Range range;
};

#define TIGHTEN_PARAM_DESCRIPTOR(field, name, low, high, initial) \
    Field{name, &TightenParams_t::field, Range{low, high}},
constexpr std::array<Field, 18> kFields{{
    TIGHTEN_PARAM_FIELDS(TIGHTEN_PARAM_DESCRIPTOR)
}};
#undef TIGHTEN_PARAM_DESCRIPTOR

constexpr TightenParams_t kDefaults = TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
static_assert(std::is_standard_layout<TightenParams_t>::value, "C ABI layout");
static_assert(std::is_trivially_copyable<TightenParams_t>::value, "Flash payload");

const Field *find(const char *name) noexcept {
    for (const auto &field : kFields) {
        if (std::strcmp(name, field.name) == 0) {
            return &field;
        }
    }
    return nullptr;
}
}  // namespace

/* Non-owning, task-local view of the existing C recipe. No static constructor,
 * heap, virtual dispatch, exception or RTOS lock is involved. The C task keeps
 * lifecycle, motion gates and synchronization ownership. Persistence policy
 * is isolated in tighten_params_storage.cpp.
 */
class RecipeView final {
public:
    explicit RecipeView(TightenParams_t &params) noexcept : params_(params) {}

    static bool validate(const TightenParams_t &params) noexcept {
        for (const auto &field : kFields) {
            if (!field.range.contains(params.*(field.member))) {
                return false;
            }
        }
        return true;
    }

    static TightenParamsResult_t get(const TightenParams_t &params,
                                    const char *name, uint32_t &value) noexcept {
        const Field *field = find(name);
        if (field == nullptr) {
            return TIGHTEN_PARAMS_UNKNOWN_NAME;
        }
        value = params.*(field->member);
        return TIGHTEN_PARAMS_OK;
    }

    TightenParamsResult_t set(const char *name, uint32_t value) noexcept {
        const Field *field = find(name);
        if (field == nullptr) {
            return TIGHTEN_PARAMS_UNKNOWN_NAME;
        }
        if (!field->range.contains(value)) {
            return TIGHTEN_PARAMS_OUT_OF_RANGE;
        }
        params_.*(field->member) = value;
        return TIGHTEN_PARAMS_OK;
    }

    void reset() noexcept { params_ = kDefaults; }

private:
    TightenParams_t &params_;
};
}  // namespace tightening

extern "C" uint8_t TightenParams_Validate(const TightenParams_t *params) {
    return params != nullptr && tightening::RecipeView::validate(*params) ? 1U : 0U;
}

extern "C" void TightenParams_ResetDefaults(TightenParams_t *params) {
    if (params != nullptr) {
        tightening::RecipeView(*params).reset();
    }
}

extern "C" TightenParamsResult_t TightenParams_TryGet(
    const TightenParams_t *params, const char *name, uint32_t *value) {
    if (params == nullptr || name == nullptr || value == nullptr) {
        return TIGHTEN_PARAMS_INVALID_ARGUMENT;
    }
    return tightening::RecipeView::get(*params, name, *value);
}

extern "C" TightenParamsResult_t TightenParams_TrySet(
    TightenParams_t *params, const char *name, uint32_t value, uint8_t busy) {
    if (busy != 0U) {
        return TIGHTEN_PARAMS_BUSY;
    }
    if (params == nullptr || name == nullptr) {
        return TIGHTEN_PARAMS_INVALID_ARGUMENT;
    }
    return tightening::RecipeView(*params).set(name, value);
}

namespace {
template <typename Emit>
void EmitParamLines(const TightenParamsState_t &state, uint32_t request_id,
                    Emit emit) {
    emit(
        "%lu OK PARAMS BACKEND=PW_KVS FLASH_VALID=%u DIRTY=%u CRC32=0x%08lX\r\n",
        static_cast<unsigned long>(request_id),
        static_cast<unsigned>(state.flash_valid),
        static_cast<unsigned>(state.dirty),
        static_cast<unsigned long>(state.last_crc32));
    for (const auto &field : tightening::kFields) {
        emit("%lu PARAM %s=%lu\r\n",
            static_cast<unsigned long>(request_id), field.name,
            static_cast<unsigned long>(state.params.*(field.member)));
    }
    emit("%lu END PARAMS\r\n", static_cast<unsigned long>(request_id));
}
}  // namespace

extern "C" void TightenParams_EmitAll(const TightenParamsState_t *state,
                                      uint32_t request_id,
                                      uint8_t (*send)(const char *)) {
    if (state == nullptr || send == nullptr) return;
    EmitParamLines(*state, request_id, [send](const char *format, auto... args) {
        char message[128];
        const int length = std::snprintf(message, sizeof(message), format, args...);
        if (length > 0 && static_cast<size_t>(length) < sizeof(message)) {
            send(message);  // Legacy callback must consume/copy synchronously.
        }
    });
}

extern "C" void TightenParams_EmitAllFormatted(
    const TightenParamsState_t *state, uint32_t request_id,
    TightenParamsFormatSendFn send) {
    if (state == nullptr || send == nullptr) return;
    EmitParamLines(*state, request_id, [send](const char *format, auto... args) {
        char fallback[128];
        send(fallback, sizeof(fallback), format, args...);
    });
}

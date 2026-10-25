#include "adc_raw_report.h"

int AdcRaw_SummarizeParallel(const uint16_t *u, const uint16_t *v, const uint16_t *w,
                            size_t count, AdcRawThreePhaseReport *report)
{
    if (!u || !v || !w || !count || !report) return 0;
    AdcRawThreePhaseReport r = {4095U, 0U, 4095U, 0U, 4095U, 0U, 0U};
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0U; i < count; ++i) {
        uint16_t triple[3] = {u[i], v[i], w[i]};
        if (u[i] > 4095U || v[i] > 4095U || w[i] > 4095U) return 0;
        if (u[i] < r.min_u) r.min_u = u[i];
        if (u[i] > r.max_u) r.max_u = u[i];
        if (v[i] < r.min_v) r.min_v = v[i];
        if (v[i] > r.max_v) r.max_v = v[i];
        if (w[i] < r.min_w) r.min_w = w[i];
        if (w[i] > r.max_w) r.max_w = w[i];
        for (unsigned phase = 0U; phase < 3U; ++phase) {
            for (unsigned byte = 0U; byte < 2U; ++byte) {
                crc ^= (uint8_t)(triple[phase] >> (8U * byte));
                for (unsigned bit = 0U; bit < 8U; ++bit)
                    crc = (crc >> 1U) ^ (0xEDB88320U & (0U - (crc & 1U)));
            }
        }
    }
    r.crc32 = crc ^ 0xFFFFFFFFU;
    *report = r;
    return 1;
}

static uint32_t ByteCrc(uint32_t crc, uint8_t byte)
{
    crc ^= byte;
    for (unsigned i = 0U; i < 8U; ++i)
        crc = (crc >> 1U) ^ (0xEDB88320U & (0U - (crc & 1U)));
    return crc;
}

int AdcRaw_SummarizeUvPadding(const uint16_t *u, const uint16_t *v,
                            size_t count, AdcRawThreePhaseReport *report)
{
    if (!u || !v || !count || !report) return 0;
    AdcRawThreePhaseReport r = {4095U, 0U, 4095U, 0U, 0U, 0U, 0xFFFFFFFFU};
    for (size_t i = 0U; i < count; ++i) {
        if (u[i] > 4095U || v[i] > 4095U) return 0;
        if (u[i] < r.min_u) r.min_u = u[i];
        if (u[i] > r.max_u) r.max_u = u[i];
        if (v[i] < r.min_v) r.min_v = v[i];
        if (v[i] > r.max_v) r.max_v = v[i];
        r.crc32 = ByteCrc(r.crc32, (uint8_t)u[i]);
        r.crc32 = ByteCrc(r.crc32, (uint8_t)(u[i] >> 8U));
        r.crc32 = ByteCrc(r.crc32, (uint8_t)v[i]);
        r.crc32 = ByteCrc(r.crc32, (uint8_t)(v[i] >> 8U));
        r.crc32 = ByteCrc(r.crc32, 0U);
        r.crc32 = ByteCrc(r.crc32, 0U);
    }
    r.crc32 ^= 0xFFFFFFFFU;
    *report = r;
    return 1;
}

int AdcRaw_Summarize(const uint16_t *u, const uint16_t *v, size_t count,
                     AdcRawReport *report)
{
    if (!u || !v || !count || !report) return 0;
    AdcRawReport r = {4095U, 0U, 4095U, 0U, 0xFFFFFFFFU};
    for (size_t i = 0U; i < count; ++i) {
        if (u[i] > 4095U || v[i] > 4095U) return 0;
        if (u[i] < r.min_u) r.min_u = u[i];
        if (u[i] > r.max_u) r.max_u = u[i];
        if (v[i] < r.min_v) r.min_v = v[i];
        if (v[i] > r.max_v) r.max_v = v[i];
        r.crc32 = ByteCrc(r.crc32, (uint8_t)u[i]);
        r.crc32 = ByteCrc(r.crc32, (uint8_t)(u[i] >> 8U));
        r.crc32 = ByteCrc(r.crc32, (uint8_t)v[i]);
        r.crc32 = ByteCrc(r.crc32, (uint8_t)(v[i] >> 8U));
    }
    r.crc32 ^= 0xFFFFFFFFU;
    *report = r;
    return 1;
}

int AdcRaw_SummarizeThreePhase(const uint16_t *uw, const uint16_t *v,
                              size_t count, AdcRawThreePhaseReport *report)
{
    if (!uw || !v || !count || count > SIZE_MAX / 2U || !report) return 0;
    AdcRawThreePhaseReport r = {4095U, 0U, 4095U, 0U, 4095U, 0U, 0xFFFFFFFFU};
    for (size_t i = 0U; i < count; ++i) {
        uint16_t u = uw[2U * i], w = uw[2U * i + 1U];
        if (u > 4095U || v[i] > 4095U || w > 4095U) return 0;
        if (u < r.min_u) r.min_u = u;
        if (u > r.max_u) r.max_u = u;
        if (v[i] < r.min_v) r.min_v = v[i];
        if (v[i] > r.max_v) r.max_v = v[i];
        if (w < r.min_w) r.min_w = w;
        if (w > r.max_w) r.max_w = w;
        uint16_t triple[3] = {u, v[i], w};
        for (unsigned phase = 0U; phase < 3U; ++phase) {
            r.crc32 = ByteCrc(r.crc32, (uint8_t)triple[phase]);
            r.crc32 = ByteCrc(r.crc32, (uint8_t)(triple[phase] >> 8U));
        }
    }
    r.crc32 ^= 0xFFFFFFFFU;
    *report = r;
    return 1;
}

#ifndef FOC_PROTECTION_SELFTEST_H
#define FOC_PROTECTION_SELFTEST_H
#include <stdint.h>
typedef struct {
    uint32_t cases, checks, failures;
} FocProtectionSelftestResult;
/* Fixed synthetic inputs; no ADC, IO, allocation or power-control calls. */
FocProtectionSelftestResult FocProtectionSelftest_Run(void);
#endif

#define PW_LOG_MODULE_NAME "STAGE5"

#include "pw_assert/check.h"
#include "pw_log/log.h"

extern "C" void PW_SmokeTest(void)
{
    int x = 123;
    const int *ptr = &x;

    PW_LOG_INFO("Pigweed alive");
    PW_LOG_INFO("MCU=STM32G474 SLOT=A");
    PW_CHECK(x == 123);
    PW_DCHECK(ptr != nullptr);
    PW_LOG_INFO("pw_assert checks passed");
}


#include <stdio.h>
#include "foc_protection_selftest.h"
int main(void)
{
    FocProtectionSelftestResult r=FocProtectionSelftest_Run();
    printf("CASES=%lu CHECKS=%lu FAIL=%08lX\n",(unsigned long)r.cases,
           (unsigned long)r.checks,(unsigned long)r.failures);
    return r.failures || r.cases!=6 || r.checks!=36;
}

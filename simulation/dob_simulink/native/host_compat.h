/* Forced include ONLY for the single-threaded offline host DLL.
 * Do not modify the MCU barrier or reuse this shim in firmware builds. */
#ifndef DOB_OFFLINE_HOST_COMPAT_H
#define DOB_OFFLINE_HOST_COMPAT_H
#define KA_SYNC_DIAGNOSTIC_H
#include <stdint.h>
static inline void KaSync_Barrier(void) {}
extern float dob_host_gain;
#endif

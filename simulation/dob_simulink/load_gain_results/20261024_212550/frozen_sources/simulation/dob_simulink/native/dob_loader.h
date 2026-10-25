#ifndef DOB_OFFLINE_LOADER_H
#define DOB_OFFLINE_LOADER_H
#include <windows.h>
typedef void (*DobReset)(const double *);
typedef void (*DobStep)(double,const double *,double *);
typedef unsigned (*DobSize)(void);
typedef void (*DobSave)(void *);
typedef void (*DobRestore)(const void *);
typedef void (*DobObserve)(const double *,double *);
static HMODULE dob_dll;
static DobReset dob_reset;
static DobStep dob_step;
static DobSize dob_size;
static DobSave dob_save;
static DobRestore dob_restore;
static DobObserve dob_observe;
static DobReset dob_configure;
static int dob_load(const char *path) {
    if(dob_dll)return 1;
    dob_dll=LoadLibraryA(path);
    if(!dob_dll)return 0;
    dob_reset=(DobReset)(void*)GetProcAddress(dob_dll,"dob_host_reset");
    dob_step=(DobStep)(void*)GetProcAddress(dob_dll,"dob_host_step");
    dob_size=(DobSize)(void*)GetProcAddress(dob_dll,"dob_host_state_size");
    dob_save=(DobSave)(void*)GetProcAddress(dob_dll,"dob_host_save");
    dob_restore=(DobRestore)(void*)GetProcAddress(dob_dll,"dob_host_restore");
    dob_observe=(DobObserve)(void*)GetProcAddress(dob_dll,"dob_host_observe");
    dob_configure=(DobReset)(void*)GetProcAddress(dob_dll,"dob_host_configure");
    return dob_reset&&dob_step&&dob_size&&dob_save&&dob_restore&&dob_observe&&dob_configure;
}
#endif

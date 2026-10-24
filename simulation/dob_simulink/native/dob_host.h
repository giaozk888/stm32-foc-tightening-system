#ifndef DOB_OFFLINE_HOST_H
#define DOB_OFFLINE_HOST_H
/* Plain double-vector ABI, no MATLAB/MCU dependency. One instance per process.
 * config: enabled, gain, cap_A. Inputs/outputs named in dob_schema.m. */
#ifdef _WIN32
#define DOB_EXPORT __declspec(dllexport)
#else
#define DOB_EXPORT
#endif
#define DOB_NU 10
#define DOB_NY 33
DOB_EXPORT void dob_host_reset(const double *config);
DOB_EXPORT void dob_host_step(double time_s,const double *input,double *output);
DOB_EXPORT unsigned dob_host_state_size(void);
DOB_EXPORT void dob_host_save(void *buffer);
DOB_EXPORT void dob_host_restore(const void *buffer);
DOB_EXPORT void dob_host_observe(const double *input,double *output);
DOB_EXPORT void dob_host_configure(const double *config);
#endif

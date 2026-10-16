#include <cstdarg>
#include <cstdio>
extern "C" void pw_log_string_HandleMessageVaList(int, unsigned int, const char*,
    const char*, int, const char* message, va_list args) {
    std::vfprintf(stderr, message, args); std::fputc('\n', stderr);
}

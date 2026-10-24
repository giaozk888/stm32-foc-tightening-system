#define PW_LOG_MODULE_NAME "DIAG"
/* Stable messages for host round-trip tests; production keeps Pigweed's
 * default module/file dictionary fields. Runtime codec/backend is unchanged. */
#define PW_LOG_TOKENIZED_FORMAT_STRING(module, message) message
#include "pw_log/log.h"
#include <cassert>
#include <cstdint>
#include <cstdio>

static unsigned emitted;
extern "C" void CLog(void);
extern "C" void pw_log_tokenized_HandleLog(uint32_t metadata,
                                            const uint8_t data[], size_t size)
{
    assert(size>=4 && size<=32);
    std::printf("%u %zu ",metadata,size);
    for(size_t i=0;i<size;++i) std::printf("%02x",data[i]);
    std::puts("");
    ++emitted;
}

/* Must compile with the existing pre-C++23 language mode, including a log
 * branch which is not evaluated during constant evaluation. */
constexpr int Checked(int value)
{
    if(value<0) PW_LOG_ERROR("bad=%d",value);
    return value;
}
static_assert(Checked(4)==4);
template<class T> static void LogTemplate(T value)
{ PW_LOG_INFO("template=%d",value); }

int main()
{
    PW_LOG_INFO("literal only");
    PW_LOG_WARN("signed=%d unsigned=%u",-7,42U);
    PW_LOG_ERROR("float=%.2f",1.25);
    PW_LOG_INFO("str=%s","ok");
    PW_LOG_INFO("func=%s",__func__);
    int count=0;
    PW_LOG_INFO("once=%d",++count);
    assert(count==1);
    LogTemplate(17);
    assert(Checked(-2)==-2);
    PW_LOG_INFO("long=%s","012345678901234567890123456789012345678901234567890123456789");
    CLog();
    assert(emitted==12);
    return 0;
}

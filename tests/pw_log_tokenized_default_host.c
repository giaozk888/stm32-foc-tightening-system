#define PW_LOG_MODULE_NAME "DIAG_C"
#define PW_LOG_TOKENIZED_FORMAT_STRING(module, message) message
#include "pw_log/log.h"
#include <assert.h>

void CLog(void)
{
    int count=0;
    PW_LOG_INFO("c=%d",++count);
    assert(count==1);
    PW_LOG_WARN("c-func=%s",__func__);
    PW_LOG_ERROR("c-empty");
}

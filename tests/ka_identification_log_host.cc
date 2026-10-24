#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include <cstdarg>
#include <cstdio>
#include "../firmware_common/ka_identification_log.cc"
extern "C" void pw_log_tokenized_HandleLog(uint32_t,const uint8_t *data,size_t size)
{
    printf("%zu ",size);for(size_t i=0;i<size;++i) printf("%02x",data[i]);puts("");
}
int main()
{
    KaIdentFrame f={UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,-300,300,.5f,-.105f,240,238};
    KaIdent_Log(&f);
}

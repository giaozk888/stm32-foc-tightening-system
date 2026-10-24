#define PW_LOG_TOKENIZED_FORMAT_STRING(module,message) message
#include "psi_ke_identification_log.cc"
#include <cassert>
#include <cstdio>
extern "C" void pw_log_tokenized_HandleLog(uint32_t,const uint8_t data[],size_t size)
{
    assert(size>=4 && size<=32);
    std::printf("%zu ",size);
    for(size_t i=0;i<size;++i) std::printf("%02x",data[i]);
    std::puts("");
}
int main()
{
    PsiIdentFrame f{};
    f.index=f.seq=f.us=UINT32_MAX;f.rpm=200;f.we=209.43951f;
    f.id=.002f;f.iq=.16f;f.vd=.01f;f.vq=.2086f;
    f.resistive=.1248f;f.cross=.0000084f;f.bemf=.0838f;f.psi=.0004f;
    f.quality=6;f.saturated=1;f.fault=UINT32_MAX;f.stage=4;
    PsiIdent_Log(&f);
}

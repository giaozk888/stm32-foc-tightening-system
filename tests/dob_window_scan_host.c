#include "dob_trend_shadow.h"
#include <assert.h>
#include <stdio.h>
int main(int argc,char **argv){
    assert(argc==2);FILE *f=fopen(argv[1],"wb");assert(f);
    DobTrendClassifier s;DobTrendClassifier_Reset(&s);
    uint32_t reset_at=0;
    for(unsigned k=0;k<3000;++k){
        uint32_t t=100000+k*1000;
        int valid=!(k==900||(k>=1000&&k<1003)||(k>=1500&&k<1525));
        float value=k<500?.002f:k<1200?.04f:.002f;
        DobTrendInput in={.encoder_us=t,.observed_us=t+20,.source_us=t+20,
            .disturbance_a=k==900?.7f:value,.direction=1,.running=1,.valid=(uint8_t)valid,.filter_updated=(uint8_t)valid};
        if(k==900){float mean=s.mean,filtered=s.trend_filtered;DobTrendClassifier_Step(&s,in);
            assert(s.mean==mean&&s.trend_filtered==filtered&&!s.valid&&!s.updated);
        }else DobTrendClassifier_Step(&s,in);
        if(k==499)assert(s.valid&&s.state==DTS_LIGHT);
        if(k==899)assert(s.valid&&s.state==DTS_HIGH);
        if(k==1003)assert(!s.resets);
        if(k==1499)reset_at=s.resets;
        if(k==1524)assert(s.resets>reset_at);
        assert(s.coverage>=0&&s.coverage<=1.000001f);
#if defined(DOB_WINDOW_SCALAR_TRACE)
        float values[18]={s.state,s.valid,s.mean,s.trend,s.coverage,s.updated,s.reason,
            s.accepted,s.rejected,s.resets,s.level_changes,s.trend_state,s.trend_valid,
            s.trend_filtered,s.trend_changes,s.level_dwell_us,s.trend_dwell_us,s.proposal};
        assert(fwrite(values,sizeof values,1,f)==1);
#else
        assert(fwrite(&s,sizeof s,1,f)==1);
#endif
    }
    assert(s.valid&&s.state==DTS_LIGHT);
    DobTrendInput in={.encoder_us=3100000,.direction=1,.running=1,.fault=1};
    DobTrendClassifier_Step(&s,in);assert(!s.valid&&!s.trend_valid);
    fclose(f);puts("PASS: light/high/return; rejected spike holds filter; short gaps hold; long gaps reset; fault invalid");
    return 0;
}

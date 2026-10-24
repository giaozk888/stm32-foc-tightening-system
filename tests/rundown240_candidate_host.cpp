#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include "tighten_params_storage.h"
/* Existing C-only inline guard uses (T){0}; keep that code unchanged while
 * exercising its C ABI from this C++ storage harness. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
extern "C" {
#include "tightening_intent_fsm.h"
}
#pragma GCC diagnostic pop
#include "protected_closed_loop.h"

static TightenParamsState_t recipe_state=TIGHTEN_PARAMS_STATE_INITIALIZER;
/* REAL_STARTUP_FUNCTION */

static unsigned saves;
static uint8_t disk[96];
static int load(void *,void *out,size_t n) { assert(n==sizeof disk); std::memcpy(out,disk,n); return 0; }
static int save(void *,const void *in,size_t n) { assert(n==sizeof disk); ++saves; std::memcpy(disk,in,n); return 0; }
static void legacy(void *,void *out,size_t n) { std::memset(out,0xFF,n); }
static void seed_normal_recipe()
{
    /* A normal V1 record, not a second storage implementation under test. */
    struct Record { uint32_t magic,version,size,reserved; TightenParams_t params; uint32_t crc,reserved1; } r;
    static_assert(sizeof r==96 && offsetof(Record,crc)==88,"record ABI");
    std::memset(&r,0xFF,sizeof r);
    r.magic=0x5041524D; r.version=1; r.size=72; r.reserved=0;
    TightenParams_ResetDefaults(&r.params); r.params.rundown_rpm=70; r.params.max_travel_deg=3000;
    uint32_t crc=0xFFFFFFFF;
    const auto *bytes=reinterpret_cast<const uint8_t *>(&r);
    for(unsigned i=0;i<88;++i) {
        crc^=bytes[i];
        for(unsigned b=0;b<8;++b) crc=(crc>>1)^((crc&1) ? 0xEDB88320U : 0U);
    }
    r.crc=~crc; std::memcpy(disk,&r,sizeof r);
}
static TighteningFsm make_fsm(float hard_limit)
{
    TighteningFsmConfig c{};
    TightenParams_ResetDefaults(&c.recipe);
    c.direction=1;
#if defined(FOC_RUNDOWN240_CANDIDATE)
    c.speed_iq_limit_a=FOC_RUNDOWN240_IQ_LIMIT_A;
#else
    c.speed_iq_limit_a=.4f;
#endif
    c.direct_iq_limit_a=.2f;
    c.hard_speed_limit_rpm=hard_limit;
    c.stop_max_rpm=2; c.stop_confirm_ms=150; c.stop_timeout_ms=2000;
    c.session_timeout_ms=12000;
    TighteningFsm s{}; TighteningFsm_Init(&s,c,0); return s;
}
static void step(TighteningFsm &s,uint32_t t,float speed,float pos,float iq,
                 bool start=false,TighteningFsmReason fault=TF_REASON_NONE)
{
    TighteningFsmInput in{};
    in.now_ms=t; in.encoder_valid=1; in.precheck_ready=1; in.start=start;
    in.speed_ctrl_rpm=in.speed_detect_rpm=speed; in.position_deg=pos;
    in.iq_demand_a=iq; in.protection_fault=fault;
    TighteningFsm_Step(&s,in);
}
#if defined(FOC_RUNDOWN240_CANDIDATE)
static void complete_240rpm_fsm_with_synthetic_contact()
{
    /* Process regression only, not a motor/torque simulation or board script.
     * No thresholds are overridden: use the actual 240rpm default recipe. */
    auto s=make_fsm(300);
    unsigned seen=1U<<s.state;
    step(s,10,0,0,0,true); seen|=1U<<s.state;
    step(s,20,0,0,0); seen|=1U<<s.state;
    for(uint32_t t=30;t<=150;t+=10) {
        step(s,t,240,(t-20)*1.44f,.2f); seen|=1U<<s.state;
        assert(s.intent.iq_limit_a==.5f && s.intent.speed_target_rpm==240);
    }
    assert(s.rundown_armed && s.state==TF_RUNDOWN);
    step(s,160,0,187.2f,.35f); seen|=1U<<s.state;
    assert(s.state==TF_CONTACT_CONFIRM && !s.contact_confirmed);
    for(uint32_t t=170;t<=410;t+=10) { step(s,t,0,187.2f,.35f); seen|=1U<<s.state; }
    assert(s.contact_confirmed && s.intent.control_mode==CONTROL_NEUTRAL);
    for(uint32_t t=420;t<=570;t+=10) { step(s,t,0,187.2f,0); seen|=1U<<s.state; }
    assert(s.state==TF_TIGHTEN && s.intent.control_mode==CONTROL_IQ);
    unsigned phases=0;
    const float expected[4]={.08f,.10f,.12f,.15f};
    for(uint32_t t=580;t<=2600 && s.state!=TF_DONE;t+=10) {
        step(s,t,0,187.2f,.10f); seen|=1U<<s.state;
        if(s.state==TF_TIGHTEN) {
            phases|=1U<<s.phase;
            assert(std::fabs(s.intent.iq_target_a-expected[s.phase])<.000001f);
            assert(s.intent.iq_limit_a==.2f && !s.intent.enable_speed_loop);
        }
        if(s.state==TF_HOLD) assert(std::fabs(s.intent.iq_target_a-.15f)<.000001f);
    }
    const unsigned full=(1U<<TF_IDLE)|(1U<<TF_PRECHECK)|(1U<<TF_RUNDOWN_START)|
        (1U<<TF_RUNDOWN)|(1U<<TF_CONTACT_CONFIRM)|(1U<<TF_TIGHTEN)|(1U<<TF_HOLD)|(1U<<TF_DONE);
    assert((seen&full)==full && phases==15);
    assert(s.state==TF_DONE && s.outcome==TF_OUT_OK && s.rundown_armed &&
           s.contact_confirmed && s.tightening_completed && s.fault_reason==TF_REASON_NONE);
    assert(!s.intent.enable_current_loop && s.intent.control_mode==CONTROL_OFF);
}
#endif
int main()
{
    static_assert(sizeof(TightenParams_t)==72,"fallback storage layout");
    seed_normal_recipe(); uint8_t before[96]; std::memcpy(before,disk,sizeof disk);
    TightenParamsStoragePort_t port{nullptr,load,save,legacy};
    recipe_state.kvs_ready=1;
    assert(TightenParams_StorageLoad(&recipe_state,&port)==PARAM_FLASH_LOAD_OK);
    assert(recipe_state.params.rundown_rpm==70 && saves==0);
    const auto original=recipe_state.params;
#if defined(FOC_RUNDOWN240_CANDIDATE)
    static_assert(CL_SPEED_RPM==240 && CL_OVERSPEED_RPM==300,"candidate speed/trip");
    static_assert(CL_MAX_US==12000000,"unchanged lease");
    TightenParams_ApplyRundown240Candidate();
    assert(recipe_state.dirty && recipe_state.params.rundown_rpm==240);
    auto changed=original; changed.rundown_rpm=240;
#if defined(FOC_RUNDOWN240_TRAVEL20000)
    changed.max_travel_deg=20000;
#endif
    assert(std::memcmp(&changed,&recipe_state.params,sizeof changed)==0);
    assert(!TightenParams_StorageSave(&recipe_state,&port) && saves==0);
    assert(std::memcmp(disk,before,sizeof disk)==0);
    assert(TightenParams_TrySet(&recipe_state.params,"RUNDOWN_RPM",241,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
    assert(TightenParams_TrySet(&recipe_state.params,"RUNDOWN_RPM",300,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
    assert(TightenParams_TrySet(&recipe_state.params,"RUNDOWN_RPM",240,0)==TIGHTEN_PARAMS_OK);
    auto s=make_fsm(300);
    step(s,10,0,0,0,true); assert(s.state==TF_PRECHECK);
    step(s,20,0,0,0); assert(s.state==TF_RUNDOWN_START);
    assert(s.intent.speed_target_rpm==240 && s.intent.iq_limit_a==.5f);
    /* Unchanged 50%-speed / 100ms / 3deg motion guard. */
    for(uint32_t t=30;t<=150;t+=10) step(s,t,120,(t-20)*.72f,.35f);
    assert(s.rundown_armed && s.state==TF_RUNDOWN);
    step(s,160,301,100,.35f,false,TF_REASON_OVERSPEED);
    assert(s.state==TF_FAULT && !s.intent.enable_current_loop);
    s=make_fsm(300); step(s,10,0,0,0,true); step(s,20,0,0,0);
    for(uint32_t t=30;t<=1550 && !TighteningFsm_IsFault(&s);t+=10) step(s,t,0,0,.4f);
    assert(s.state==TF_NO_ROTATION && !s.contact_confirmed && s.outcome!=TF_OUT_OK);
    s=make_fsm(240); step(s,10,0,0,0,true);
    assert(s.state==TF_FAULT && s.fault_reason==TF_REASON_PRECHECK);
    complete_240rpm_fsm_with_synthetic_contact();
#if defined(FOC_RUNDOWN240_TRAVEL20000)
    static_assert(TIGHTEN_MAX_TRAVEL_LIMIT_DEG==20000 && TIGHTEN_MAX_TRAVEL_DEFAULT_DEG==20000,"travel candidate");
    assert(TightenParams_TrySet(&recipe_state.params,"MAX_TRAVEL_DEG",20000,0)==TIGHTEN_PARAMS_OK);
    assert(TightenParams_TrySet(&recipe_state.params,"MAX_TRAVEL_DEG",20001,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
    s=make_fsm(300); step(s,10,0,0,0,true); step(s,20,0,0,0);
    for(uint32_t t=30;t<=8020;t+=10) {
        step(s,t,240,(t-20)*1.44f,.15f);
        if(t<8020) assert(!TighteningFsm_IsFault(&s));
    }
    assert(s.state==TF_TIMEOUT && s.fault_reason==TF_REASON_TIMEOUT &&
           s.motion_travel_deg<20000 && !s.contact_confirmed && s.outcome!=TF_OUT_OK);
    s=make_fsm(300); step(s,10,0,0,0,true); step(s,20,0,0,0);
    for(uint32_t t=30;t<=150;t+=10) step(s,t,240,(t-20)*1.44f,.15f);
    assert(s.rundown_armed);
    step(s,160,240,20000,.15f);
    assert(s.state==TF_TIMEOUT && s.fault_reason==TF_REASON_TIMEOUT && !s.intent.enable_current_loop);
#else
    assert(TightenParams_TrySet(&recipe_state.params,"MAX_TRAVEL_DEG",20000,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
#endif
#else
    (void)original;
    static_assert(CL_SPEED_RPM==20 && CL_OVERSPEED_RPM==60,"normal fallback limits");
    static_assert(TIGHTEN_RUNDOWN_DEFAULT_RPM==80 && TIGHTEN_RUNDOWN_MAX_RPM==120,"normal recipe");
    assert(TightenParams_TrySet(&recipe_state.params,"RUNDOWN_RPM",240,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
    assert(TightenParams_TrySet(&recipe_state.params,"MAX_TRAVEL_DEG",20000,0)==TIGHTEN_PARAMS_OUT_OF_RANGE);
    assert(TightenParams_StorageSave(&recipe_state,&port) && saves==1);
    auto s=make_fsm(60); step(s,10,0,0,0,true);
    assert(s.state==TF_FAULT); /* Normal 80rpm defaults are not admitted at 60. */
#endif
    return 0;
}

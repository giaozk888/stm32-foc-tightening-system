#include <assert.h>
#include <math.h>
#include <string.h>
#include "speed_accel_audit.h"
#include "speed_friction_compensation.h"
#include "speed_scurve.h"
int main(void)
{
    for (unsigned gain=0;gain<4;++gain) for (int sign=-1;sign<=1;sign+=2) {
        const float scales[]={0,.25f,.5f,1};float ka=.0001875f*scales[gain];
        SpeedAccelAudit audit={0};SpeedAccelAudit_Reset(&audit);
        SpeedScurve sc;SpeedScurve_Reset(&sc,0);float integral=0;
        for (unsigned k=0;k<3000;++k) {
            float dt=.001f,ref=SpeedScurve_Step(&sc,sign*240.0f,dt);
            float speed=ref-sign*5.f,p=.003f*(ref-speed),candidate=integral+.02f*(ref-speed)*dt;
            SpeedFrictionResult r=SpeedFriction_Apply(integral,candidate,p,sc.acceleration_rpm_s,
                ka,ref,.105f,2.f,.5f,.35f,0,1,1);
            SpeedAccelFfFrame f={.seq=k+1,.ms=k,.speed_ref_rpm=ref,.speed_meas_rpm=speed,
                .accel_ref_rpm_s=sc.acceleration_rpm_s,.iq_pi_a=r.speed.iq_pi_a,.iq_ff_a=r.speed.iq_ff_a,
                .iq_raw_a=r.speed.iq_raw_a,.iq_ref_a=r.speed.iq_ref_a,.speed_integrator_a=r.speed.integral_a,
                .enabled=1,.saturated=r.speed.saturated,.valid=1};
            SpeedAccelFfFrame before=f;SpeedScurve sc_before=sc;
            ++audit.meta.trajectory_updates;
            SpeedAccelAudit_Push(&audit,&f,r.iq_fric_a,sc.phase,dt,ka,.5f,r.speed.aw_limited,0,integral,candidate);
            assert(!memcmp(&before,&f,sizeof f));assert(!memcmp(&sc,&sc_before,sizeof sc));
            integral=r.speed.integral_a;
            assert(fabsf(r.speed.iq_ref_a)<=.5f);
            if (sc.acceleration_rpm_s==0) assert(r.speed.iq_ff_a==0);
            if (gain==0) {
                SpeedFrictionResult off=SpeedFriction_Apply(integral,candidate,p,sc.acceleration_rpm_s,
                    .0001875f,ref,.105f,2.f,.5f,.35f,0,0,1);
                /* Recompute same pre-update state for exact OFF equivalence. */
                SpeedFrictionResult zero=SpeedFriction_Apply(integral,candidate,p,sc.acceleration_rpm_s,
                    0,ref,.105f,2.f,.5f,.35f,0,1,1);
                assert(off.speed.iq_ref_a==zero.speed.iq_ref_a);
                assert(off.speed.integral_a==zero.speed.integral_a);
            }
        }
        assert(audit.meta.samples==3000 && audit.meta.trace_count==16);
        assert(!audit.meta.sync_errors && !audit.meta.formula_errors && !audit.meta.zero_ff_errors);
        assert(!audit.meta.sign_errors && !audit.meta.unexpected_aw_samples);
        assert(fabsf(audit.meta.max_abs_accel-200)<.001f);
        assert(fabsf(audit.meta.max_abs_ff-200*ka)<.000001f);
        assert(fabsf(audit.meta.max_ff_limit_ratio-400*ka)<.000001f);
        assert(audit.frames[0].ms==0 && audit.frames[15].ms==1500);
        uint32_t generation=audit.meta.generation;SpeedAccelAudit_Reset(&audit);
        assert(audit.meta.trace_count==0 && audit.meta.samples==0 && audit.meta.generation==generation+1);
    }
    SpeedAccelAudit s={0};SpeedAccelAudit_Reset(&s);
    SpeedAccelFfFrame f={.valid=1,.enabled=1,.accel_ref_rpm_s=200,.iq_ff_a=-.0375f};
    SpeedAccelAudit_Push(&s,&f,0,1,.001f,.0001875f,.5f,0,0,0,0);
    assert(s.meta.sign_errors==1 && s.meta.formula_errors==1 && s.meta.sync_errors==1);
    f.accel_ref_rpm_s=0;f.iq_ff_a=.01f;
    ++s.meta.trajectory_updates;
    SpeedAccelAudit_Push(&s,&f,0,0,.001f,.0001875f,.5f,0,0,0,0);
    assert(s.meta.zero_ff_errors==1);
    /* Unexpected AW freeze must inspect tentative total, not final sat bit. */
    SpeedAccelAudit_Reset(&s);f=(SpeedAccelFfFrame){.valid=1,.iq_pi_a=.1f,.iq_raw_a=.1f,.iq_ref_a=.1f,.saturated=1};
    ++s.meta.trajectory_updates;
    SpeedAccelAudit_Push(&s,&f,0,0,.001f,.0001875f,.5f,1,0,0,.01f);
    assert(s.meta.unexpected_aw_samples==1);
    return 0;
}

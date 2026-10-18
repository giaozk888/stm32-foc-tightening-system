#include "foc_fast_path_profile.h"
#include "foc_pwm_write_probe.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    _Static_assert(sizeof(FocProfileFrame)==72U,"RAM decoder frame schema");
    _Static_assert(sizeof(FocPathProfile)==168U,"RAM decoder profile schema");
    _Static_assert(sizeof(FocPwmPoint)==16U,"RAM decoder point schema");
    _Static_assert(sizeof(FocPwmWriteProbe)==128U,"RAM decoder PWM schema");
    FocPathProfile s={0}; FocProfileFrame f={0};
    f.wall[0]=200U; f.irq[0]=50U; f.wall[1]=300U; f.irq[1]=20U;
    FocProfile_Record(&s,&f,500U,70U);
    assert(s.frames==1U && s.normal_total_max==500U && s.normal_cpu_max==430U);
    assert(s.cpu_max[0]==150U && s.cpu_max[1]==280U && s.worst_irq==70U);
    f.wall[0]=400U; f.wall[1]=10U;
    f.irq[0]=0U; f.irq[1]=0U;
    FocProfile_Record(&s,&f,410U,0U);
    assert(s.wall_max[0]==400U && s.wall_max[1]==300U);
    assert(s.worst.wall[0]==200U && s.worst.wall[1]==300U); /* Not sum-max. */
    FocProfile_Record(&s,&f,409U,0U); assert(s.invalid==1U);
    f.irq[0]=500U; FocProfile_Record(&s,&f,410U,500U); assert(s.invalid==2U);

    FocPwmWriteProbe p={0};
    FocPwmPoint entry={.dwt=UINT32_MAX-99U,.count=4200U,.down=1U,.valid=1U};
    FocPwmPoint begin={.dwt=0U,.count=4100U,.down=1U,.valid=1U};
    FocPwmPoint end={.dwt=100U,.count=4000U,.down=1U,.valid=1U};
    FocPwm_Observe(&p,4249U,entry,end,1U,begin,170U);
    assert(p.points==1U && p.writes==1U && !p.invalid);
    assert(p.pwm_update_margin_ticks_min==4000 && p.next_uev_ticks_min==4000U);
    assert(p.ccr_write_cycles_max==100U && !p.late_update_count);
    end.dwt=4400U; end.count=300U; end.down=0U;
    FocPwm_Observe(&p,4249U,entry,end,1U,begin,170U);
    assert(p.pwm_update_margin_ticks_min==-300 && p.late_update_count==1U);
    assert(p.possible_suppressed_uev_count==1U); /* Never wrap into next bottom as safe. */
    FocPwmPoint worst_entry=p.entry;
    FocPwmPoint later_entry={.dwt=5000U,.count=4000U,.down=1U,.valid=1U};
    FocPwmPoint later_end={.dwt=5100U,.count=3900U,.down=1U,.valid=1U};
    FocPwm_Observe(&p,4249U,later_entry,later_end,0U,later_end,170U);
    assert(p.entry.dwt==worst_entry.dwt && p.worst.dwt==4400U);
    entry=(FocPwmPoint){.dwt=100U,.count=4200U,.down=0U,.valid=1U};
    end=(FocPwmPoint){.dwt=200U,.count=4198U,.down=1U,.valid=1U,.span=4U};
    FocPwmWriteProbe shadow={0};
    FocPwm_Observe(&shadow,4249U,entry,end,0U,begin,170U);
    assert(shadow.pwm_update_margin_ticks_min==4198 && !shadow.writes);
    assert(shadow.next_uev_ticks_min==4194U && p.writes==2U);
    /* RCR=0 top is only 49 ticks away, not bottom's 4298 ticks. */
    assert(FocPwm_NextUev(4249U,entry)==49U);
    entry.valid=0U; FocPwm_Observe(&shadow,4249U,entry,end,0U,begin,170U);
    assert(shadow.invalid==1U && shadow.points==1U);
    FocPwm_Observe(&shadow,4249U,entry,end,1U,begin,170U);
    assert(shadow.invalid==2U && shadow.points==1U && shadow.writes==1U);
    puts("PASS phase ledger / signed same-bottom margin / UEV / wrap / no-write separation");
    return 0;
}

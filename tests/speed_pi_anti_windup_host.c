#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "speed_pi_anti_windup.h"
#include "speed_bumpless.h"
#include "speed_brake_track.h"

static int near(float a,float b) { return fabsf(a-b)<0.000001f; }
static SpeedPiAntiWindupResult aw(float prev,float candidate,float p,float limit,unsigned release)
{ return SpeedPiAntiWindup_Apply(prev,candidate,p,limit,.35f,(uint8_t)release); }

int main(void)
{
    for (int sign=-1;sign<=1;sign+=2) {
        float s=(float)sign;
        /* Unsaturated control math is identical; exact current boundary. */
        SpeedPiAntiWindupResult r=aw(s*.1f,s*.11f,s*.2f,.5f,0);
        assert(near(r.integral_A,s*.11f) && near(r.current_A,s*.31f) && !r.limited);
        r=aw(s*.29f,s*.31f,s*.2f,.5f,0);
        assert(near(r.integral_A,s*.3f) && near(r.current_A,s*.5f) && r.limited);
        /* Freeze only motion INTO saturation; no old-I restoration. */
        r=aw(s*.32f,s*.34f,s*.3f,.5f,0);
        assert(near(r.integral_A,s*.32f) && near(r.current_A,s*.5f) && r.limited);
        r=aw(s*.32f,s*.31f,s*.3f,.5f,0);
        assert(near(r.integral_A,s*.31f) && !r.limited); /* unwind while still saturated */
        r=aw(s*.31f,s*.30f,-s*.9f,.5f,1);
        assert(near(r.integral_A,s*.30f)); /* mandatory bleed not vetoed */
        r=aw(s*.34f,s*.36f,0,.5f,0);
        assert(near(r.integral_A,s*.35f)); /* original integral clamp */
        r=aw(s*.3f,s*.31f,s*.2f,.2f,0);
        assert(near(r.integral_A,s*.3f) && near(r.current_A,s*.2f)); /* tighter output bound */

        float integral=0;
        for (unsigned tick=0;tick<10000;++tick) {
            r=aw(integral,integral+s*.0004f,s*.6f,.5f,0);
            integral=r.integral_A;
            assert(near(integral,0) && near(r.current_A,s*.5f));
        }
        /* Error reverses: integration can immediately unwind. */
        r=aw(s*.3f,s*.299f,-s*.6f,.5f,0);
        assert(near(r.integral_A,s*.299f));

        /* Actual SB2 helper retained; held load still reaches contact demand. */
        integral=0;
        for (unsigned tick=0;tick<1500;++tick) {
            float ref=s*fminf(240,(float)(tick+1)*.2f),p=.003f*ref;
            SpeedStartupBrakeResult shaped=SpeedBumpless_Apply(integral,
                integral+.020f*ref*.001f,ref,0,.001f,5,5);
            r=aw(integral,shaped.integral_A,p,.5f,0);
            integral=r.integral_A;
            assert(fabsf(r.current_A)<=.500001f && fabsf(integral)<=.350001f);
        }
        assert(near(r.current_A,s*.5f));

        /* SB3 is still the final limiter and tracks its braking command. */
        SpeedBrakeTrack state; SpeedBrakeTrack_Reset(&state);
        float p=s*.003f*(20-10);
        r=aw(s*.2f,s*.2004f,p,.5f,0);
        SpeedBrakeTrackResult b=SpeedBrakeTrack_Apply(&state,s*20,s*10,s*30,p,
            r.integral_A,r.current_A,.003f,5,5,.5f,.35f);
        assert(!b.limited);
        b=SpeedBrakeTrack_Apply(&state,s*20,s*10,s*40,p,
            b.integral_A,b.current_A,.003f,5,5,.5f,.35f);
        assert(b.limited && near(b.current_A,-s*.03f) && near(b.integral_A,-s*.06f));
        r=aw(b.integral_A,b.integral_A+s*.00002f,s*.003f,.5f,0);
        assert(s*r.integral_A<0 && s*r.current_A<0); /* no reload old positive integral */
        SpeedBrakeTrack_Reset(&state); /* original stop/mode reset owner */
        r=aw(0,0,0,.5f,0);
        assert(!state.have_previous && near(r.current_A,0));
    }
    /* Grid properties: bounded output, bounded I, no growth into saturation. */
    for(int p=-100;p<=100;p+=5) for(int prev=-35;prev<=35;prev+=5)
        for(int delta=-10;delta<=10;++delta) {
            float before=(float)prev*.01f, candidate=(float)(prev+delta)*.01f;
            SpeedPiAntiWindupResult r=aw(before,candidate,(float)p*.01f,.5f,0);
            assert(fabsf(r.current_A)<=.500001f && fabsf(r.integral_A)<=.350001f);
            assert(near(r.current_A,fmaxf(-.5f,fminf(.5f,(float)p*.01f+r.integral_A))));
            if (candidate>before && (float)p*.01f+before>=.5f) assert(near(r.integral_A,before));
            if (candidate<before && (float)p*.01f+before<=-.5f) assert(near(r.integral_A,before));
        }
    puts("PASS conditional boundary admission, unwind, SB2/SB3 and current limits; not plant stability");
    return 0;
}

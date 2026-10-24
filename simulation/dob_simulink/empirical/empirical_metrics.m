function m=empirical_metrics(T,c,name,seed,gain,cap,profile)
m=dob_metrics(T,c,name,seed,gain,cap);m.scenario=string(name)+"__"+profile;
m.case_name=string(name);m.profile=profile;
if name=="unloaded_stress",m.detection_delay_s=NaN;m.estimate_recovery_s=NaN;end
window=T.time_s>=2.3&T.time_s<c.stop_s-.1;
m.longest_invalid_ms=longest(~logical(T.dob_valid)&window);
m.rejected_pairs=sum(window&T.lpf_updated==0&bitand(uint32(T.quality_reason),8)~=0);
m.feedback_hold_ms=sum(window&T.feedback_state==3);
m.feedback_fade_ms=sum(window&T.feedback_state==4);
m.compensation_cap_s=sum(window&abs(T.iq_dob_a)>=cap-1e-7)*c.dt;
m.compensation_rms_a=sqrt(mean(T.iq_dob_a(window).^2));
m.actual_iq_peak_a=max(abs(T.iq_true_a));
m.id_filtered_peak_a=max(T.abs_id_lpf_a(window));
end
function n=longest(mask)
n=0;run=0;
for k=1:numel(mask),if mask(k),run=run+1;n=max(n,run);else,run=0;end,end
end

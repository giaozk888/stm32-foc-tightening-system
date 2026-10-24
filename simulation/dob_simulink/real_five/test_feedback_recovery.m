function test_feedback_recovery()
t=(0:.001:.5)';n=numel(t);
T=table(t,zeros(n,1),ones(n,1),zeros(n,1),round(t*1e6)+100000,ones(n,1),zeros(n,1), ...
 'VariableNames',{'time_s','load_ground_truth_a','dob_valid','dob_estimate_a', ...
 'observer_source_us','input_running','simulation_guard_fault'});
r=dob_feedback_recovery(T,.1,.008,.1);assert(abs(r.recovery_s)<1e-8&&abs(r.confirmed_s-.1)<1e-8);
%3ms suspect is not an accepted sample; it does not reset recovery credit.
Q=T;Q.dob_valid(t>=.15&t<.153)=0;Q.dob_estimate_a(Q.dob_valid==0)=.7;
r=dob_feedback_recovery(Q,.1,.008,.1);assert(abs(r.recovery_s)<1e-8&&r.held_ms>0&&r.accepted_epochs<101);
%9ms gap: hold then pause, never advance qualified credit while fading.
Q=T;Q.dob_valid(t>=.15&t<.159)=0;
r=dob_feedback_recovery(Q,.1,.008,.1);assert(abs(r.recovery_s)<1e-8&&r.fade_pause_ms>0&&r.confirmed_s>.1);
%>=20ms resets the metric. There is no reuse of pre-expiry stability credit.
Q=T;Q.dob_valid(t>=.15&t<.175)=0;
r=dob_feedback_recovery(Q,.1,.008,.1);assert(r.recovery_s>=.075-1e-9&&r.expired_events==1);
%Persistent rejection or accepted biased estimates can never pass.
Q=T;Q.dob_valid(:)=0;r=dob_feedback_recovery(Q,.1,.008,.1);assert(isnan(r.recovery_s));
Q=T;Q.dob_estimate_a(:)=.02;r=dob_feedback_recovery(Q,.1,.008,.1);assert(isnan(r.recovery_s));
%Stale supposedly-valid publication is not fresh input.
Q=T;Q.observer_source_us(:)=1;r=dob_feedback_recovery(Q,.1,.008,.1);assert(isnan(r.recovery_s));
%A fresh erroneous estimate resets even with a previous good holding value.
Q=T;Q.dob_estimate_a(abs(t-.15)<1e-9)=.02;
r=dob_feedback_recovery(Q,.1,.008,.1);assert(r.recovery_s>=.051-1e-9);
fprintf('PASS8: hold/pause/expiry, missing!=valid, bias/stale rejection, fresh bad reset\n');
end

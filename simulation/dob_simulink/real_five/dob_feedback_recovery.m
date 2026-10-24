function r=dob_feedback_recovery(T,start_s,tolerance_a,dwell_s)
% SOFTWARE metric only. Does NOT alter DOB validity, filters, feedback or PI.
% Same source freshness/hold/expiry as the existing feedback adapter. Missing
% data never become accepted measurements. 5..20ms fades PAUSE qualification;
% >=20ms expires it. A fresh inaccurate estimate resets qualification.
r=struct('recovery_s',NaN,'confirmed_s',NaN,'held_ms',0,'fade_pause_ms',0, ...
 'expired_events',0,'accepted_epochs',0,'credit_s',0);
last_source=NaN;last_value=NaN;begin=NaN;credit=0;previous=NaN;expired=false;
for k=1:height(T)
 t=T.time_s(k); % Simulator timestamps share the host's documented100000us origin.
 now_us=round(t*1e6)+100020;
 fresh=T.dob_valid(k)~=0&&isfinite(T.dob_estimate_a(k))&& ...
  now_us-T.observer_source_us(k)>=0&&now_us-T.observer_source_us(k)<=2000;
 if fresh
  last_source=T.observer_source_us(k);last_value=T.dob_estimate_a(k);expired=false;
  if t>=start_s,r.accepted_epochs=r.accepted_epochs+1;end
 end
 if t<start_s,previous=t;continue;end
 dt=0;if isfinite(previous),dt=t-previous;end;previous=t;
 age=now_us-last_source;
 if T.input_running(k)==0||T.simulation_guard_fault(k)||~isfinite(age)||age<0||dt<0||dt>.002
  begin=NaN;credit=0;continue;
 end
 if age>=20000
  if ~expired,r.expired_events=r.expired_events+1;expired=true;end
  begin=NaN;credit=0;continue;
 end
 if age>5000
  % Real feedback is fading. Do not label it good or credit missing time.
  r.fade_pause_ms=r.fade_pause_ms+dt*1000;continue;
 end
 if ~fresh,r.held_ms=r.held_ms+dt*1000;end
 if abs(last_value-T.load_ground_truth_a(k))>tolerance_a
  begin=NaN;credit=0;continue;
 end
 if ~isfinite(begin),begin=t;credit=0;else,credit=credit+dt;end
 if credit>=dwell_s-1e-9
  r.recovery_s=begin-start_s;r.confirmed_s=t-start_s;r.credit_s=credit;return;
 end
end
r.credit_s=credit;
end

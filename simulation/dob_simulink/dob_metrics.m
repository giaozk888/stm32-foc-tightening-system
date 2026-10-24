function m=dob_metrics(T,c,name,seed,gain,cap)
t=T.time_s;dt=c.dt;event=t>=c.event_s&t<c.unload_s;
assessment=t>=2.3&t<c.stop_s-.1;ok=T.dob_valid~=0&assessment;
err=T.dob_estimate_a-T.load_ground_truth_a;speed=T.speed_ref_rpm-T.speed_meas_rpm;
m=struct('scenario',string(name),'seed',seed,'gain',gain,'cap_a',cap, ...
 'estimate_rmse_a',sqrt(mean(err(ok).^2)),'estimate_bias_a',mean(err(ok)), ...
 'estimate_peak_error_a',max(abs(err(ok)),[],'omitnan'), ...
 'valid_rate',sum(ok)/sum(assessment),'reset_calls',sum(T.epoch_resets(assessment)), ...
 'warmup_unavailable_s',sum(T.dob_valid==0&assessment&T.warmup_s>0)*dt, ...
 'warmup_total_s',sum(T.dob_valid==0&T.warmup_s>0)*dt,'first_valid_time_s',NaN, ...
 'detection_delay_s',NaN,'estimate_recovery_s',NaN, ...
 'speed_mae_rpm',mean(abs(speed(assessment))),'load_speed_mae_rpm',mean(abs(speed(event))), ...
 'speed_dip_rpm',max(sign(mean(T.target_rpm(event)))*(T.target_rpm(event)-T.rpm_true(event))), ...
 'speed_recovery_s',NaN,'unload_overshoot_rpm',0, ...
 'iq_peak_a',max(abs(T.iq_cmd_a)),'integrator_peak_a',max(abs(T.speed_integrator_a)), ...
 'iq_saturation_s',sum(abs(T.iq_raw_a-T.iq_cmd_a)>1e-7|abs(T.iq_cmd_a)>=.5-1e-7)*dt, ...
 'false_comp_unloaded_rms_a',NaN,'guard_faults',max(T.simulation_guard_fault), ...
 'cap_obeyed',all(abs(T.iq_dob_a)<=cap+1e-7),'total_limit_obeyed',all(abs(T.iq_cmd_a)<=.5+1e-7), ...
 'finite',all(isfinite(table2array(T(:,cellstr(dob_schema())))),'all'),'direction_ok',true);
first_valid=find(T.dob_valid~=0,1);if ~isempty(first_valid),m.first_valid_time_s=t(first_valid);end
if any(abs(T.load_ground_truth_a)>.001)
 direction=sign(mean(T.load_ground_truth_a(event)));
 hit=find(t>=c.event_s&T.dob_valid~=0&direction*T.dob_estimate_a>=.5*c.load_a,1);
 true_hit=find(t>=c.event_s&direction*T.load_ground_truth_a>=.5*c.load_a,1);
 if ~isempty(hit)&&~isempty(true_hit),m.detection_delay_s=t(hit)-t(true_hit);end
 steady=ok&t>=c.event_s+.8&t<c.unload_s-.1;
 m.direction_ok=any(steady)&&direction*mean(T.dob_estimate_a(steady))>0;
 % Five-percent-or-2rpm recovery requires continuous 100 ms dwell. Recovery
 % means first return AFTER the peak drop, not the pre-disturbance good point.
 [~,peak]=max(abs(speed(event)));ids=find(event);start=ids(peak);
 m.speed_recovery_s=dwell(t,abs(speed)<=max(2,.05*abs(c.target_rpm)),t(start),.1);
 if isfinite(m.speed_recovery_s),m.speed_recovery_s=m.speed_recovery_s+t(start)-c.event_s;end
end
tail=t>=c.unload_s&t<c.unload_s+.8;
direction=sign(mean(T.target_rpm(event)));if direction==0,direction=1;end
m.unload_overshoot_rpm=max(0,max(direction*(T.rpm_true(tail)-T.target_rpm(tail))));
m.estimate_recovery_s=dwell(t,T.dob_valid~=0&abs(err)<=c.accept.bias_a,c.unload_s,.1);
unloaded=assessment&abs(T.load_ground_truth_a)<1e-8&t>c.unload_s+.8;
m.false_comp_unloaded_rms_a=sqrt(mean(T.iq_dob_a(unloaded).^2));
if isempty(m.estimate_peak_error_a),m.estimate_peak_error_a=NaN;end
end

function value=dwell(t,condition,start,duration)
value=NaN;first=0;
for k=find(t>=start)'
 if condition(k)
  if first==0,first=k;end
  if t(k)-t(first)>=duration-1e-9,value=t(first)-start;return;end
 else,first=0;end
end
end

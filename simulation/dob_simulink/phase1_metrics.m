function m=phase1_metrics(T,name,seed,enabled)
t=T.time_s;eval=t>=2.3&t<6.9;
good=T.load_label_valid>0;truth=sign(T.target_rpm).*T.load_ground_truth_a;
% Event windows reference the simulator's independent load, NOT the observer.
high=eval&truth>=.025;light=eval&truth<=.010;
m=struct('scenario',string(name),'seed',seed,'features_enabled',enabled, ...
    'valid_rate',mean(good(eval)),'unknown_rate',mean(~good(eval)), ...
    'quality_reset_count',T.load_quality_resets(end),'transitions',T.load_transitions(end), ...
    'dob_reset_count',T.reset_count(end),'guard_fault',max(T.simulation_guard_fault), ...
    'high_recall',fraction(T.load_state==4&good,high), ...
    'false_high_rate',fraction(T.load_state==4&good,light), ...
    'load_rmse_a',NaN,'rise_delay_s',NaN,'high_delay_s',NaN, ...
    'release_delay_s',NaN,'return_light_delay_s',NaN, ...
    'speed_mae_rpm',mean(abs(T.speed_ref_rpm(eval)-T.speed_meas_rpm(eval))), ...
    'iq_peak_a',max(abs(T.iq_cmd_a)),'iq_dob_peak_a',max(abs(T.iq_dob_a)), ...
    'pre_event_rising',0,'pre_event_high',0,'pre_unload_falling',0);
if any(eval&good),m.load_rmse_a=sqrt(mean((T.load_mean_a(eval&good)-truth(eval&good)).^2));end
idx=find(t>=2.3&abs(T.load_ground_truth_a)>.005,1);
if ~isempty(idx)
    event=t(idx);last=find(t>event&abs(T.load_ground_truth_a)<.001,1);
    finish=6.9;if ~isempty(last),finish=t(last);end
    if ismember('load_trend_state',T.Properties.VariableNames)
        rise=T.load_trend_state==2&T.load_trend_valid>0;
        fall=T.load_trend_state==3&T.load_trend_valid>0;
    else
        rise=T.load_state==3&good;fall=T.load_state==5&good;
    end
    m.rise_delay_s=delay(t,rise,event,finish);
    m.pre_event_rising=prior(t,rise,event);
    m.pre_event_high=prior(t,T.load_state==4&good,event);
    if any(truth(t>=event&t<finish)>=.025)
        m.high_delay_s=delay(t,T.load_state==4&good,event,finish);
    end
    if ~isempty(last)
        m.release_delay_s=delay(t,fall,t(last),6.9);
        m.pre_unload_falling=prior(t,fall,t(last));
        m.return_light_delay_s=delay(t,T.load_state==1&good,t(last),6.9);
    end
end
end
function r=fraction(condition,mask)
if any(mask),r=mean(condition(mask));else,r=NaN;end
end
function d=delay(t,condition,start,finish)
% A label active BEFORE the physical event is a false/ambiguous activation,
% not a perfect zero-latency detector. Preserve NaN and report that fact.
d=NaN;if prior(t,condition,start),return;end
edge=condition&~[false;condition(1:end-1)];
j=find(t>=start&t<finish&edge,1);if ~isempty(j),d=t(j)-start;end
end
function b=prior(t,condition,start)
j=find(t<start,1,'last');b=~isempty(j)&&condition(j);
end

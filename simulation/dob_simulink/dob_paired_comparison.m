function P=dob_paired_comparison(M)
metrics={'speed_dip_rpm','speed_recovery_s','load_speed_mae_rpm','unload_overshoot_rpm', ...
 'iq_peak_a','iq_saturation_s','false_comp_unloaded_rms_a','valid_rate','reset_calls'};
ON=M(M.gain~=0,:);OFF=M(M.gain==0,:);rows=struct([]);n=0;
for i=1:height(ON)
 base=OFF(OFF.scenario==ON.scenario(i)&OFF.seed==ON.seed(i),:);assert(height(base)==1);
 n=n+1;r=struct('scenario',ON.scenario(i),'seed',ON.seed(i),'gain',ON.gain(i),'cap_a',ON.cap_a(i));
 for j=1:numel(metrics)
  key=metrics{j};d=ON.(key)(i)-base.(key);r.(['delta_' key])=d;
  if strcmp(key,'valid_rate'),d=-d;end % Higher validity is better.
  r.(['improved_' key])=double(d<0);r.(['worsened_' key])=double(d>0);
 end
 if n==1,rows=r;else,rows(n)=r;end
end
if isempty(rows),P=table;else
 trials=struct2table(rows);
 numeric=trials.Properties.VariableNames(startsWith(trials.Properties.VariableNames,{'delta_','improved_','worsened_'}));
 P=groupsummary(trials,{'scenario','gain','cap_a'},{'mean','std'},numeric);
end
end

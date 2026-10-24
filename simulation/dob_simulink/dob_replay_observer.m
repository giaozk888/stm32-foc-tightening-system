function result=dob_replay_observer(path,c)
% Actual measured epoch contract, rad/s and A, timestamps uint32 microseconds.
% Use raw signed timestamps from one coherent capture. This does not route
% anything to a controller or synthesize load truth from the DOB estimate.
fields=["observed_us","encoder_us","dt_us","omega_rad_s","id_a","iq_a", ...
 "adc_seq","adc_source_us","adc_published_us","current_valid", ...
 "iq_saturated","current_flags","running","fault"];
T=readtable(path);assert(all(ismember(fields,string(T.Properties.VariableNames))),'Missing explicit replay metadata');
U=table2array(T(:,cellstr(fields)));assert(all(isfinite(U),'all'),'Nonfinite input must be explicitly marked and audited, not silently interpolated');
assert(all(mod(diff(T.encoder_us),2^32)==T.dt_us(2:end)),'Sparse epochs without exact dt: cannot reconstruct observer history');
dob_bridge_mex('reset',fullfile(c.build,'dob_host.dll'),[0,0,.025]);Y=zeros(height(T),33);
for k=1:height(T),Y(k,:)=dob_bridge_mex('observe',U(k,:));end
R=array2table(Y,'VariableNames',cellstr(dob_schema()));
R.observed_us=T.observed_us;R.ground_truth_available=false(height(T),1);
[folder,name]=fileparts(path);writetable(R,fullfile(folder,[name '_replayed.csv']));
result=struct('rows',height(T),'valid_rate',mean(R.dob_valid~=0), ...
 'resets',sum(R.epoch_resets),'ground_truth_available',false,'estimate_rmse_a',[], ...
 'physical_performance_validated',false,'note','Observer-only replay, no load truth, no actuator output.');
dob_write_json(fullfile(folder,[name '_replayed.json']),result);
end

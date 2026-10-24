function audit=audit_dob_feedback_scan(dest)
% Independent saved-trace audit. No simulations, compilation or hardware I/O.
root=fileparts(fileparts(mfilename('fullpath')));
env=fullfile(root,'simulation','dob_simulink','real_five');
addpath(env,fileparts(env),fullfile(fileparts(env),'empirical'));
if nargin==0,dest=fullfile(env,'feedback_aware_results');end
R=jsondecode(fileread(fullfile(dest,'report.json')));
M=readtable(fullfile(dest,'metrics_per_trial.csv'),'TextType','string');
assert(R.on_trials==1800&&R.off_trials_reused==200&&height(M)==2000);
assert(R.repeats_per_group==100&&~R.hardware_access&&~R.physical_performance_validated);
assert(strcmp(dob_sha256(fullfile(env,'results','metrics_per_trial.csv')),R.baseline_metrics_sha256));
for pin=[R.sources(:);R.native_artifacts(:)]'
 assert(strcmp(dob_sha256(pin.path),pin.sha256),'Source/artifact changed');
end
columns={'time_s','target_rpm','load_ground_truth_a','speed_noise_rpm', ...
 'iq_noise_a','id_raw_a','physical_current_pulse_a','input_valid', ...
 'input_voltage_sat','input_encoder_age_us','input_running'};
baseline=containers.Map('KeyType','char','ValueType','any');
scratch=tempname(dest);mkdir(scratch);cleanup=onCleanup(@()rmdir(scratch)); %#ok<NASGU>
off=M(M.gain==0,:);on=M(M.gain~=0,:);
assert(height(off)==200&&height(on)==1800);
for k=1:height(off)
 m=off(k,:);label=sprintf('%s_seed%03d_g0_cap0.025',m.case_name,m.seed);
 paths=gunzip(fullfile(env,'results',[label '.csv.gz']),scratch);
 T=readtable(paths{1});delete(paths{1});
 baseline(sprintf('%s_%d',m.case_name,m.seed))=table2array(T(:,columns));
end
quarantined=0;all_rows=0;max_delta=0;guard_trials=0;gate_failures=0;ramp_csv=0;
for k=1:height(on)
 m=on(k,:);label=sprintf('%s_seed%03d_g%g_cap%g',m.case_name,m.seed,m.gain,m.cap_a);
 S=load(fullfile(dest,[label '.mat']),'T');T=S.T;
 assert(height(T)==7001&&all(isfinite(table2array(T)),'all'));
 assert(all(abs(T.iq_cmd_a)<=.5+1e-7));
 assert(all(abs(T.iq_dob_a)<=m.cap_a+1e-7));
 assert(abs(max(abs(T.iq_cmd_a))-m.iq_peak_a)<1e-10);
 delta=max(abs(table2array(T(:,columns))-baseline(sprintf('%s_%d',m.case_name,m.seed))),[],'all');
 assert(delta<=1e-10&&abs(delta-m.paired_input_max_abs_delta)<=1e-10);
 max_delta=max(max_delta,delta);
 rejected=bitand(uint32(T.quality_reason),8)~=0&T.lpf_updated==0;
 assert(all(T.abs_id_lpf_a(rejected)==T.id_lpf_before_a(rejected)));
 quarantined=quarantined+sum(rejected);all_rows=all_rows+height(T);
 assert(max(T.simulation_guard_fault)==m.guard_faults);
 guard_trials=guard_trials+(m.guard_faults~=0);gate_failures=gate_failures+~m.feedback_gate_pass;
 % Fixed even seeds supplement the runner's fixed odd-seed step CSVs. No
 % outcome-dependent example selection; all original MAT data are unchanged.
 if ismember(m.seed,[2,62])
  writetable(T,fullfile(dest,[label '.csv']));ramp_csv=ramp_csv+1;
 end
 % Metric assertions above do not require every trial to succeed: failures
 % are retained in the complete population, not silently dropped/retried.
 if mod(k,100)==0,fprintf('AUDIT %d/1800 saved ON traces\n',k);end
end
for hyp=["measurement","torque"]
 for gain=[.15,.25,.5]
  for cap=[.00625,.0125,.025]
   seeds=on.seed(on.case_name==hyp&on.gain==gain&abs(on.cap_a-cap)<1e-12);
   assert(isequal(sort(seeds),(1:100)'));
  end
 end
end
audit=struct('passed',true,'on_traces_checked',height(on), ...
 'off_inputs_reused_checked',height(off),'on_rows_checked',all_rows, ...
 'actual_input_pairs_checked',height(on),'maximum_input_abs_delta',max_delta, ...
 'quarantined_lpf_unchanged_checks',quarantined, ...
 'guard_fault_trials',guard_trials,'feedback_gate_failed_trials',gate_failures, ...
 'supplemental_ramp_csv',ramp_csv,'ramp_csv_seeds',[2,62], ...
 'all_groups_100_unique_seeds',true,'pins_unchanged',true, ...
 'hardware_access',false,'physical_performance_validated',false);
dob_write_json(fullfile(dest,'independent_audit.json'),audit);
disp(audit);
end

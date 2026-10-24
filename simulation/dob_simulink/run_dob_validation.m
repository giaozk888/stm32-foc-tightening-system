function report=run_dob_validation(mode)
% MATLAB/Simulink offline only. First build, native contracts, observer OFF
% qualification; ONLY then simulation compensation scans. No board APIs.
if nargin==0,mode="full";end
c=build_dob_simulink();storage=dob_storage_session(c); %#ok<NASGU>
addpath(fullfile(c.root,'tests'));
if ~isfolder(c.results),mkdir(c.results);end
native=test_dob_native(c);
set_param(c.model,'FastRestart','on');
fast_restart_cleanup=onCleanup(@()set_param(c.model,'FastRestart','off')); %#ok<NASGU>
scenarios=["no_load","step","ramp","unload","negative_step","noise", ...
 "spike","persistent_id","short_gap","long_gap","voltage_sat"];
if mode=="smoke",c.seeds=101:103;scenarios=["no_load","step","negative_step","spike","persistent_id"];end
rows=struct([]);n=0;gate=true;
for scenario=scenarios
 for seed=c.seeds
  T=dob_run_case(c,scenario,seed,0,.025);n=n+1;
  test_dob_simulink_case(T,c);
  metrics=dob_metrics(T,c,scenario,seed,0,.025);
  if n==1,rows=metrics;else,rows(n)=metrics;end
  label=sprintf('%s_seed%d_OFF',scenario,seed);
  writetable(T,fullfile(c.results,[label '.csv']));
  dob_plot_case(T,fullfile(c.results,[label '.png']),label);
  assert(rows(n).finite&&rows(n).cap_obeyed&&rows(n).total_limit_obeyed&&~rows(n).guard_faults);
  % Isolated spike must not enter filters/reset. Other gate faults are
  % preserved and reported, not hidden to force availability to 100%.
  if scenario=="spike"
   q=find(abs(T.time_s-3.8)<1e-8);assert(T.lpf_updated(q)==0&&T.epoch_resets(q)==0);
   assert(T.abs_id_lpf_a(q)==T.abs_id_lpf_a(q-1));
  end
  baselineScenario=ismember(scenario,["no_load","step","ramp","unload","negative_step","noise","spike"]);
  if baselineScenario
   gate=gate&&rows(n).estimate_rmse_a<=c.accept.rmse_a&& ...
    abs(rows(n).estimate_bias_a)<=c.accept.bias_a&&rows(n).valid_rate>=c.accept.valid_rate&&rows(n).direction_ok;
   if scenario~="no_load"
    gate=gate&&rows(n).detection_delay_s<=c.accept.delay_s&&rows(n).estimate_recovery_s<=c.accept.recovery_s;
   end
  end
  fprintf('OFF %s seed%d RMSE=%.5f A valid=%.1f%% resets=%d\n',scenario,seed,rows(n).estimate_rmse_a,100*rows(n).valid_rate,rows(n).reset_calls);
 end
end
dob_replay(fullfile(c.results,sprintf('step_seed%d_OFF.csv',c.seeds(1))),c);
estimator=struct('passed',gate,'criteria',c.accept,'native_passed',native.passed, ...
 'compensation_scan_allowed',gate,'physical_performance_validated',false);
dob_write_json(fullfile(c.results,'estimator_gate.json'),estimator);
if gate
 for scenario=scenarios
  for gain=c.gains(c.gains~=0)
   for cap=c.caps_a
    for seed=c.seeds
     T=dob_run_case(c,scenario,seed,gain,cap);n=n+1;
     test_dob_simulink_case(T,c);
     rows(n)=dob_metrics(T,c,scenario,seed,gain,cap);
     assert(rows(n).finite&&rows(n).cap_obeyed&&rows(n).total_limit_obeyed&&~rows(n).guard_faults);
     if any(abs(T.load_ground_truth_a)>.001)
      mature=T.time_s>c.event_s+.8&T.time_s<c.unload_s-.1&T.dob_valid~=0;
      assert(any(mature)&&max(abs(T.iq_dob_a(mature)))>1e-4,'Requested ON did not apply compensation');
      assert(mean(T.iq_dob_a(mature))*mean(T.load_ground_truth_a(mature))>0,'Compensation direction error');
     end
     label=sprintf('%s_seed%d_gain%g_cap%g',scenario,seed,gain,cap);
     writetable(T,fullfile(c.results,[label '.csv']));
     dob_plot_case(T,fullfile(c.results,[label '.png']),label);
     if mod(n,10)==0
      writetable(struct2table(rows),fullfile(c.results,'metrics_progress.csv'));
      fprintf('ON progress: %d trials saved\n',n);
     end
    end
   end
  end
  fprintf('ON scan complete: %s\n',scenario);
 end
else
 fprintf('ESTIMATOR GATE FAILED: ON scans NOT RUN. See estimator_gate.json.\n');
end
M=struct2table(rows);writetable(M,fullfile(c.results,'metrics_per_trial.csv'));
numeric=M.Properties.VariableNames(varfun(@isnumeric,M,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
summary=groupsummary(M,{'scenario','gain','cap_a'},{'mean','std'},numeric);
writetable(summary,fullfile(c.results,'metrics_mean_std.csv'));
paired=dob_paired_comparison(M);writetable(paired,fullfile(c.results,'paired_on_minus_off.csv'));
manifest=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
for k=1:numel(manifest.sources)
 assert(strcmp(dob_sha256(manifest.sources(k).path),manifest.sources(k).sha256), ...
  'Source changed during offline run (firmware or harness): %s',manifest.sources(k).path);
end
report=struct('simulator','MATLAB Simulink','mode',mode,'trials',height(M),'repeats',numel(c.seeds), ...
 'estimator_passed',gate,'on_scan_executed',gate,'firmware_sources_unchanged',true, ...
 'hardware_access',false,'physical_performance_validated',false, ...
 'unvalidated',{{'real motor/electrical FOC','ADC/PWM/CUR_CONFIRM timing','real load torque','hardware protection and WCET'}}, ...
 'configuration',c);
dob_write_json(fullfile(c.results,'report.json'),report);
dob_write_report(c,M,summary,paired,report);
fprintf('DONE %d Simulink runs. Physical motor performance NOT validated.\n',height(M));
end

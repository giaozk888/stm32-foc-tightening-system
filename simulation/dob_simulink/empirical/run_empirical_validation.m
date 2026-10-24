function report=run_empirical_validation(mode)
% Empirical event-conditioned Simulink stress, NOT full real-data replay.
if nargin==0,mode="full";end
c=prepare_empirical_model();storage=dob_storage_session(c); %#ok<NASGU>
if string(mode)=="smoke",c.seeds=101;c.results=fullfile(c.root,'smoke_results');end
if ~isfolder(c.results),mkdir(c.results);end
pins=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
for k=1:numel(pins.sources),assert(strcmp(dob_sha256(pins.sources(k).path),pins.sources(k).sha256));end
files=[dir(fullfile(c.root,'*.m'));dir(fullfile(c.root,'*.py'));dir(fullfile(c.root,'java.opts'))];frozen=struct([]);
for k=1:numel(files)
 frozen(k).path=fullfile(files(k).folder,files(k).name);
 frozen(k).sha256=dob_sha256(frozen(k).path);
end
set_param(c.model,'FastRestart','on');
cleanup=onCleanup(@()set_param(c.model,'FastRestart','off')); %#ok<NASGU>
rows=struct([]);gates=struct([]);n=0;
for name=c.cases
 passed=true;
 for seed=c.seeds
  T=empirical_run_case(c,name,seed,0,.025);
  m=empirical_metrics(T,c,name,seed,0,.025,"nominal");
  ok=m.estimate_rmse_a<=c.accept.rmse_a&&abs(m.estimate_bias_a)<=c.accept.bias_a&& ...
   m.valid_rate>=c.accept.valid_rate&&m.direction_ok;
  if name~="unloaded_stress",ok=ok&&m.detection_delay_s<=c.accept.delay_s&&m.estimate_recovery_s<=c.accept.recovery_s;end
  passed=passed&&ok;n=n+1;if n==1,rows=m;else,rows(n)=m;end
  save_trial(T,c,name,seed,0,.025);
  fprintf('OFF %s %d RMSE %.3fmA valid %.2f%% reset %d longest-invalid %gms gate %d\n', ...
   name,seed,1000*m.estimate_rmse_a,100*m.valid_rate,m.reset_calls,m.longest_invalid_ms,ok);
 end
 gates(end+1).scenario=char(name);gates(end).profile='nominal';gates(end).passed=passed; %#ok<AGROW>
end
dob_write_json(fullfile(c.results,'estimator_gates.json'),struct('criteria',c.accept,'scenarios',gates));
for j=1:numel(gates)
 name=string(gates(j).scenario);
 if ~gates(j).passed,fprintf('ON SKIPPED: %s failed estimator gate.\n',name);continue;end
 for gain=c.gains(c.gains~=0)
  for seed=c.seeds
   T=empirical_run_case(c,name,seed,gain,.025);
   n=n+1;rows(n)=empirical_metrics(T,c,name,seed,gain,.025,"nominal");
   save_trial(T,c,name,seed,gain,.025);
   fprintf('ON %s seed%d g%g MAE %.4frpm comp peak %.3fmA\n',name,seed,gain,rows(n).load_speed_mae_rpm,1000*max(abs(T.iq_dob_a)));
  end
 end
end
% Bounded model-assumption sensitivity, NOT confidence intervals for J/B.
% Only the simulated plant changes; the original C controller stays frozen.
nominal_plant=c.plant_vector;
if string(mode)=="full"
 profiles=["lighter_faster","heavier_slower"];
 factors=[.7,.9,.0005;1.3,1.1,.002]; % J/Kt factor, B/Kt factor, current-lag s
 for p=1:numel(profiles)
  set_param(c.model,'FastRestart','off');c.plant_vector=nominal_plant;
  c.plant_vector(1:2)=nominal_plant(1:2).*factors(p,1:2);c.plant_vector(5)=factors(p,3);
  ws=get_param(c.model,'ModelWorkspace');assignin(ws,'plant_parameters',c.plant_vector);
  set_param(c.model,'FastRestart','on');
  for name=["measurement_train","torque_train"]
   passed=true;
   for seed=c.seeds(1:3)
    T=empirical_run_case(c,name,seed,0,.025);
    n=n+1;rows(n)=empirical_metrics(T,c,name,seed,0,.025,profiles(p));m=rows(n);
    passed=passed&&m.estimate_rmse_a<=c.accept.rmse_a&&abs(m.estimate_bias_a)<=c.accept.bias_a&& ...
     m.valid_rate>=c.accept.valid_rate&&m.direction_ok&&m.detection_delay_s<=c.accept.delay_s&&m.estimate_recovery_s<=c.accept.recovery_s;
    save_trial(T,c,name,seed,0,.025,profiles(p));
   end
   gates(end+1)=struct('scenario',char(name),'profile',char(profiles(p)),'passed',passed); %#ok<AGROW>
   fprintf('Sensitivity OFF %s %s passed %d\n',profiles(p),name,passed);
   if ~passed,continue;end
   for seed=c.seeds(1:3)
    T=empirical_run_case(c,name,seed,.25,.025);
    n=n+1;rows(n)=empirical_metrics(T,c,name,seed,.25,.025,profiles(p));
    save_trial(T,c,name,seed,.25,.025,profiles(p));
   end
  end
 end
 c.plant_vector=nominal_plant;
end
dob_write_json(fullfile(c.results,'estimator_gates.json'),struct('criteria',c.accept,'scenarios',gates));
M=struct2table(rows);writetable(M,fullfile(c.results,'metrics_per_trial.csv'));
numeric=M.Properties.VariableNames(varfun(@isnumeric,M,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
S=groupsummary(M,{'scenario','gain','cap_a'},{'mean','std'},numeric);
writetable(S,fullfile(c.results,'metrics_mean_std.csv'));
writetable(dob_paired_comparison(M),fullfile(c.results,'paired_on_minus_off.csv'));
for k=1:numel(pins.sources),assert(strcmp(dob_sha256(pins.sources(k).path),pins.sources(k).sha256));end
for k=1:numel(frozen),assert(strcmp(dob_sha256(frozen(k).path),frozen(k).sha256));end
report=struct('trials',height(M),'repeats',numel(c.seeds),'firmware_and_base_sources_unchanged',true, ...
 'hardware_access',false,'physical_performance_validated',false, ...
 'full_historical_replay',false,'event_frequency_measured',false, ...
 'event_manifest_sha256',dob_sha256(fullfile(c.root,'data','manifest.json')), ...
 'empirical_sources',frozen,'configuration',c,'estimator_gates',gates);
dob_write_json(fullfile(c.results,'report.json'),report);
fprintf('DONE %d trials; no physical validation or firmware changes.\n',height(M));
end

function save_trial(T,c,name,seed,gain,cap,profile)
if nargin<7,profile="nominal";end
if profile~="nominal",name=string(name)+"__"+profile;end
label=sprintf('%s_seed%d_g%g_cap%g',name,seed,gain,cap);
writetable(T,fullfile(c.results,[label '.csv']));
end

function report=run_real_five_scan(mode)
% All100 repeats are SOFTWARE trials, not independent physical measurements.
if nargin==0,mode="full";end
c=prepare_real_five();storage=dob_storage_session(c); %#ok<NASGU>
if string(mode)=="smoke",c.seeds=[1,61];c.results=fullfile(c.root,'smoke_results');mkdir(c.results);end
% Existing C/native pins must still match. Source-only diagnostic additions
% to MCU main/CMake are recorded separately, never silently rebuild old DLL.
old=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
for k=1:numel(old.sources)
 p=old.sources(k).path;
 if contains(p,[filesep 'firmware_common' filesep])&&~endsWith(p,'dob_real_trace.h')&&~endsWith(p,'dob_real_trace.c')
  assert(strcmp(dob_sha256(p),old.sources(k).sha256),'Original C primitive changed: %s',p);
 elseif contains(p,[filesep 'native' filesep])
  assert(strcmp(dob_sha256(p),old.sources(k).sha256),'Native host changed: %s',p);
 end
end
files=[dir(fullfile(c.root,'*.m'));dir(fullfile(c.root,'*.py'))];frozen=struct([]);
for k=1:numel(files),frozen(k).path=fullfile(files(k).folder,files(k).name);frozen(k).sha256=dob_sha256(frozen(k).path);end
artifact=struct([]);for k=1:4
 names={'dob_host.dll','dob_controller_sfun.mexw64','dob_plant_sfun.mexw64','dob_bridge_mex.mexw64'};
 artifact(k).path=fullfile(c.build,names{k});artifact(k).sha256=dob_sha256(artifact(k).path);
end
set_param(c.model,'FastRestart','on');cleanup=onCleanup(@()shutdown_model(c.model)); %#ok<NASGU>
rows=struct([]);n=0;baselines=containers.Map('KeyType','char','ValueType','any');
gates=struct([]);started=tic;
for hypothesis=["measurement","torque"]
 passed=true;
 for seed=c.seeds
  [T,amplitude]=real_five_run_case(c,hypothesis,seed,0,.025);
  mc=c;mc.load_a=amplitude;
  m=empirical_metrics(T,mc,hypothesis,seed,0,.025,"fixed_model");
  ok=m.estimate_rmse_a<=c.accept.rmse_a&&abs(m.estimate_bias_a)<=c.accept.bias_a&& ...
   m.valid_rate>=c.accept.valid_rate&&m.direction_ok&&~m.guard_faults&& ...
   m.detection_delay_s<=c.accept.delay_s&&m.estimate_recovery_s<=c.accept.recovery_s;
  passed=passed&&ok;
  m.split=split(seed);m.estimator_trial_pass=ok;
  n=n+1;if n==1,rows=m;else,rows(n)=m;end
  baselines(key(hypothesis,seed))=input_hash(T);
  save_trial(T,c,hypothesis,seed,0,.025);
  if mod(n,10)==0,fprintf('OFF progress %d RMSE %.2fmA valid %.1f%% elapsed %.0fs\n',n,m.estimate_rmse_a*1e3,m.valid_rate*100,toc(started));end
 end
 gate_row=struct('hypothesis',char(hypothesis),'passed',passed);
 if isempty(gates),gates=gate_row;else,gates(end+1)=gate_row;end %#ok<AGROW>
 fprintf('ESTIMATOR %s all trials pass %d\n',hypothesis,passed);
end
dob_write_json(fullfile(c.results,'estimator_gates.json'),struct('criteria',c.accept,'hypotheses',gates));
for j=1:numel(gates)
 hypothesis=string(gates(j).hypothesis);
 if ~gates(j).passed,fprintf('ON SKIPPED %s; estimator gate failed, do not tune around failure\n',hypothesis);continue;end
 for gain=c.gains
  for cap=c.caps_a
   for seed=c.seeds
    [T,amplitude]=real_five_run_case(c,hypothesis,seed,gain,cap);
    assert(strcmp(input_hash(T),baselines(key(hypothesis,seed))),'Actual OFF/ON inputs differ');
    mc=c;mc.load_a=amplitude;m=empirical_metrics(T,mc,hypothesis,seed,gain,cap,"fixed_model");
    m.split=split(seed);m.estimator_trial_pass=true;n=n+1;rows(n)=m;
    save_trial(T,c,hypothesis,seed,gain,cap);
    if mod(n,25)==0
     writetable(struct2table(rows),fullfile(c.results,'metrics_progress.csv'));
     fprintf('ON progress %d %s gain%g cap%g elapsed %.0fs\n',n,hypothesis,gain,cap,toc(started));
    end
   end
  end
 end
end
M=struct2table(rows);writetable(M,fullfile(c.results,'metrics_per_trial.csv'));
numeric=M.Properties.VariableNames(varfun(@isnumeric,M,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
S=groupsummary(M,{'scenario','split','gain','cap_a'},{'mean','std'},numeric);
writetable(S,fullfile(c.results,'metrics_mean_std.csv'));
writetable(dob_paired_comparison(M),fullfile(c.results,'paired_on_minus_off.csv'));
for k=1:numel(frozen),assert(strcmp(dob_sha256(frozen(k).path),frozen(k).sha256));end
for k=1:numel(artifact),assert(strcmp(dob_sha256(artifact(k).path),artifact(k).sha256));end
report=struct('trials',height(M),'software_repeats_per_group',numel(c.seeds), ...
 'physical_motor_runs',5,'physical_windows_s',.192,'physical_performance_validated',false, ...
 'hardware_access',false,'full_historical_replay',false,'sources',frozen,'native_artifacts',artifact, ...
 'configuration',c,'gates',gates,'data_manifest_sha256',dob_sha256(fullfile(c.root,'data','manifest.json')));
dob_write_json(fullfile(c.results,'report.json'),report);
fprintf('DONE %d SOFTWARE trials. No parameter writes/hardware.\n',height(M));
end

function value=split(seed)
if seed<=60,value="tune_sources1to3";else,value="heldout_sources4to5";end
end
function k=key(hypothesis,seed),k=sprintf('%s_%d',hypothesis,seed);end
function h=input_hash(T)
cols={'time_s','target_rpm','load_ground_truth_a','speed_noise_rpm','iq_noise_a','id_raw_a', ...
 'physical_current_pulse_a','input_valid','input_voltage_sat','input_encoder_age_us','input_running'};
bytes=typecast(reshape(table2array(T(:,cols)),[],1),'uint8');
md=java.security.MessageDigest.getInstance('SHA-256');md.update(bytes);
h=lower(reshape(dec2hex(typecast(md.digest(),'uint8'),2).',1,[]));
end
function save_trial(T,c,hypothesis,seed,gain,cap)
label=sprintf('%s_seed%03d_g%g_cap%g',hypothesis,seed,gain,cap);
file=fullfile(c.results,[label '.csv']);archive=[file '.gz'];
writetable(T,file);gzip(file);assert(isfile(archive));
% Exact just-created CSV has a gzip archive; remove only that temporary
% uncompressed duplicate, never previous logs/user directories.
delete(file);
end
function shutdown_model(name)
if bdIsLoaded(name),set_param(name,'FastRestart','off');close_system(name,0);end
end

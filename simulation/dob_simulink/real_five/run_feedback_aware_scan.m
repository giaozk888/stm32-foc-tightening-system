function report=run_feedback_aware_scan(mode)
% User-authorized SOFTWARE recovery metric. Original strict files untouched.
if nargin==0,mode="full";end
c=prepare_real_five();storage=dob_storage_session(c); %#ok<NASGU>
old=fullfile(c.root,'results');dest=fullfile(c.root,'feedback_aware_results');
M=readtable(fullfile(dest,'off_recomputed_metrics.csv'),'TextType','string');
gate=jsondecode(fileread(fullfile(dest,'gate_recalculation.json')));
assert(height(M)==200&&all(M.feedback_gate_pass),'Recalculate/qualify estimator first');
assert(strcmp(dob_sha256(fullfile(old,'metrics_per_trial.csv')),gate.original_metrics_sha256));
if string(mode)=="smoke",c.seeds=[1,61];dest=fullfile(c.root,'feedback_aware_smoke');end
if ~isfolder(dest),mkdir(dest);end
c.results=dest;files=[dir(fullfile(c.root,'*.m'));dir(fullfile(c.root,'*.py'))];frozen=struct([]);
for k=1:numel(files),frozen(k).path=fullfile(files(k).folder,files(k).name);frozen(k).sha256=dob_sha256(frozen(k).path);end
% Pin the actually reused binaries and all original firmware/host source pins
% from the completed baseline audit, without rebuilding or mutating them.
baseline_report=jsondecode(fileread(fullfile(old,'report.json')));
for pin=baseline_report.native_artifacts',assert(strcmp(dob_sha256(pin.path),pin.sha256));end
M=M(ismember(M.seed,c.seeds),:);
scratch=tempname(dest);mkdir(scratch);scratch_cleanup=onCleanup(@()rmdir(scratch)); %#ok<NASGU>
inputs=containers.Map('KeyType','char','ValueType','any');
M.true_load_speed_mae_rpm=zeros(height(M),1);
M.paired_input_max_abs_delta=zeros(height(M),1);
for k=1:height(M)
 p=fullfile(old,sprintf('%s_seed%03d_g0_cap0.025.csv.gz',M.case_name(k),M.seed(k)));
 f=gunzip(p,scratch);T=readtable(f{1});delete(f{1});
 inputs(key(M.case_name(k),M.seed(k)))=input_values(T);
 ix=T.time_s>=c.event_s&T.time_s<c.unload_s;
 M.true_load_speed_mae_rpm(k)=mean(abs(T.speed_ref_rpm(ix)-T.rpm_true(ix)));
end
writetable(M,fullfile(dest,'off_metrics_used.csv'));
set_param(c.model,'FastRestart','on');restart_cleanup=onCleanup(@()shutdown_model(c.model)); %#ok<NASGU>
rows=struct([]);n=0;started=tic;
for hypothesis=["measurement","torque"]
 assert(any(strcmp({gate.hypotheses.hypothesis},hypothesis)&[gate.hypotheses.passed]));
 for gain=c.gains
  for cap=c.caps_a
   for seed=c.seeds
    [T,amplitude]=real_five_run_case(c,hypothesis,seed,gain,cap);
    input_delta=max(abs(input_values(T)-inputs(key(hypothesis,seed))),[],'all');
    assert(input_delta<=1e-10,'Actual OFF/ON inputs differ beyond CSV serialization tolerance');
    mc=c;mc.load_a=amplitude;
    m=empirical_metrics(T,mc,hypothesis,seed,gain,cap,"fixed_model");
    r=dob_feedback_recovery(T,c.unload_s,.008,.1);
    m.split=split(seed);m.estimator_trial_pass=m.estimate_recovery_s<=.8;
    m.feedback_recovery_s=r.recovery_s;m.feedback_confirmed_s=r.confirmed_s;
    m.recovery_held_ms=r.held_ms;m.recovery_fade_pause_ms=r.fade_pause_ms;m.recovery_expired_events=r.expired_events;
    m.feedback_gate_pass=m.estimate_rmse_a<=.012&&abs(m.estimate_bias_a)<=.008&&m.valid_rate>=.9&& ...
     m.direction_ok&&~m.guard_faults&&m.detection_delay_s<=.5&&r.recovery_s<=.8;
    ix=T.time_s>=c.event_s&T.time_s<c.unload_s;
    m.true_load_speed_mae_rpm=mean(abs(T.speed_ref_rpm(ix)-T.rpm_true(ix)));
    m.paired_input_max_abs_delta=input_delta;
    n=n+1;if n==1,rows=m;else,rows(n)=m;end
    % Every run's full trace retained losslessly in MAT; representative tune
    % seed1 and heldout seed61 also CSV. Avoid thousands of text conversions.
    label=sprintf('%s_seed%03d_g%g_cap%g',hypothesis,seed,gain,cap);
    save(fullfile(dest,[label '.mat']),'T','-v7');
    if ismember(seed,[1,61]),writetable(T,fullfile(dest,[label '.csv']));end
    if mod(n,25)==0
     writetable(struct2table(rows),fullfile(dest,'on_metrics_progress.csv'));
     fprintf('SCAN %d/1800 %s gain%g cap%g elapsed %.0fs\n',n,hypothesis,gain,cap,toc(started));
    end
   end
   fprintf('GROUP COMPLETE %s gain%g cap%g n=%d\n',hypothesis,gain,cap,numel(c.seeds));
  end
 end
end
N=struct2table(rows);assert(isequal(sort(M.Properties.VariableNames),sort(N.Properties.VariableNames)));
N=N(:,M.Properties.VariableNames);ALL=[M;N];
writetable(ALL,fullfile(dest,'metrics_per_trial.csv'));
numeric=ALL.Properties.VariableNames(varfun(@isnumeric,ALL,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
writetable(groupsummary(ALL,{'scenario','split','gain','cap_a'},{'mean','std'},numeric),fullfile(dest,'metrics_mean_std.csv'));
writetable(dob_paired_comparison(ALL),fullfile(dest,'paired_on_minus_off.csv'));
for k=1:numel(frozen),assert(strcmp(dob_sha256(frozen(k).path),frozen(k).sha256));end
for pin=baseline_report.native_artifacts',assert(strcmp(dob_sha256(pin.path),pin.sha256));end
report=struct('on_trials',height(N),'off_trials_reused',height(M),'repeats_per_group',numel(c.seeds), ...
 'sources',frozen,'native_artifacts',baseline_report.native_artifacts,'hardware_access',false, ...
 'physical_performance_validated',false,'physical_runs',5,'configuration',c, ...
 'strict_results_preserved',true,'baseline_metrics_sha256',gate.original_metrics_sha256, ...
 'recovery_criterion','fresh<=2ms; hold<=5ms credit,5..20ms pause,>=20ms reset; missing samples remain invalid', ...
 'all_on_traces_lossless_mat',true,'representative_csv_seeds',[1,61]);
dob_write_json(fullfile(dest,'report.json'),report);
fprintf('DONE ON%d, OFF reused%d. Software only; firmware/native files unchanged.\n',height(N),height(M));
end
function value=split(seed)
if seed<=60,value="tune_sources1to3";else,value="heldout_sources4to5";end
end
function k=key(hypothesis,seed),k=sprintf('%s_%d',hypothesis,seed);end
function values=input_values(T)
cols={'time_s','target_rpm','load_ground_truth_a','speed_noise_rpm','iq_noise_a','id_raw_a', ...
 'physical_current_pulse_a','input_valid','input_voltage_sat','input_encoder_age_us','input_running'};
% Compare actual doubles, not hashes of rounded numbers near decimal bin
% boundaries. Tolerance is1e-10 only for15-digit baseline CSV serialization;
% input values used by Simulink are NEVER rounded/changed for this check.
values=table2array(T(:,cols));
end
function shutdown_model(name)
if bdIsLoaded(name),set_param(name,'FastRestart','off');close_system(name,0);end
end

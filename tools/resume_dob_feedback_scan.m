function report=resume_dob_feedback_scan()
% Resume only MISSING simulations after storage interruption. Existing saved
% traces are validated and reduced, never rerun, replaced or outcome-selected.
repo=fileparts(fileparts(mfilename('fullpath')));
env=fullfile(repo,'simulation','dob_simulink','real_five');addpath(env);
c=prepare_real_five();dest=fullfile(env,'feedback_aware_results');old=fullfile(env,'results');
assert(~isfile(fullfile(dest,'report.json')),'Completed report already exists');
prior=jsondecode(fileread(fullfile(env,'feedback_aware_smoke','report.json')));
for p=[prior.sources(:);prior.native_artifacts(:)]'
 assert(strcmp(dob_sha256(p.path),p.sha256),'Pre-full source/artifact pin changed');
end
% New session-private SDI location; do not reuse or clear the interrupted
% repository. Returned simulation traces/model/controller are unchanged.
sc=c;sc.build=fullfile(dest,'resume_storage');storage=dob_storage_session(sc); %#ok<NASGU>
M=readtable(fullfile(dest,'off_recomputed_metrics.csv'),'TextType','string');
gate=jsondecode(fileread(fullfile(dest,'gate_recalculation.json')));
assert(height(M)==200&&all(M.feedback_gate_pass));
assert(strcmp(dob_sha256(fullfile(old,'metrics_per_trial.csv')),gate.original_metrics_sha256));
checkpoint=fullfile(dest,'on_metrics_progress.csv');
saved_checkpoint=fullfile(dest,'on_metrics_progress_interrupted.csv');
if isfile(checkpoint)&&~isfile(saved_checkpoint),copyfile(checkpoint,saved_checkpoint);end
resume_source.path=mfilename('fullpath')+".m";resume_source.sha256=dob_sha256(resume_source.path);
initial=dir(fullfile(dest,'*.mat'));initial_pins=struct([]);
for k=1:numel(initial)
 initial_pins(k).path=fullfile(initial(k).folder,initial(k).name);
 initial_pins(k).sha256=dob_sha256(initial_pins(k).path);
end
dob_write_json(fullfile(dest,'interrupted_trace_pins.json'),initial_pins);
fprintf('RESUME validated pre-full code pins; %d existing MAT traces will be checked, not rerun\n',numel(initial));
scratch=tempname(dest);mkdir(scratch);clean=onCleanup(@()rmdir(scratch)); %#ok<NASGU>
inputs=containers.Map('KeyType','char','ValueType','any');
M.true_load_speed_mae_rpm=zeros(height(M),1);M.paired_input_max_abs_delta=zeros(height(M),1);
for k=1:height(M)
 paths=gunzip(fullfile(old,sprintf('%s_seed%03d_g0_cap0.025.csv.gz',M.case_name(k),M.seed(k))),scratch);
 T=readtable(paths{1});delete(paths{1});
 inputs(key(M.case_name(k),M.seed(k)))=input_values(T);
 ix=T.time_s>=c.event_s&T.time_s<c.unload_s;
 M.true_load_speed_mae_rpm(k)=mean(abs(T.speed_ref_rpm(ix)-T.rpm_true(ix)));
end
writetable(M,fullfile(dest,'off_metrics_used.csv'));
set_param(c.model,'FastRestart','on');clean_model=onCleanup(@()shutdown(c.model)); %#ok<NASGU>
rows=struct([]);n=0;reused=0;fresh=0;started=tic;
for hypothesis=["measurement","torque"]
 for gain=c.gains
  for cap=c.caps_a
   for seed=c.seeds
    label=sprintf('%s_seed%03d_g%g_cap%g',hypothesis,seed,gain,cap);
    file=fullfile(dest,[label '.mat']);
    if isfile(file)
     S=load(file,'T');T=S.T;reused=reused+1;
     % An unreadable or invalid original is NOT silently rerun.
     amplitude=max(T.load_ground_truth_a);
    else
     [T,amplitude]=real_five_run_case(c,hypothesis,seed,gain,cap);
     save(file,'T','-v7');fresh=fresh+1;
    end
    assert(height(T)==7001&&all(isfinite(table2array(T)),'all'));
    assert(all(abs(T.iq_cmd_a)<=.5+1e-7)&&all(abs(T.iq_dob_a)<=cap+1e-7));
    suspect=bitand(uint32(T.quality_reason),8)~=0&T.lpf_updated==0;
    assert(all(T.abs_id_lpf_a(suspect)==T.id_lpf_before_a(suspect)));
    delta=max(abs(input_values(T)-inputs(key(hypothesis,seed))),[],'all');
    assert(delta<=1e-10,'Actual paired inputs differ');
    mc=c;mc.load_a=amplitude;m=empirical_metrics(T,mc,hypothesis,seed,gain,cap,"fixed_model");
    r=dob_feedback_recovery(T,c.unload_s,.008,.1);
    if seed<=60,m.split="tune_sources1to3";else,m.split="heldout_sources4to5";end
    m.estimator_trial_pass=m.estimate_recovery_s<=.8;
    m.feedback_recovery_s=r.recovery_s;m.feedback_confirmed_s=r.confirmed_s;
    m.recovery_held_ms=r.held_ms;m.recovery_fade_pause_ms=r.fade_pause_ms;m.recovery_expired_events=r.expired_events;
    m.feedback_gate_pass=m.estimate_rmse_a<=.012&&abs(m.estimate_bias_a)<=.008&&m.valid_rate>=.9&& ...
     m.direction_ok&&~m.guard_faults&&m.detection_delay_s<=.5&&r.recovery_s<=.8;
    ix=T.time_s>=c.event_s&T.time_s<c.unload_s;
    m.true_load_speed_mae_rpm=mean(abs(T.speed_ref_rpm(ix)-T.rpm_true(ix)));
    m.paired_input_max_abs_delta=delta;
    n=n+1;if n==1,rows=m;else,rows(n)=m;end
    csvfile=fullfile(dest,[label '.csv']);
    if ismember(seed,[1,61])&&~isfile(csvfile),writetable(T,csvfile);end
    if mod(n,25)==0
     writetable(struct2table(rows),fullfile(dest,'on_metrics_resumed_progress.csv'));
     fprintf('RESUME %d/1800 verified%d new%d elapsed %.0fs\n',n,reused,fresh,toc(started));
    end
   end
  end
 end
end
assert(reused==numel(initial)&&reused+fresh==1800);
N=struct2table(rows);assert(isequal(sort(M.Properties.VariableNames),sort(N.Properties.VariableNames)));
N=N(:,M.Properties.VariableNames);ALL=[M;N];writetable(ALL,fullfile(dest,'metrics_per_trial.csv'));
numeric=ALL.Properties.VariableNames(varfun(@isnumeric,ALL,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
writetable(groupsummary(ALL,{'scenario','split','gain','cap_a'},{'mean','std'},numeric),fullfile(dest,'metrics_mean_std.csv'));
writetable(dob_paired_comparison(ALL),fullfile(dest,'paired_on_minus_off.csv'));
for p=[prior.sources(:);prior.native_artifacts(:);initial_pins(:);resume_source]'
 assert(strcmp(dob_sha256(p.path),p.sha256),'Pinned file changed');
end
report=struct('on_trials',height(N),'off_trials_reused',height(M),'repeats_per_group',100, ...
 'sources',[prior.sources(:);resume_source],'native_artifacts',prior.native_artifacts, ...
 'hardware_access',false,'physical_performance_validated',false,'physical_runs',5,'configuration',c, ...
 'strict_results_preserved',true,'baseline_metrics_sha256',gate.original_metrics_sha256, ...
 'recovery_criterion','fresh<=2ms; hold<=5ms credit,5..20ms pause,>=20ms reset; missing samples remain invalid', ...
 'all_on_traces_lossless_mat',true,'representative_csv_seeds',[1,61], ...
 'storage_interruption',true,'verified_saved_traces_reused',reused,'new_simulations_after_resume',fresh, ...
 'source_pins_basis','Unchanged pre-full smoke snapshot + separately pinned resume harness', ...
 'interrupted_log_sha256',dob_sha256(fullfile(repo,'tmp','dob_feedback_aware_full.log')), ...
 'interrupted_checkpoint_sha256',dob_sha256(saved_checkpoint));
dob_write_json(fullfile(dest,'report.json'),report);
fprintf('DONE ON1800 = %d verified originals + %d new; OFF reused200. No hardware access.\n',reused,fresh);
end
function k=key(h,s),k=sprintf('%s_%d',h,s);end
function values=input_values(T)
columns={'time_s','target_rpm','load_ground_truth_a','speed_noise_rpm','iq_noise_a','id_raw_a', ...
 'physical_current_pulse_a','input_valid','input_voltage_sat','input_encoder_age_us','input_running'};
values=table2array(T(:,columns));
end
function shutdown(name)
if bdIsLoaded(name),set_param(name,'FastRestart','off');close_system(name,0);end
end

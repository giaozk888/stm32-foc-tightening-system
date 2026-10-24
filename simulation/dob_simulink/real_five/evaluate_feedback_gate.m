function evaluate_feedback_gate()
root=fileparts(mfilename('fullpath'));addpath(fileparts(root));test_feedback_recovery();
old=fullfile(root,'results');dest=fullfile(root,'feedback_aware_results');
if ~isfolder(dest),mkdir(dest);end
M=readtable(fullfile(old,'metrics_per_trial.csv'),'TextType','string');
assert(height(M)==200&&all(M.gain==0),'Keep the original200 OFF trials intact');
scratch=tempname(dest);mkdir(scratch);clean=onCleanup(@()remove_scratch(scratch)); %#ok<NASGU>
for k=1:height(M)
 name=sprintf('%s_seed%03d_g0_cap0.025.csv.gz',M.case_name(k),M.seed(k));
 files=gunzip(fullfile(old,name),scratch);T=readtable(files{1});
 r=dob_feedback_recovery(T,4.6,.008,.1);delete(files{1});
 M.feedback_recovery_s(k)=r.recovery_s;M.feedback_confirmed_s(k)=r.confirmed_s;
 M.recovery_held_ms(k)=r.held_ms;M.recovery_fade_pause_ms(k)=r.fade_pause_ms;
 M.recovery_expired_events(k)=r.expired_events;
 M.feedback_gate_pass(k)=M.estimate_rmse_a(k)<=.012&&abs(M.estimate_bias_a(k))<=.008&& ...
  M.valid_rate(k)>=.9&&M.direction_ok(k)&&M.guard_faults(k)==0&&M.detection_delay_s(k)<=.5&&r.recovery_s<=.8;
end
writetable(M,fullfile(dest,'off_recomputed_metrics.csv'));
gates=struct([]);
for name=["measurement","torque"]
 rows=M(M.case_name==name,:);
 gates(end+1).hypothesis=char(name);gates(end).trials=height(rows);gates(end).passed=all(rows.feedback_gate_pass); %#ok<AGROW>
 fprintf('%s: feedback-aware pass%d/%d, recovery %.3f..%.3fs; strict retained\n', ...
  name,sum(rows.feedback_gate_pass),height(rows),min(rows.feedback_recovery_s),max(rows.feedback_recovery_s));
end
dob_write_json(fullfile(dest,'gate_recalculation.json'),struct('original_results_unchanged',true, ...
 'original_metrics_sha256',dob_sha256(fullfile(old,'metrics_per_trial.csv')), ...
 'metric','100ms qualified time; hold<=5ms, fade pauses<20ms, expiry resets>=20ms; fresh inaccurate resets', ...
 'hardware_access',false,'hypotheses',gates));
end
function remove_scratch(folder)
% Only this exact temp directory was created by this invocation.
if isfolder(folder),rmdir(folder);end
end

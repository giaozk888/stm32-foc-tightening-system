function report=finalize_dob_results()
% Semantic reduction of raw metrics, separate from simulation dynamics.
% A no-load record has no unload event. Its 0-second already-in-band dwell
% must be reported as NOT APPLICABLE, not as an infinitely fast recovery.
c=dob_config();folder=c.results;
report=jsondecode(fileread(fullfile(folder,'report.json')));
M=readtable(fullfile(folder,'metrics_per_trial.csv'),'TextType','string');
if ~isfield(report,'nonevent_metrics_are_not_applicable')||~report.nonevent_metrics_are_not_applicable
 copyfile(fullfile(folder,'metrics_per_trial.csv'),fullfile(folder,'metrics_per_trial_raw.csv'),'f');
end
M.estimate_recovery_s(M.scenario=="no_load")=NaN;
writetable(M,fullfile(folder,'metrics_per_trial.csv'));
numeric=M.Properties.VariableNames(varfun(@isnumeric,M,'OutputFormat','uniform'));
numeric=setdiff(numeric,{'seed','gain','cap_a'},'stable');
S=groupsummary(M,{'scenario','gain','cap_a'},{'mean','std'},numeric);
P=dob_paired_comparison(M);
writetable(S,fullfile(folder,'metrics_mean_std.csv'));
writetable(P,fullfile(folder,'paired_on_minus_off.csv'));
report.nonevent_metrics_are_not_applicable=true;
report.semantic_reducer_sha256=dob_sha256(mfilename('fullpath')+".m");
dob_write_json(fullfile(folder,'report.json'),report);
dob_write_report(c,M,S,P,report);
dob_write_json(fullfile(folder,'analysis_provenance.json'),struct( ...
 'simulation_source_manifest_sha256',dob_sha256(fullfile(c.build,'source_manifest.json')), ...
 'semantic_reducer_sha256',report.semantic_reducer_sha256, ...
 'raw_metrics_file','metrics_per_trial_raw.csv', ...
 'raw_metrics_sha256',dob_sha256(fullfile(folder,'metrics_per_trial_raw.csv')), ...
 'change','No-load has no unload event: already-in-band waiting time -> NaN/not applicable', ...
 'controller_or_trajectory_changed',false,'physical_performance_validated',false));
end

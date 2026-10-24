function c=prepare_empirical_model()
c=empirical_config();addpath(c.base.root,c.base.build,c.root);
assert(isfile(c.event_library),'Run empirical/export_events.py first');
if ~isfolder(c.model_dir),mkdir(c.model_dir);end
if ~isfolder(c.results),mkdir(c.results);end
if bdIsLoaded(c.model),close_system(c.model,0);end
load_system(fullfile(c.base.build,[c.base.model '.slx']));
save_system(c.base.model,fullfile(c.model_dir,[c.model '.slx']));
if ~bdIsLoaded(c.model),load_system(fullfile(c.model_dir,[c.model '.slx']));end
% Iq_total = modeled regulator current + exogenous torque-current pulse.
% Applying -pulse at plant load port is algebraically equivalent in the
% normalized mechanical equation. Load truth stays separate/unchanged.
add_block('simulink/Sources/From Workspace',[c.model '/Current_Pulse_Hypothesis'], ...
 'VariableName','physical_current','Interpolate','off','OutputAfterFinalValue','Holding final value', ...
 'SampleTime','.00005','Position',[780 450 960 490]);
add_block('simulink/Math Operations/Sum',[c.model '/Load_Minus_CurrentPulse'], ...
 'Inputs','+-','Position',[980 350 1010 390]);
add_block('simulink/Math Operations/Sum',[c.model '/Actual_Total_Iq'], ...
 'Inputs','++','Position',[1250 350 1280 390]);
delete_line(c.model,'Independent_Load_GroundTruth_A/1','Plant_Inputs/2');
add_line(c.model,'Independent_Load_GroundTruth_A/1','Load_Minus_CurrentPulse/1','autorouting','on');
add_line(c.model,'Current_Pulse_Hypothesis/1','Load_Minus_CurrentPulse/2','autorouting','on');
add_line(c.model,'Load_Minus_CurrentPulse/1','Plant_Inputs/2','autorouting','on');
delete_line(c.model,'Physical_States/2','Controller_Inputs/3');
add_line(c.model,'Physical_States/2','Actual_Total_Iq/1','autorouting','on');
add_line(c.model,'Current_Pulse_Hypothesis/1','Actual_Total_Iq/2','autorouting','on');
add_line(c.model,'Actual_Total_Iq/1','Controller_Inputs/3','autorouting','on');
add_block('simulink/Sinks/To Workspace',[c.model '/Actual_Current_Pulse_Log'], ...
 'VariableName','pulse_log','SaveFormat','Timeseries','SampleTime','.001', ...
 'MaxDataPoints','inf','Position',[1050 460 1210 495]);
add_line(c.model,'Current_Pulse_Hypothesis/1','Actual_Current_Pulse_Log/1','autorouting','on');
[stimulus,load_truth,physical_current]=empirical_scenario(c,'nominal',101);
ws=get_param(c.model,'ModelWorkspace');
assignin(ws,'stimulus',stimulus);assignin(ws,'load_truth',load_truth);
assignin(ws,'physical_current',physical_current);
save_system(c.model,fullfile(c.model_dir,[c.model '.slx']));
end

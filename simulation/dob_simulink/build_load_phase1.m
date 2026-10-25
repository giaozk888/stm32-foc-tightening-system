function [c,p]=build_load_phase1()
% Extends the existing model with a SINK-ONLY branch. Original 33-vector ABI
% and firmware sources are untouched. No selector or actuator consumes it.
c=build_dob_simulink();p=phase1_config();
c.model=p.model;c.model_dir=fullfile(c.build,'load_phase1');
if ~isfolder(c.model_dir),mkdir(c.model_dir);end
native=fullfile(c.root,'native');
mex('-silent',['-I',native],'-outdir',c.model_dir, ...
    fullfile(native,'load_features_sfun.c'),fullfile(native,'load_features.c'));
addpath(c.model_dir);
if bdIsLoaded(c.model),close_system(c.model,0);end
save_system('dob_offline',fullfile(c.model_dir,[c.model '.slx']));
if ~bdIsLoaded(c.model),load_system(fullfile(c.model_dir,[c.model '.slx']));end
ws=get_param(c.model,'ModelWorkspace');
assignin(ws,'features_enabled',1);assignin(ws,'features_config',p.features);
add_block('simulink/User-Defined Functions/S-Function',[c.model '/ReadOnly_Load_Features'], ...
    'FunctionName','load_features_sfun','Parameters','features_enabled, features_config', ...
    'Position',[900 540 1130 610]);
add_block('simulink/Sinks/To Workspace',[c.model '/Load_Features_Log'], ...
    'VariableName','features_log','SaveFormat','Timeseries','SampleTime','.001', ...
    'MaxDataPoints','inf','Position',[1230 555 1400 590]);
% Resolve the compiled S-function's two ports before connecting port 2.
set_param(c.model,'SimulationCommand','update');
add_line(c.model,'Original_C_SpeedPI_Scurve_DOB_Quality/1','ReadOnly_Load_Features/1','autorouting','on');
add_line(c.model,'Controller_Inputs/1','ReadOnly_Load_Features/2','autorouting','on');
add_line(c.model,'ReadOnly_Load_Features/1','Load_Features_Log/1');
% Same independently generated current-pulse hypothesis as empirical model.
% It is zero in synthetic/measurement cases. Not a DOB-derived true load.
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
assignin(ws,'features_enabled',1);assignin(ws,'features_config',p.features);
[stimulus,load_truth]=dob_scenario(c,'step',1);
assignin(ws,'physical_current',[stimulus(:,1),zeros(size(stimulus,1),1)]);
assignin(ws,'stimulus',stimulus);assignin(ws,'load_truth',load_truth);
save_system(c.model,fullfile(c.model_dir,[c.model '.slx']));
% Read-only graph contract: classifier's only output terminates in logging.
ports=get_param([c.model '/ReadOnly_Load_Features'],'PortHandles');
line=get_param(ports.Outport,'Line');dest=get_param(line,'DstPortHandle');
assert(numel(dest)==1&&strcmp(get_param(get_param(dest,'Parent'),'Name'),'Load_Features_Log'));
fprintf('PASS: phase1 model + read-only classifier MEX built\n');
end

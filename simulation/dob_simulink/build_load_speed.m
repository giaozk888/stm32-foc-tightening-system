function c=build_load_speed()
% Entirely new SOFTWARE model; no MCU source/build/flash changes.
c.root=fileparts(mfilename('fullpath'));c.repo=fileparts(fileparts(c.root));
c.build=fullfile(c.root,'load_speed_work');c.model='dob_rundown_load_speed';
c.m=jsondecode(fileread(fullfile(c.build,'manifest.json')));
native=fullfile(c.root,'native');addpath(c.root,c.build);
source=fileread(fullfile(native,'dob_controller_sfun.c'));
source=strrep(source,'ssSetInputPortWidth(S,0,10)','ssSetInputPortWidth(S,0,16)');
source=strrep(source,'ssSetOutputPortWidth(S,0,33)','ssSetOutputPortWidth(S,0,64)');
path=fullfile(c.build,'load_speed_controller_sfun.c');fid=fopen(path,'w');fwrite(fid,source);fclose(fid);
mex('-silent','-DDOB_CONTROLLER_SFUN_NAME=load_speed_controller_sfun', ...
    ['-I',native],'-output','load_speed_controller_sfun','-outdir',c.build,path);
mex('-silent','-outdir',c.build,fullfile(native,'load_speed_plant_sfun.c'));
if bdIsLoaded(c.model),close_system(c.model,0);end
new_system(c.model);set_param(c.model,'Solver','FixedStepDiscrete','FixedStep','.00005', ...
    'StopTime','10','ReturnWorkspaceOutputs','on','SignalLogging','off');
add_block('simulink/Sources/From Workspace',[c.model '/Independent_Scenario'], ...
    'VariableName','stimulus','Interpolate','off','SampleTime','.001','OutputAfterFinalValue','Holding final value');
add_block('simulink/Signal Routing/Demux',[c.model '/Exogenous'],'Outputs','15');
add_block('simulink/Signal Routing/Mux',[c.model '/ControllerInputs'],'Inputs','16');
add_block('simulink/User-Defined Functions/S-Function',[c.model '/OriginalC_FSM_Scheduler_Scurve_PI_DOB'], ...
    'FunctionName','load_speed_controller_sfun','Parameters','host_dll, run_config');
add_block('simulink/Signal Routing/Selector',[c.model '/IqLimited'],'NumberOfDimensions','1', ...
    'Indices','8','InputPortWidth','64');
add_block('simulink/Discrete/Zero-Order Hold',[c.model '/PWM_ZOH'],'SampleTime','.00005');
add_block('simulink/Discrete/Unit Delay',[c.model '/One_PWM_Cycle'],'SampleTime','.00005','InitialCondition','0');
add_block('simulink/Signal Routing/Mux',[c.model '/PlantInputs'],'Inputs','5');
add_block('simulink/User-Defined Functions/S-Function',[c.model '/Independent_MechanicalPlant_Fixture'], ...
    'FunctionName','load_speed_plant_sfun','Parameters','plant_parameters');
add_block('simulink/Signal Routing/Demux',[c.model '/PhysicalStates'],'Outputs','6');
for name={'control','inputs','truth','scenario'}
    add_block('simulink/Sinks/To Workspace',[c.model '/',name{1},'_log'], ...
        'VariableName',[name{1},'_log'],'SaveFormat','Timeseries','SampleTime','.001','MaxDataPoints','inf');
end
add_line(c.model,'Independent_Scenario/1','Exogenous/1');
add_line(c.model,'Independent_Scenario/1','scenario_log/1');
% Scenario: target, speedNoise,iqNoise,Id,valid,sat,age,run,enable,dir,stop,fault,load,angle,fixture.
map=[1 0 0 2 3 4 5 6 7 8 9 0 10 15 11 12];
for port=1:16
    if map(port)>0,add_line(c.model,sprintf('Exogenous/%d',map(port)),sprintf('ControllerInputs/%d',port));end
end
add_line(c.model,'PhysicalStates/1','ControllerInputs/2');
add_line(c.model,'PhysicalStates/2','ControllerInputs/3');
add_line(c.model,'PhysicalStates/3','ControllerInputs/12');
add_line(c.model,'ControllerInputs/1','OriginalC_FSM_Scheduler_Scurve_PI_DOB/1');
add_line(c.model,'ControllerInputs/1','inputs_log/1');
add_line(c.model,'OriginalC_FSM_Scheduler_Scurve_PI_DOB/1','control_log/1');
add_line(c.model,'OriginalC_FSM_Scheduler_Scurve_PI_DOB/1','IqLimited/1');
add_line(c.model,'IqLimited/1','PWM_ZOH/1');add_line(c.model,'PWM_ZOH/1','One_PWM_Cycle/1');
add_line(c.model,'One_PWM_Cycle/1','PlantInputs/1');
add_line(c.model,'Exogenous/13','PlantInputs/2');add_line(c.model,'Exogenous/14','PlantInputs/3');
add_line(c.model,'Exogenous/15','PlantInputs/4');add_line(c.model,'Exogenous/10','PlantInputs/5');
add_line(c.model,'PlantInputs/1','Independent_MechanicalPlant_Fixture/1');
add_line(c.model,'Independent_MechanicalPlant_Fixture/1','PhysicalStates/1');
add_line(c.model,'Independent_MechanicalPlant_Fixture/1','truth_log/1');
ws=get_param(c.model,'ModelWorkspace');[stimulus,plant]=load_speed_inputs(c,'no_load',1,0);
stimulus(:,1)=stimulus(:,1)-1e-9; % Avoid binary floating-point boundary choosing the previous row.
assignin(ws,'stimulus',stimulus);assignin(ws,'host_dll',c.m.dll);assignin(ws,'run_config',[1,.25,.025]);
assignin(ws,'plant_parameters',plant);set_param(c.model,'SimulationCommand','update');
Simulink.BlockDiagram.arrangeSystem(c.model);save_system(c.model,fullfile(c.build,[c.model '.slx']));
fprintf('BUILT Simulink load-speed scheduling, original C FSM, independent truth and50us delayed current command\n');
end

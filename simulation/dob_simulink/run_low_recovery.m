function report=run_low_recovery()
% Observer-only paired Simulink test. Truth cannot enter either estimator.
root=fileparts(mfilename('fullpath'));work=fullfile(root,'low_recovery_work');
m=jsondecode(fileread(fullfile(work,'manifest.json')));addpath(work);
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));dest=fullfile(root,'low_recovery_results',stamp);mkdir(dest);
copyfile(fullfile(work,'manifest.json'),fullfile(dest,'manifest.json'));
model='dob_low_recovery_ab';if bdIsLoaded(model),close_system(model,0);end
new_system(model);set_param(model,'Solver','FixedStepDiscrete','FixedStep','.001','StopTime','7', ...
    'ReturnWorkspaceOutputs','on','SignalLogging','off');
cleanup=onCleanup(@()finish(model)); %#ok<NASGU>
ws=get_param(model,'ModelWorkspace');assignin(ws,'fb_config',[1 .25 .025]);
fid=fopen(m.runs(1).input,'rb');data=fread(fid,[16 inf],'double=>double')';fclose(fid);
assignin(ws,'epochs',[(data(:,1)-100020)*1e-6,data]);
add_block('simulink/Sources/From Workspace',[model '/Independent_Epochs_And_Truth'], ...
    'VariableName','epochs','Interpolate','off','OutputAfterFinalValue','Holding final value','SampleTime','.001');
add_block('simulink/Signal Routing/Selector',[model '/Measurements_Only'], ...
    'NumberOfDimensions','1','Indices','1:14','InputPortWidth','16');
add_block('simulink/Sinks/To Workspace',[model '/Consumed_Input'], ...
    'VariableName','consumed','SaveFormat','Timeseries','SampleTime','.001','MaxDataPoints','inf');
add_line(model,'Independent_Epochs_And_Truth/1','Measurements_Only/1');
add_line(model,'Independent_Epochs_And_Truth/1','Consumed_Input/1');
profiles=reshape(string(m.profiles),1,[]);
for profile=profiles
    name=char("low_"+profile+"_sfun");
    mex('-silent',"-DLOW_RECOVERY_SFUN_NAME="+name,'-output',name,'-outdir',work, ...
        fullfile(root,'native','low_recovery_sfun.c'));
    assignin(ws,char(profile+"_dll"),m.dlls.(profile).path);
    add_block('simulink/User-Defined Functions/S-Function',char(model+"/"+profile), ...
        'FunctionName',name,'Parameters',char(profile+"_dll, fb_config"));
    add_block('simulink/Sinks/To Workspace',char(model+"/"+profile+"_Log"), ...
        'VariableName',char(profile+"_log"),'SaveFormat','Timeseries','SampleTime','.001','MaxDataPoints','inf');
end
set_param(model,'SimulationCommand','update');
for profile=profiles
    add_line(model,'Measurements_Only/1',char(profile+"/1"));
    add_line(model,char(profile+"/1"),char(profile+"_Log/1"));
end
Simulink.BlockDiagram.arrangeSystem(model);save_system(model,fullfile(dest,[model '.slx']));
for k=1:numel(m.runs)
    r=m.runs(k);fid=fopen(r.input,'rb');data=fread(fid,[16 inf],'double=>double')';fclose(fid);
    times=(data(:,1)-100020)*1e-6;
    si=Simulink.SimulationInput(model);si=si.setVariable('epochs',[times,data],'Workspace',model);
    out=sim(si);U=out.get('consumed');assert(isequal(squeeze(U.Data),data));
    T=[table(times,'VariableNames',{'time_s'}),array2table(data,'VariableNames',cellstr(string(m.input_names)))];
    for profile=profiles
        Y=out.get(char(profile+"_log"));A=squeeze(Y.Data);
        assert(size(A,1)==r.rows&&all(isfinite(A),'all')&&max(abs(Y.Time-times))<1e-9);
        T=[T,array2table(A,'VariableNames',cellstr(profile+"_"+string(m.output_names)))]; %#ok<AGROW>
    end
    file=fullfile(dest,sprintf('%s_seed%03d.csv',r.scenario,r.seed));writetable(T,file);gzip(file);delete(file);
    dob_write_json(fullfile(dest,'progress.json'),struct('completed',k,'total',numel(m.runs)));
    fprintf('LOW RECOVERY %d/%d %s seed%d\n',k,numel(m.runs),r.scenario,r.seed);
end
for k=1:numel(m.sources),assert(strcmp(dob_sha256(m.sources(k).path),m.sources(k).sha256));end
report=struct('completed',true,'runs',numel(m.runs),'paired_estimator_evaluations',numel(profiles)*numel(m.runs), ...
    'repeats',10,'consumed_input_verified',true,'hardware_access',false,'feedback_applied_to_plant',false, ...
    'physical_performance_validated',false,'results',dest);
dob_write_json(fullfile(dest,'report.json'),report);
fid=fopen(fullfile(work,'latest_results.txt'),'w');fprintf(fid,'%s',dest);fclose(fid);
fprintf('COMPLETE %s\n',dest);
end
function finish(model)
if bdIsLoaded(model),close_system(model,0);end
end

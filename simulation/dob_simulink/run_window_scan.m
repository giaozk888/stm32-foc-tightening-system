function report=run_window_scan()
% Pure classification replay; actual MCU float C, four separate DWork states.
root=fileparts(mfilename('fullpath'));work=fullfile(root,'window_scan_work');
m=jsondecode(fileread(fullfile(work,'manifest.json')));gen=fullfile(work,'generated');
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
dest=fullfile(root,'window_scan_results',stamp);mkdir(dest);
copyfile(fullfile(work,'manifest.json'),fullfile(dest,'manifest.json'));
addpath(work);model='dob_window_replay';
if bdIsLoaded(model),close_system(model,0);end
new_system(model);set_param(model,'Solver','FixedStepDiscrete','FixedStep','.001','StopTime','7', ...
    'SignalLogging','off','ReturnWorkspaceOutputs','on');
cleanup=onCleanup(@()finish(model)); %#ok<NASGU>
ws=get_param(model,'ModelWorkspace');
fid=fopen(m.runs(1).input,'rb');data=fread(fid,[8 inf],'double=>double')';fclose(fid);
assignin(ws,'replay',[data(:,1),data]);
add_block('simulink/Sources/From Workspace',[model '/Frozen_Replay'], ...
    'VariableName','replay','Interpolate','off','OutputAfterFinalValue','Holding final value', ...
    'SampleTime','.001','Position',[50 150 240 200]);
add_block('simulink/Sinks/To Workspace',[model '/Consumed_Input_Log'], ...
    'VariableName','consumed_input','SaveFormat','Timeseries','SampleTime','.001', ...
    'MaxDataPoints','inf','Position',[370 70 590 110]);
add_line(model,'Frozen_Replay/1','Consumed_Input_Log/1');
names=["level","level_valid","mean_a","slope_a_s","coverage","updated","reason", ...
    "accepted","rejected","resets","level_changes","trend","trend_valid", ...
    "filtered_slope_a_s","trend_changes","level_dwell_ms","trend_dwell_ms","proposal"];
for j=1:4
    w=m.windows_ms(j);name=sprintf('dob_window_%d_sfun',w);
    mex('-silent',['-I',gen],sprintf('-DDOB_WINDOW_POINTS=%dU',w), ...
        sprintf('-DDOB_WINDOW_MIN_GOOD=%dU',m.min_good(j)), ...
        sprintf('-DDOB_WINDOW_MIN_SPAN_US=%dU',m.min_span_ms(j)*1000), ...
        ['-DDOB_WINDOW_SFUN_NAME=',name],'-output',name,'-outdir',work, ...
        fullfile(root,'native','dob_window_sfun.c'),fullfile(gen,'dob_trend_shadow.c'));
    add_block('simulink/User-Defined Functions/S-Function',sprintf('%s/Window_%d',model,w), ...
        'FunctionName',name,'Position',[370 50+100*j 590 110+100*j]);
    add_block('simulink/Sinks/To Workspace',sprintf('%s/Log_%d',model,w), ...
        'VariableName',sprintf('window_%d',w),'SaveFormat','Timeseries','SampleTime','.001', ...
        'MaxDataPoints','inf','Position',[720 65+100*j 940 100+100*j]);
end
set_param(model,'SimulationCommand','update');
for w=reshape(m.windows_ms,1,[])
    add_line(model,'Frozen_Replay/1',sprintf('Window_%d/1',w),'autorouting','on');
    add_line(model,sprintf('Window_%d/1',w),sprintf('Log_%d/1',w));
end
save_system(model,fullfile(dest,[model '.slx']));set_param(model,'FastRestart','on');
completed=struct([]);
for k=1:numel(m.runs)
    r=m.runs(k);fid=fopen(r.input,'rb');data=fread(fid,[8 inf],'double=>double')';fclose(fid);
    assert(size(data,1)==r.rows&&all(isfinite(data),'all'));
    si=Simulink.SimulationInput(model);si=si.setVariable('replay',[data(:,1),data],'Workspace',model);
    out=sim(si);consumed=out.get('consumed_input');actual=squeeze(consumed.Data);
    assert(isequal(actual,data)&&max(abs(consumed.Time-data(:,1)))<1e-9, ...
        'FastRestart must consume the exact current trial, not a cached prior source');
    T=array2table(actual,'VariableNames',cellstr(string(m.input_columns)));
    for w=reshape(m.windows_ms,1,[])
        Y=out.get(sprintf('window_%d',w));A=squeeze(Y.Data);
        assert(size(A,1)==r.rows&&all(isfinite(A),'all')&&max(abs(Y.Time-data(:,1)))<1e-9);
        assert(all(ismember(A(:,1),[0 1 2 4]))&&all(ismember(A(:,12),0:3)));
        T=[T,array2table(A,'VariableNames',cellstr("w"+w+"_"+names))]; %#ok<AGROW>
    end
    file=fullfile(dest,sprintf('%s_seed%03d.csv',r.scenario,r.seed));writetable(T,file);
    gzip(file);delete(file); % Exact newly created per-run CSV only; preserve compressed results.
    completed(k).scenario=r.scenario;completed(k).seed=r.seed;completed(k).rows=r.rows; %#ok<AGROW>
    dob_write_json(fullfile(dest,'progress.json'),struct('completed',k,'total',numel(m.runs)));
    fprintf('WINDOW %d/%d %s seed%d four branches\n',k,numel(m.runs),r.scenario,r.seed);
end
assert(strcmp(dob_sha256(m.original_c),m.original_c_sha256));
assert(strcmp(dob_sha256(m.original_h),m.original_h_sha256));
report=struct('completed',true,'model_runs',numel(completed),'classification_evaluations',4*numel(completed), ...
    'repeats',10,'hardware_access',false,'production_parameters_changed',false, ...
    'physical_performance_validated',false,'consumed_input_verified',true,'runs',completed,'results',dest);
dob_write_json(fullfile(dest,'report.json'),report);
fid=fopen(fullfile(work,'latest_results.txt'),'w');fprintf(fid,'%s',dest);fclose(fid);
fprintf('COMPLETE %s\n',dest);
end
function finish(model)
if bdIsLoaded(model),set_param(model,'FastRestart','off');close_system(model,0);end
end

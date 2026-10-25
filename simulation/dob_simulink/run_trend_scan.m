function report=run_trend_scan(mode)
% Four independent DWork branches on ONE unchanged Simulink trajectory.
% 130 model runs ->520 paired classification evaluations, not520 motor runs.
if nargin<1,mode='full';end
[c,p]=build_load_repair();q=trend_scan_config();addpath(fullfile(c.root,'real_five'));
if strcmp(mode,'smoke'),p.scenarios=["unload","short_gap","real_measurement","real_torque"];q.seeds=1;end
model='dob_trend_scan';save_system(p.fixed_model,fullfile(c.model_dir,[model '.slx']));
if ~bdIsLoaded(model),load_system(fullfile(c.model_dir,[model '.slx']));end
ws=get_param(model,'ModelWorkspace');
assert(p.features(9)==.100&&p.features(10)==.080);
configs=repmat(p.features,4,1);
for j=1:4
    configs(j,9)=q.tau_ms(j)*.001;configs(j,10)=q.dwell_ms(j)*.001;
    assert(all(configs(j,[1:8,11])==p.features([1:8,11])));
end
for j=2:4
    assignin(ws,sprintf('trend_config_%d',j),configs(j,:));
    block=sprintf('Trend_Profile_%d',j);sink=sprintf('Trend_Profile_Log_%d',j);
    add_block('simulink/User-Defined Functions/S-Function',[model '/' block], ...
        'FunctionName','load_features_sfun', ...
        'Parameters',sprintf('features_enabled, trend_config_%d',j), ...
        'Position',[900 790+100*j 1130 850+100*j]);
    add_block('simulink/Sinks/To Workspace',[model '/' sink], ...
        'VariableName',sprintf('trend_log_%d',j),'SaveFormat','Timeseries','SampleTime','.001', ...
        'MaxDataPoints','inf','Position',[1230 800+100*j 1400 840+100*j]);
end
set_param(model,'SimulationCommand','update');
for j=2:4
    block=sprintf('Trend_Profile_%d',j);sink=sprintf('Trend_Profile_Log_%d',j);
    add_line(model,'Original_C_SpeedPI_Scurve_DOB_Quality/1',[block '/1'],'autorouting','on');
    add_line(model,'Controller_Inputs/1',[block '/2'],'autorouting','on');
    add_line(model,[block '/1'],[sink '/1']);
end
save_system(model,fullfile(c.model_dir,[model '.slx']));
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
c.results=fullfile(c.root,'trend_scan_results',stamp);mkdir(c.results);
storage_c=c;storage_c.build=fullfile(c.model_dir,'trend_storage',stamp);
storage=dob_storage_session(storage_c); %#ok<NASGU>
set_param(model,'SignalLogging','off','FastRestart','on');
shutdown=onCleanup(@()finish(model)); %#ok<NASGU>
config=struct('mode',mode,'scan',q,'base',c,'classification',p,'profiles',configs, ...
    'repeats',numel(q.seeds),'hardware_access',false,'control_adaptation',false, ...
    'physical_performance_validated',false,'compensation_enabled',false);
dob_write_json(fullfile(c.results,'config.json'),config);
manifest=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
copyfile(fullfile(c.build,'source_manifest.json'),fullfile(c.results,'source_manifest.json'));
index=0;checks=struct([]);
for name=p.scenarios
    for seed=q.seeds
        [stimulus,truth,physical,mapping]=phase1_inputs(c,name,seed);
        si=Simulink.SimulationInput(model);
        values={stimulus,truth,physical,[0,0,.025],c.plant_vector,1};
        vars={'stimulus','load_truth','physical_current','run_config','plant_parameters','features_enabled'};
        for k=1:numel(vars),si=si.setVariable(vars{k},values{k},'Workspace',model);end
        out=sim(si);Y=out.get('control_log');F=out.get('features_log');
        U=out.get('input_log');L=out.get('load_log');P=out.get('truth_log');
        assert(numel(Y.Time)==size(stimulus,1)&&numel(F.Time)==numel(Y.Time));
        assert(max(abs(Y.Time-F.Time))<1e-10);
        T=array2table(squeeze(Y.Data),'VariableNames',cellstr(dob_schema()));
        T=[table(Y.Time,'VariableNames',{'time_s'}),T, ...
            array2table(squeeze(F.Data),'VariableNames',cellstr(p.feature_names))];
        for j=2:4
            Z=out.get(sprintf('trend_log_%d',j));
            assert(numel(Z.Time)==numel(Y.Time)&&max(abs(Z.Time-Y.Time))<1e-10);
            B=squeeze(Z.Data);A=squeeze(F.Data);
            assert(max(abs(A(:,1:16)-B(:,1:16)),[],'all')==0, ...
                'Trend setting changed level/quality statistics');
            T=[T,array2table(B,'VariableNames',cellstr(q.ids(j)+"_"+p.feature_names))]; %#ok<AGROW>
        end
        T.target_rpm=U.Data(:,1);T.rpm_true=U.Data(:,2)*60/(2*pi);T.iq_true_a=U.Data(:,3);
        T.load_ground_truth_a=L.Data;T.speed_noise_rpm=U.Data(:,4);T.iq_noise_a=U.Data(:,5);
        T.input_valid=U.Data(:,7);T.input_voltage_sat=U.Data(:,8);T.physical_current_pulse_a=physical(:,2);
        if isempty(mapping),T.source_window=zeros(height(T),1);else,T.source_window=mapping(:,1);end
        assert(all(isfinite(T{:,:}),'all')&&max(T.simulation_guard_fault)==0);
        assert(max(abs(T.iq_cmd_a))<=.500001&&all(T.iq_dob_a==0));
        assert(max(abs(U.Data(:,2)-P.Data(:,1)))<1e-12);
        file=fullfile(c.results,sprintf('%s_seed%03d.csv',name,seed));
        writetable(T,file);gz=gzip(file);assert(isfile(gz{1}));delete(file);
        index=index+1;check=struct('scenario',name,'seed',seed,'rows',height(T),'profile_count',4);
        if isempty(checks),checks=check;else,checks(index)=check;end %#ok<AGROW>
        dob_write_json(fullfile(c.results,'progress.json'),struct('completed_runs',index,'runs',checks));
        fprintf('TREND RUN %d/%d %s seed%d four_profiles_level_identical=1\n', ...
            index,numel(p.scenarios)*numel(q.seeds),name,seed);
    end
    draw_profiles(c,q,T,name,seed);
end
for k=1:numel(manifest.sources)
    assert(strcmp(dob_sha256(manifest.sources(k).path),manifest.sources(k).sha256));
end
report=struct('completed',true,'model_runs',index,'classification_evaluations',4*index, ...
    'repeats',numel(q.seeds),'control_adaptation',false,'hardware_access',false, ...
    'physical_performance_validated',false,'frozen_sources_unchanged',true,'runs',checks,'results',c.results);
dob_write_json(fullfile(c.results,'report.json'),report);
fid=fopen(fullfile(c.build,'trend_scan_latest_results.txt'),'w');fprintf(fid,'%s',c.results);fclose(fid);
fprintf('COMPLETE TREND %d model runs / %d classification evaluations -> %s\n',index,4*index,c.results);
end
function finish(model)
if bdIsLoaded(model),set_param(model,'FastRestart','off');end
end
function draw_profiles(c,q,T,name,seed)
f=figure('Visible','off','Position',[100 100 1150 1050]);tiledlayout(5,1);
nexttile;d=T.dob_estimate_a;d(T.dob_valid==0)=NaN;
plot(T.time_s,T.load_ground_truth_a,T.time_s,d,T.time_s,T.load_mean_a);
legend('Independent load','Valid DOB','Mean load');ylabel('A equiv');
title(sprintf('%s seed%d',strrep(name,'_',' '),seed));
for j=1:4
    if j==1,s=T.load_trend_state;v=T.load_trend_valid;
    else,s=T.(q.ids(j)+"_load_trend_state");v=T.(q.ids(j)+"_load_trend_valid");end
    nexttile;stairs(T.time_s,s);hold on;
    bad=v==0;plot(T.time_s(bad),s(bad),'.','Color',[.7 .7 .7],'MarkerSize',2);
    yticks(0:3);yticklabels({'UNKNOWN','STEADY','RISING','FALLING'});ylim([-.1 3.2]);
    ylabel(sprintf('%d/%d ms',q.tau_ms(j),q.dwell_ms(j)));
end
xlabel('Time (s)');exportgraphics(f,fullfile(c.results,char(name+".png")));close(f);
end

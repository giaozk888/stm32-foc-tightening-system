function report=run_load_repair(mode)
if nargin<1,mode='full';end
[c,p]=build_load_repair();addpath(fullfile(c.root,'real_five'));
if strcmp(mode,'smoke'),p.scenarios=["unload","short_gap","long_gap","real_torque"];p.seeds=1;end
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
c.results=fullfile(c.root,'load_repair_results',stamp);mkdir(c.results);
storage_c=c;storage_c.build=fullfile(c.model_dir,'repair_storage',stamp);
storage=dob_storage_session(storage_c); %#ok<NASGU>
for model=[string(p.legacy_model),string(p.fixed_model)]
    set_param(model,'SignalLogging','off','FastRestart','on');
end
shutdown=onCleanup(@()finish(p)); %#ok<NASGU>
config=struct('mode',mode,'paired_repeats',numel(p.seeds),'classification',p,'base',c, ...
    'hardware_access',false,'physical_performance_validated',false,'control_adaptation',false, ...
    'gap_max_us',5000,'recovery_actual_points',2,'compensation_enabled',false);
dob_write_json(fullfile(c.results,'config.json'),config);
manifest=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
copyfile(fullfile(c.build,'source_manifest.json'),fullfile(c.results,'source_manifest.json'));
rows=struct([]);checks=struct([]);index=0;
for name=p.scenarios
    for seed=p.seeds
        [stimulus,truth,physical,mapping]=phase1_inputs(c,name,seed);pair=cell(1,2);
        for revision=0:1
            if revision==0,model=p.legacy_model;else,model=p.fixed_model;end
            si=Simulink.SimulationInput(model);
            values={stimulus,truth,physical,[0,0,.025],c.plant_vector,1};
            vars={'stimulus','load_truth','physical_current','run_config','plant_parameters','features_enabled'};
            for j=1:numel(vars),si=si.setVariable(vars{j},values{j},'Workspace',model);end
            out=sim(si);Y=out.get('control_log');F=out.get('features_log');B=out.get('legacy_features_log');
            U=out.get('input_log');L=out.get('load_log');P=out.get('truth_log');
            assert(numel(Y.Time)==size(stimulus,1)&&numel(F.Time)==numel(Y.Time)&&numel(B.Time)==numel(Y.Time));
            assert(max(abs(Y.Time-F.Time))<1e-10&&max(abs(Y.Time-B.Time))<1e-10);
            T=array2table(squeeze(Y.Data),'VariableNames',cellstr(dob_schema()));
            T=[table(Y.Time,'VariableNames',{'time_s'}),T, ...
                array2table(squeeze(F.Data),'VariableNames',cellstr(p.feature_names)), ...
                array2table(squeeze(B.Data),'VariableNames',cellstr("legacy_"+p.feature_names(1:16)))];
            T.target_rpm=U.Data(:,1);T.rpm_true=U.Data(:,2)*60/(2*pi);T.iq_true_a=U.Data(:,3);
            T.load_ground_truth_a=L.Data;T.speed_noise_rpm=U.Data(:,4);T.iq_noise_a=U.Data(:,5);
            T.input_valid=U.Data(:,7);T.input_voltage_sat=U.Data(:,8);T.physical_current_pulse_a=physical(:,2);
            if isempty(mapping),T.source_window=zeros(height(T),1);else,T.source_window=mapping(:,1);end
            assert(all(isfinite(T{:,:}),'all')&&max(T.simulation_guard_fault)==0);
            assert(max(abs(T.iq_cmd_a))<=.500001&&all(T.iq_dob_a==0));
            assert(max(abs(U.Data(:,2)-P.Data(:,1)))<1e-12);
            TM=T;
            if revision==0
                for j=1:16,TM.(p.feature_names(j))=T.("legacy_"+p.feature_names(j));end
                TM=removevars(TM,cellstr(p.feature_names(17:end)));
            end
            metric=phase1_metrics(TM,name,seed,revision);
            metric.revision=metric.features_enabled;metric=rmfield(metric,'features_enabled');
            if revision==0,metric.trend_transitions=NaN;else,metric.trend_transitions=T.load_trend_transitions(end);end
            mask=T.time_s>=2.3&T.time_s<6.9;
            valid=TM.load_label_valid>0;metric.unavailable_ms=sum(~valid(mask));
            metric.max_unavailable_ms=longest(~valid(mask));
            metric.event_dob_resets=sum(T.epoch_resets(mask));
            if isempty(rows),rows=metric;else,rows(end+1)=metric;end %#ok<AGROW>
            file=fullfile(c.results,sprintf('%s_seed%03d_revision%d.csv',name,seed,revision));
            writetable(T,file);gz=gzip(file);assert(isfile(gz{1}));delete(file);pair{revision+1}=T;
        end
        % Estimator differences are intended ONLY for source-gap cases. PI,
        % current commands, physical truth and exact exogenous data never differ.
        base=dob_schema();columns=[cellstr(base(1:10)), ...
            {'simulation_guard_fault','travel_deg','id_raw_a','iq_meas_a','time_s','target_rpm', ...
            'rpm_true','iq_true_a','load_ground_truth_a','speed_noise_rpm','iq_noise_a', ...
            'input_valid','input_voltage_sat','physical_current_pulse_a','source_window'}];
        delta=max(abs(pair{1}{:,columns}-pair{2}{:,columns}),[],'all');assert(delta==0);
        if ~ismember(name,["short_gap","long_gap"])
            assert(max(abs(pair{1}{:,cellstr(base)}-pair{2}{:,cellstr(base)}),[],'all')==0, ...
                'Gap adapter altered a healthy/non-source path');
        end
        index=index+1;check=struct('scenario',name,'seed',seed,'control_truth_input_diff',delta);
        if isempty(checks),checks=check;else,checks(index)=check;end %#ok<AGROW>
        writetable(struct2table(rows),fullfile(c.results,'metrics_per_trial.csv'));
        fprintf('REPAIR PAIR %d/%d %s seed%d control_diff=%g\n',index,numel(p.scenarios)*numel(p.seeds),name,seed,delta);
    end
    draw(c,p,pair,name);
end
for k=1:numel(manifest.sources)
    assert(strcmp(dob_sha256(manifest.sources(k).path),manifest.sources(k).sha256));
end
M=struct2table(rows);metrics=setdiff(M.Properties.VariableNames,{'scenario','seed','revision'},'stable');
S=groupsummary(M,{'scenario','revision'},{'mean','std'},metrics);
writetable(S,fullfile(c.results,'metrics_mean_std.csv'));
report=struct('completed',true,'pairs',index,'runs',height(M),'results',c.results, ...
    'control_truth_inputs_identical',true,'source_pins_unchanged',true, ...
    'hardware_access',false,'physical_performance_validated',false,'control_adaptation',false,'pairs_audit',checks);
dob_write_json(fullfile(c.results,'report.json'),report);
fid=fopen(fullfile(c.build,'load_repair_latest_results.txt'),'w');fprintf(fid,'%s',c.results);fclose(fid);
fprintf('COMPLETE REPAIR %d pairs / %d runs -> %s\n',index,height(M),c.results);
end
function n=longest(invalid)
n=0;run=0;for k=1:numel(invalid),if invalid(k),run=run+1;else,run=0;end;n=max(n,run);end
end
function finish(p)
for model=[string(p.legacy_model),string(p.fixed_model)]
    if bdIsLoaded(model),set_param(model,'FastRestart','off');end
end
end
function draw(c,p,pair,name)
A=pair{1};T=pair{2};f=figure('Visible','off','Position',[100 100 1150 950]);tiledlayout(5,1);
nexttile;plot(T.time_s,T.load_ground_truth_a,T.time_s,T.dob_estimate_a,T.time_s,T.load_mean_a);ylabel('A equiv');title(strrep(name,'_',' '));legend('Independent load','DOB fixed','Feature mean');
nexttile;stairs(A.time_s,A.legacy_load_state);yticks(0:5);yticklabels(p.state_names);ylabel('Legacy');
nexttile;stairs(T.time_s,T.load_state);yticks([0 1 2 4]);yticklabels({'UNKNOWN','LIGHT','MEDIUM','HIGH'});ylabel('Level fixed');
nexttile;stairs(T.time_s,T.load_trend_state);yticks(0:3);yticklabels(p.trend_names);ylabel('Trend fixed');
nexttile;plot(T.time_s,A.legacy_load_label_valid,T.time_s,T.load_label_valid);legend('Legacy valid','Fixed valid');ylabel('Quality');xlabel('Time (s)');
exportgraphics(f,fullfile(c.results,char(name+".png")));close(f);
end

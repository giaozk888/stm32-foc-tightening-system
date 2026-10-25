function report=run_load_phase1(mode)
% Actual Simulink paired trials. No MCU transport, no control adaptation.
if nargin<1,mode='full';end
[c,p]=build_load_phase1();addpath(fullfile(c.root,'real_five'));
if strcmp(mode,'smoke'),p.scenarios=["no_load","unload","spike","long_gap","negative_step","real_measurement","real_torque"];p.seeds=1;end
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
c.results=fullfile(c.root,'phase1_results',stamp);mkdir(c.results);
% R2025b To Workspace also uses the recording backend: disabling it returns
% empty logs. Keep complete samples and isolate this run's storage instead.
storage_c=c;storage_c.build=fullfile(c.model_dir,'storage',stamp);
storage=dob_storage_session(storage_c); %#ok<NASGU>
set_param(c.model,'SignalLogging','off','FastRestart','on');
shutdown=onCleanup(@()set_param(c.model,'FastRestart','off')); %#ok<NASGU>
config=struct('phase',1,'mode',mode,'paired_repeats',numel(p.seeds), ...
    'classification',p,'base',c,'hardware_access',false,'physical_performance_validated',false, ...
    'control_dob_feedback',false,'control_adaptation',false);
dob_write_json(fullfile(c.results,'config.json'),config);
manifest=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
rows=struct([]);checks=struct([]);index=0;
for name=p.scenarios
    for seed=p.seeds
        [stimulus,truth,physical,mapping]=phase1_inputs(c,name,seed);
        pair=cell(1,2);
        for enabled=0:1
            si=Simulink.SimulationInput(c.model);
            si=si.setVariable('stimulus',stimulus,'Workspace',c.model);
            si=si.setVariable('load_truth',truth,'Workspace',c.model);
            si=si.setVariable('physical_current',physical,'Workspace',c.model);
            si=si.setVariable('run_config',[0,0,.025],'Workspace',c.model);
            si=si.setVariable('plant_parameters',c.plant_vector,'Workspace',c.model);
            si=si.setVariable('features_enabled',double(enabled),'Workspace',c.model);
            out=sim(si);Y=out.get('control_log');F=out.get('features_log');
            U=out.get('input_log');L=out.get('load_log');P=out.get('truth_log');
            assert(numel(Y.Time)==size(stimulus,1)&&numel(F.Time)==numel(Y.Time), ...
                'Missing logs: controller %d classifier %d expected %d', ...
                numel(Y.Time),numel(F.Time),size(stimulus,1));
            assert(max(abs(Y.Time-F.Time))<1e-10,'Feature/control timestamp mismatch');
            T=array2table(squeeze(Y.Data),'VariableNames',cellstr(dob_schema()));
            T=[table(Y.Time,'VariableNames',{'time_s'}),T, ...
                array2table(squeeze(F.Data),'VariableNames',cellstr(p.feature_names))];
            T.target_rpm=U.Data(:,1);T.rpm_true=U.Data(:,2)*60/(2*pi);
            T.iq_true_a=U.Data(:,3);T.load_ground_truth_a=L.Data;
            T.speed_noise_rpm=U.Data(:,4);T.iq_noise_a=U.Data(:,5);
            T.input_valid=U.Data(:,7);T.input_voltage_sat=U.Data(:,8);
            T.physical_current_pulse_a=physical(:,2);
            if ~isempty(mapping),T.source_window=mapping(:,1);else,T.source_window=zeros(height(T),1);end
            assert(all(isfinite(T{:,:}),'all'),'Nonfinite sample');
            assert(max(T.simulation_guard_fault)==0,'Original software guard triggered');
            assert(max(abs(T.iq_cmd_a))<=.500001&&all(T.iq_dob_a==0));
            assert(max(abs(U.Data(:,2)-P.Data(:,1)))<1e-12);
            if enabled
                isolated=ismember(T.load_reason,[4,5,6,9,10,11]);z=diff(T.load_accepted);
                assert(all(z(isolated(2:end))==0),'Rejected evidence counted valid');
            end
            file=fullfile(c.results,sprintf('%s_seed%03d_features%d.csv',name,seed,enabled));
            writetable(T,file);gz=gzip(file);assert(isfile(gz{1}));delete(file);
            pair{enabled+1}=T;
            metric=phase1_metrics(T,name,seed,enabled);
            if isempty(rows),rows=metric;else,rows(end+1)=metric;end %#ok<AGROW>
        end
        % Includes original observer, PI, quality, resets, inputs AND true plant.
        columns=[cellstr(dob_schema()),{'time_s','target_rpm','rpm_true','iq_true_a', ...
            'load_ground_truth_a','speed_noise_rpm','iq_noise_a','input_valid', ...
            'input_voltage_sat','physical_current_pulse_a','source_window'}];
        maxdiff=max(abs(pair{1}{:,columns}-pair{2}{:,columns}),[],'all');
        assert(maxdiff==0,'Read-only classifier changed original control/plant');
        index=index+1;check=struct('scenario',name,'seed',seed,'max_control_truth_input_diff',maxdiff);
        if isempty(checks),checks=check;else,checks(index)=check;end %#ok<AGROW>
        writetable(struct2table(rows),fullfile(c.results,'metrics_per_trial.csv'));
        fprintf('PAIR %d/%d %s seed%d identical_control=%g\n',index, ...
            numel(p.scenarios)*numel(p.seeds),name,seed,maxdiff);
    end
    draw_phase1(c,p,pair{2},name);
end
for k=1:numel(manifest.sources)
    assert(strcmp(dob_sha256(manifest.sources(k).path),manifest.sources(k).sha256), ...
        'Frozen source changed: %s',manifest.sources(k).path);
end
M=struct2table(rows);
metrics={'valid_rate','unknown_rate','quality_reset_count','transitions','dob_reset_count', ...
    'high_recall','false_high_rate','load_rmse_a','rise_delay_s','high_delay_s', ...
    'release_delay_s','return_light_delay_s','speed_mae_rpm','iq_peak_a','iq_dob_peak_a'};
summary=groupsummary(M,{'scenario','features_enabled'},{'mean','std'},metrics);
writetable(summary,fullfile(c.results,'metrics_mean_std.csv'));
report=struct('completed',true,'pairs',index,'runs',height(M),'results',c.results, ...
    'firmware_and_original_harness_unchanged',true,'all_pairs_exactly_equal',true, ...
    'hardware_access',false,'physical_performance_validated',false,'pairs_audit',checks, ...
    'thresholds_calibrated',false,'control_adaptation',false);
dob_write_json(fullfile(c.results,'report.json'),report);
fid=fopen(fullfile(c.root,'build','phase1_latest_results.txt'),'w');fprintf(fid,'%s',c.results);fclose(fid);
fprintf('COMPLETE %d pairs / %d runs -> %s\n',index,height(M),c.results);
end
function draw_phase1(c,p,T,name)
f=figure('Visible','off','Position',[100 100 1100 850]);
tiledlayout(4,1);
nexttile;plot(T.time_s,T.load_ground_truth_a,T.time_s,T.dob_estimate_a,T.time_s,T.load_mean_a);ylabel('A equiv');legend('Independent load','DOB','Feature mean');title(strrep(name,'_',' '));
nexttile;plot(T.time_s,T.load_trend_a_s);yline(p.features(4),'--');yline(-p.features(4),'--');ylabel('A/s');
nexttile;stairs(T.time_s,T.load_state);yticks(0:5);yticklabels(p.state_names);ylim([-.2 5.2]);
nexttile;plot(T.time_s,T.load_label_valid,T.time_s,T.load_coverage,T.time_s,T.dob_valid);ylabel('Quality');xlabel('Time (s)');legend('Label valid','Window coverage','DOB valid');
exportgraphics(f,fullfile(c.results,char(name+".png")));close(f);
end

function report=run_load_speed(mode)
if nargin<1,mode='full';end
c=build_load_speed();stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
dest=fullfile(c.root,'load_speed_results',stamp);mkdir(dest);storage=dob_storage_session(c); %#ok<NASGU>
scenes=["no_load","step","ramp","unload","spike","id_anomaly","source_gap", ...
    "noise","replay","negative_load","contact_early","contact_late","stop","fault"];
seeds=reshape(c.m.seeds,1,[]);if strcmp(mode,'smoke'),scenes=["no_load","step","contact_early"];seeds=1;end
copyfile(fullfile(c.build,'manifest.json'),fullfile(dest,'manifest.json'));
copyfile(fullfile(c.build,[c.model '.slx']),fullfile(dest,[c.model '.slx']));
config=struct('mode',mode,'scenarios',scenes,'seeds',seeds,'repeats',numel(seeds),'hardware_access',false, ...
    'policy_fixed_before_runs',true,'physical_performance_validated',false,'feedback_gain',.25,'iq_limit',.5, ...
    'workspace_source_time_shift_s',-1e-9, ...
    'acceptance',struct('false_contact',0,'command_limit_a',.500001,'target_floor_rpm',120, ...
    'max_accel_rpm_s',200.01,'max_jerk_rpm_s2',1000.2,'no_new_faults',true,'missed_contact',0));
dob_write_json(fullfile(dest,'config.json'),config);set_param(c.model,'FastRestart','on');
finish=onCleanup(@()set_param(c.model,'FastRestart','off')); %#ok<NASGU>
index=0;
for scene=scenes
    for seed=seeds
        pair=cell(1,2);exogenous=cell(1,2);
        for enabled=0:1
            [stimulus,plant]=load_speed_inputs(c,scene,seed,enabled);exogenous{enabled+1}=stimulus;
            source=stimulus;source(:,1)=source(:,1)-1e-9; % Intended discrete epoch, not previous-ULP row.
            si=Simulink.SimulationInput(c.model);si=si.setVariable('stimulus',source,'Workspace',c.model);
            si=si.setVariable('plant_parameters',plant,'Workspace',c.model);out=sim(si);
            Y=out.get('control_log');U=out.get('inputs_log');P=out.get('truth_log');E=out.get('scenario_log');
            if numel(Y.Time)~=10001||~isequal(squeeze(E.Data),stimulus(:,2:end))
                save(fullfile(dest,'failed_input_alignment.mat'),'Y','E','U','P','stimulus');
                error('Input alignment: Y rows%d, E size%s expected%s, maxdiff%g',numel(Y.Time), ...
                    mat2str(size(squeeze(E.Data))),mat2str(size(stimulus(:,2:end))), ...
                    max(abs(squeeze(E.Data)-stimulus(:,2:end)),[],'all'));
            end
            T=[table(Y.Time,'VariableNames',{'time_s'}),array2table(squeeze(Y.Data),'VariableNames',cellstr(string(c.m.output_names))), ...
                array2table(squeeze(U.Data),'VariableNames',cellstr("input_"+string(c.m.input_names)))];
            names={'omega_true_rad_s','iq_true_a','position_true_deg','load_truth_a','fixture_contact','travel_true_deg'};
            T=[T,array2table(squeeze(P.Data),'VariableNames',names)];
            T.external_load_a=stimulus(:,14);T.fixture_angle_deg=stimulus(:,15);T.fixture_enabled=stimulus(:,16);
            T.plant_j_over_kt=repmat(plant(1),height(T),1);T.plant_b_over_kt=repmat(plant(2),height(T),1);
            T.plant_ic_over_kt=repmat(plant(3),height(T),1);
            assert(all(isfinite(T{:,:}),'all'),'NaN/Inf in logged data');
            file=fullfile(dest,sprintf('%s_seed%03d_enabled%d.csv',scene,seed,enabled));writetable(T,file);gzip(file);delete(file);
            pair{enabled+1}=T;index=index+1;
            dob_write_json(fullfile(dest,'progress.json'),struct('runs',index,'total',numel(scenes)*numel(seeds)*2));
        end
        columns=[1:9,11:16];assert(isequal(exogenous{1}(:,columns),exogenous{2}(:,columns)), 'OFF/ON exogenous drift');
        for side=1:2
            active=pair{side}.control_mode==3|pair{side}.control_mode==4;
            assert(all(pair{side}.iq_limit_a(active)==.5),'Unchanged active-phase recipe current limit');
        end
        fprintf('LOAD SPEED PAIR %s seed%d complete\n',scene,seed);
    end
end
for k=1:numel(c.m.sources),assert(strcmp(dob_sha256(c.m.sources(k).path),c.m.sources(k).sha256),'Source changed');end
report=struct('completed',true,'runs',index,'repeats',numel(seeds),'results',dest, ...
    'consumed_exogenous_verified',true,'hardware_access',false,'physical_performance_validated',false);
dob_write_json(fullfile(dest,'report.json'),report);fid=fopen(fullfile(c.build,'latest_results.txt'),'w');fprintf(fid,'%s',dest);fclose(fid);
fprintf('COMPLETE LOAD SPEED %d runs -> %s\n',index,dest);
end

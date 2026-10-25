function report=run_load_gain(mode)
if nargin<1,mode='full';end
c=build_load_gain();storage=dob_storage_session(c); %#ok<NASGU>
stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));dest=fullfile(c.root,'load_gain_results',stamp);mkdir(dest);
scenes=["no_load","step","ramp","unload","spike","id_anomaly","source_gap", ...
    "noise","replay","negative_load","contact_early","contact_late","stop","fault"];
seeds=reshape(c.m.seeds,1,[]);if strcmp(mode,'smoke'),scenes=["no_load","unload","contact_early"];seeds=1;end
config=struct('mode',mode,'scenarios',scenes,'seeds',seeds,'variants',["off","fixed","adaptive"], ...
    'hardware_access',false,'physical_performance_validated',false,'fast_restart',false, ...
    'actual_plant_parameters_logged',true,'speed_scheduling',false,'max_gain',.25, ...
    'gain_rise_per_s',1,'gain_fall_per_s',2.5,'saturation_feedback_guard_aligned_to_mcu',true, ...
    'acceptance',struct('iq_limit_a',.500001,'dob_limit_a',.025001,'gain_max',.250001, ...
        'strict_jerk_rpm_s2',1000.2,'false_contact',0,'no_new_process_failures',true));
dob_write_json(fullfile(dest,'config.json'),config);copyfile(fullfile(c.build,'manifest.json'),fullfile(dest,'manifest.json'));
copyfile(fullfile(c.build,[c.model,'.slx']),fullfile(dest,[c.model,'.slx']));index=0;
set_param(c.model,'FastRestart','off');
for variant=["off","fixed","adaptive"]
    run_config=[double(variant~="off"),.25,.025,double(variant=="adaptive")];
    for scene=scenes
        for seed=seeds
            [stimulus,plant]=load_speed_inputs(c,scene,seed,0); % Keep speed scheduling OFF in all three groups.
            shifted=stimulus;shifted(:,1)=shifted(:,1)-1e-9;
            si=Simulink.SimulationInput(c.model);si=si.setVariable('stimulus',shifted,'Workspace',c.model);
            si=si.setVariable('plant_parameters',plant,'Workspace',c.model);
            si=si.setVariable('run_config',run_config,'Workspace',c.model);out=sim(si);
            Y=out.get('control_log');U=out.get('inputs_log');P=out.get('truth_log');E=out.get('scenario_log');
            assert(numel(Y.Time)==10001&&isequal(squeeze(E.Data),stimulus(:,2:end)), 'Actual exogenous input mismatch');
            T=[table(Y.Time,'VariableNames',{'time_s'}),array2table(squeeze(Y.Data),'VariableNames',cellstr(string(c.m.output_names))), ...
                array2table(squeeze(U.Data),'VariableNames',cellstr("input_"+string(c.m.input_names)))];
            truth={'omega_true_rad_s','iq_true_a','position_true_deg','load_truth_a','fixture_contact','travel_true_deg','fixture_contact_age_s', ...
                'consumed_j_over_kt','consumed_b_over_kt','consumed_ic_over_kt','consumed_bias_a','consumed_current_tau_s'};
            T=[T,array2table(squeeze(P.Data),'VariableNames',truth)];
            assert(isequal(squeeze(P.Data(:,8:12)),repmat(plant,height(T),1)), 'Actual plant parameter mismatch');
            T.external_load_a=stimulus(:,14);T.fixture_angle_deg=stimulus(:,15);T.fixture_enabled=stimulus(:,16);
            T.requested_j_over_kt=repmat(plant(1),height(T),1);T.requested_b_over_kt=repmat(plant(2),height(T),1);
            T.requested_ic_over_kt=repmat(plant(3),height(T),1);
            assert(all(isfinite(T{:,:}),'all'),'NaN/Inf in logs');
            assert(max(abs(T.iq_cmd_a))<=.500001&&max(abs(T.iq_dob_a))<=.025001,'Original caps');
            assert(max(T.gain_selected)<=.250001&&min(T.gain_selected)>=0,'Gain bounds');
            file=fullfile(dest,sprintf('%s_seed%03d_%s.csv',scene,seed,variant));writetable(T,file);gzip(file);delete(file);
            index=index+1;dob_write_json(fullfile(dest,'progress.json'),struct('runs',index,'total',numel(scenes)*numel(seeds)*3));
            fprintf('GAIN %s %s seed%d complete\n',variant,scene,seed);
        end
    end
end
for k=1:numel(c.m.sources),assert(strcmp(dob_sha256(c.m.sources(k).path),c.m.sources(k).sha256),'Software source changed');end
for k=1:numel(c.m.firmware_unchanged_pins)
    assert(strcmp(dob_sha256(c.m.firmware_unchanged_pins(k).path),c.m.firmware_unchanged_pins(k).sha256),'Firmware source changed');
end
assert(strcmp(dob_sha256(c.m.dll),c.m.dll_sha256),'DLL changed');
report=struct('completed',true,'runs',index,'results',dest,'hardware_access',false,'physical_performance_validated',false);
dob_write_json(fullfile(dest,'report.json'),report);fid=fopen(fullfile(c.build,'latest_results.txt'),'w');fprintf(fid,'%s',dest);fclose(fid);
fprintf('COMPLETE GAIN %d runs -> %s\n',index,dest);
end

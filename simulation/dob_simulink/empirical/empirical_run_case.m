function T=empirical_run_case(c,name,seed,gain,cap)
[stimulus,truth,physical,mapping]=empirical_scenario(c,name,seed);
si=Simulink.SimulationInput(c.model);
vars={'stimulus',stimulus;'load_truth',truth;'physical_current',physical; ...
 'run_config',[gain~=0,gain,cap];'plant_parameters',c.plant_vector};
for j=1:size(vars,1),si=si.setVariable(vars{j,1},vars{j,2},'Workspace',c.model);end
out=sim(si);C=out.get('control_log');P=out.get('truth_log');I=out.get('input_log');
L=out.get('load_log');Q=out.get('pulse_log');U=squeeze(I.Data);
assert(numel(C.Time)==size(stimulus,1)&&max(abs(C.Time-P.Time))<1e-9);
T=array2table(squeeze(C.Data),'VariableNames',cellstr(dob_schema()));
T.time_s=C.Time;T.omega_true_rad_s=U(:,2);T.iq_true_a=U(:,3);
T.iq_regulator_a=P.Data(:,2);T.physical_current_pulse_a=Q.Data;
assert(max(abs(T.iq_true_a-T.iq_regulator_a-T.physical_current_pulse_a))<1e-10);
T.rpm_true=U(:,2)*60/(2*pi);T.load_ground_truth_a=L.Data;
T.target_rpm=U(:,1);T.speed_noise_rpm=U(:,4);T.iq_noise_a=U(:,5);
T.input_valid=U(:,7);T.input_voltage_sat=U(:,8);T.input_encoder_age_us=U(:,9);T.input_running=U(:,10);
% Mapping describes the scheduled grid. Actual consumed currents/noise/pulse
% above are logged at the controller port (From Workspace ZOH boundary may
% select the previous row). Do not claim these labels are original replay.
T.scheduled_source_id=mapping(:,1);T.scheduled_original_us=mapping(:,2);T.scheduled_grid_error_us=mapping(:,3);
T.ground_truth_available=true(height(T),1); % synthetic external load, not historical motor truth
T=movevars(T,'time_s','Before',1);
assert(all(isfinite(table2array(T(:,cellstr(dob_schema())))),'all'));
assert(all(abs(T.iq_cmd_a)<=.5+1e-7)&&all(abs(T.iq_dob_a)<=cap+1e-7));
assert(~any(T.simulation_guard_fault));
suspect=bitand(uint32(T.quality_reason),8)~=0&T.lpf_updated==0;
assert(all(T.abs_id_lpf_a(suspect)==T.id_lpf_before_a(suspect)),'Quarantine polluted LPF');
end

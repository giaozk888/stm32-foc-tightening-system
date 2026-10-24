function T=dob_run_case(c,name,seed,gain,cap)
[stimulus,load_truth]=dob_scenario(c,name,seed);
si=Simulink.SimulationInput(c.model);
si=si.setVariable('stimulus',stimulus,'Workspace',c.model);
si=si.setVariable('load_truth',load_truth,'Workspace',c.model);
si=si.setVariable('run_config',[gain~=0,gain,cap],'Workspace',c.model);
si=si.setVariable('plant_parameters',c.plant_vector,'Workspace',c.model);
out=sim(si);control=out.get('control_log');truth=out.get('truth_log');
inputs=out.get('input_log');load_record=out.get('load_log');U=squeeze(inputs.Data);
assert(numel(control.Time)==size(stimulus,1),'Unexpected controller sampling: got %d expected %d',numel(control.Time),size(stimulus,1));
assert(max(abs(control.Time-truth.Time))<1e-9,'Truth/control not synchronous');
T=array2table(squeeze(control.Data),'VariableNames',cellstr(dob_schema()));
assert(max(abs(U(:,2:3)-truth.Data(:,1:2)),[],'all')<1e-12,'Input/truth epoch mismatch');
T.time_s=control.Time;T.omega_true_rad_s=U(:,2);T.iq_true_a=U(:,3);
T.rpm_true=U(:,2)*60/(2*pi);T.load_ground_truth_a=load_record.Data;
T.target_rpm=U(:,1);T.speed_noise_rpm=U(:,4);T.iq_noise_a=U(:,5);
T.input_valid=U(:,7);T.input_voltage_sat=U(:,8);T.input_encoder_age_us=U(:,9);
T.input_running=U(:,10);T.ground_truth_available=true(height(T),1);
T=movevars(T,'time_s','Before',1);
end

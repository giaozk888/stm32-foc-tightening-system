function result=dob_replay(path,c)
% Strict epoch-level replay, no guessed timestamps/sequence, no interpolation.
% Metadata are mandatory. Sparse rings must remain evidence-only and are
% deliberately NOT passed to this 1ms control adapter as invented history.
T=readtable(path);required=["time_s","omega_true_rad_s","iq_true_a", ...
 "target_rpm","speed_noise_rpm","iq_noise_a","id_raw_a","input_valid", ...
 "input_voltage_sat","input_encoder_age_us","input_running"];
assert(all(ismember(required,string(T.Properties.VariableNames))),'Incomplete epoch replay CSV');
assert(all(abs(diff(T.time_s)-.001)<1e-8),'Sparse/nonuniform records: no synthetic 1kHz reconstruction');
dob_bridge_mex('reset',fullfile(c.build,'dob_host.dll'),[0,0,.025]);
Y=zeros(height(T),33);
for k=1:height(T)
 u=[T.target_rpm(k),T.omega_true_rad_s(k),T.iq_true_a(k), ...
  T.speed_noise_rpm(k),T.iq_noise_a(k),T.id_raw_a(k),T.input_valid(k), ...
  T.input_voltage_sat(k),T.input_encoder_age_us(k),T.input_running(k)];
 Y(k,:)=dob_bridge_mex('step',T.time_s(k),u);
end
original=table2array(T(:,cellstr(dob_schema())));
% CSV double serialization is not guaranteed bit-exact; this tolerance is
% below a microamp/rpm and never excuses a counter/status disagreement.
discrete=[12,13,16:21,23:27,30];
delta=max(abs(Y-original),[],'all');
result=struct('passed',delta<1e-6&&isequal(Y(:,discrete),original(:,discrete)), ...
 'max_difference',delta,'csv_tolerance',1e-6, ...
 'ground_truth_available',ismember('load_ground_truth_a',T.Properties.VariableNames)&&all(T.ground_truth_available), ...
 'physical_performance_validated',false,'note','Full synthetic epoch replay only; no interpolated physical ground truth.');
dob_write_json(fullfile(c.results,'replay_check.json'),result);
if ~result.passed
 D=array2table(Y-original,'VariableNames',cellstr(dob_schema()));D.time_s=T.time_s;
 writetable(D,fullfile(c.results,'replay_difference.csv'));
end
assert(result.passed,'C replay differs from Simulink C execution: max difference %g',delta);
end

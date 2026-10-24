function test_dob_simulink_case(T,c)
% Do not silently accept a numerically finite but behaviorally wrong harness.
assert(all(abs(diff(T.time_s)-c.dt)<1e-8));
assert(all(abs(T.accel_ref_rpm_s)<=200.001));
assert(all(abs(T.iq_acc_ff_a-.000046875*T.accel_ref_rpm_s)<1e-7));
active=abs(T.speed_ref_rpm)>2&T.input_running~=0;
assert(all(abs(T.iq_friction_a(active)-.105*sign(T.speed_ref_rpm(active)))<1e-7));
assert(all(abs(T.iq_cmd_a)<=.5+1e-7));
assert(all(abs(T.iq_dob_a)<=.025+1e-7));
assert(all(abs(T.speed_integrator_a)<=.35+1e-7));
assert(all(abs(T.iq_meas_a-(T.iq_true_a+T.iq_noise_a))<1e-7));
assert(all(abs(T.rpm_true-T.omega_true_rad_s*60/(2*pi))<1e-10));
assert(T.iq_cmd_a(end)==0&&T.iq_dob_a(end)==0);
end

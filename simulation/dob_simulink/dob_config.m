function c=dob_config()
% All overrides affect ONLY the offline Simulink model, never A/B firmware.
c.root=fileparts(mfilename('fullpath'));
c.repo=fileparts(fileparts(c.root));
c.build=fullfile(c.root,'build');c.results=fullfile(c.root,'results');
c.model='dob_offline';c.dt=.001;c.pwm_dt=.00005;c.stop_s=7;
c.target_rpm=240;c.seeds=101:105;
c.plant_vector=[.000386049,.00155158,.11945168237076952,.0005496600325149542,.001];
c.gains=[0,.15,.25,.5,1];c.caps_a=[.0125,.025];
c.noise_speed_rpm=.4;c.noise_current_a=.002;
c.noise_id_a=.003;c.id_baseline_a=.005;c.id_spike_a=.700;c.id_persistent_a=.090;
c.load_a=.04;c.event_s=3;c.unload_s=4.6;
% Software acceptance criteria, NOT safety/firmware thresholds. Declared
% BEFORE running; report failures rather than changing criteria to pass.
c.accept.rmse_a=.012;c.accept.bias_a=.008;c.accept.valid_rate=.90;
c.accept.delay_s=.5;c.accept.recovery_s=.8;
c.hardware_access=false;c.physical_performance_validated=false;
end

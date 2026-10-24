function c=empirical_config()
addpath(fileparts(fileparts(mfilename('fullpath'))));
base=dob_config();c=base;c.base=base;
c.root=fileparts(mfilename('fullpath'));c.results=fullfile(c.root,'results');
c.model='dob_empirical';c.model_dir=fullfile(c.root,'build');
c.gains=[0,.25,.5,1];c.seeds=101:105;
c.cases=["nominal","measured_once","measurement_train","torque_train","unloaded_stress"];
c.event_library=fullfile(c.root,'data','events.csv');
c.event_schedule_s=[2.6,3.2,3.8,4.4,5.0]; % Synthetic stress rate, not measured frequency.
end

function [stimulus,load_truth]=dob_scenario(c,name,seed)
% Exogenous truth has NO dependency on estimated disturbance or controller.
rng(seed,'twister');t=(0:c.dt:c.stop_s)';n=numel(t);
target=c.target_rpm*double(t>=.2);load=zeros(n,1);
speed_noise=c.noise_speed_rpm*randn(n,1);iq_noise=c.noise_current_a*randn(n,1);
id=c.id_baseline_a+c.noise_id_a*randn(n,1);valid=ones(n,1);sat=zeros(n,1);age=zeros(n,1);run=ones(n,1);
if name=="negative_step",target=-target;end
switch string(name)
 case {"step","negative_step","spike","persistent_id","short_gap","long_gap","voltage_sat","noise","unload"}
  load(t>=c.event_s&t<c.unload_s)=c.load_a;
 case "ramp"
  load=c.load_a*min(max((t-c.event_s)/1.0,0),1);load(t>=c.unload_s)=0;
 case "no_load"
 otherwise,error('Unknown scenario: %s',name);
end
if name=="negative_step",load=-load;end
switch string(name)
 case "spike",id(round(3.8/c.dt)+1)=c.id_spike_a;
 case "persistent_id",id(t>=3.8&t<4.1)=c.id_persistent_a;
 case "short_gap",valid(t>=3.8&t<3.803)=0;
 case "long_gap",valid(t>=3.8&t<3.83)=0;
 case "voltage_sat",sat(t>=3.8&t<3.83)=1;
 case "noise",speed_noise=3*speed_noise;iq_noise=5*iq_noise;
end
% Last epoch stops output. Not a board-side command or automatic restart.
run(end)=0;
stimulus=[t,target,speed_noise,iq_noise,id,valid,sat,age,run];
load_truth=[t,load];
end

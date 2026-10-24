function [stimulus,truth,physical,mapping,amplitude]=real_five_inputs(c,hypothesis,seed)
% Measured windows condition exogenous inputs. They are NOT true load labels.
[stimulus,truth]=dob_scenario(c,'step',seed);t=stimulus(:,1);physical=[t,zeros(size(t))];
mapping=zeros(numel(t),3);E=readtable(c.events,'TextType','string');
rng(10000+seed,'twister');
amplitude=.02+.04*rand;rise=.2*double(mod(seed,2)==0);
if rise==0,truth(:,2)=amplitude*double(t>=c.event_s&t<c.unload_s);
else,truth(:,2)=amplitude*min(max((t-c.event_s)/rise,0),1).*double(t<c.unload_s);end
% Source-window holdout: gain selection uses sources1..3 only; sources4..5
% never enter the first60 tuning seeds. Last40 are held-out evaluation.
if seed<=60,pool=1:3;else,pool=4:5;end
for start=2.3:.192:6.5
 source=pool(randi(numel(pool)));B=E(E.source_id==source,:);
 elapsed=B.relative_us*1e-6;slots=round((start+elapsed)/c.dt)+1;
 assert(numel(unique(slots))==height(B)&&all(slots<=numel(t)));
 stimulus(slots,5)=B.id_raw_a;
 if string(hypothesis)=="measurement"
  stimulus(slots,4)=stimulus(slots,4)+B.iq_residual_a;
  % High-pass speed is an ASSUMED observation disturbance, not proven noise.
  stimulus(slots,3)=stimulus(slots,3)+B.speed_highpass_rpm;
 else
  physical(slots,2)=B.iq_residual_a;
  % Do not also force the measured speed when current pulses drive the plant.
 end
 mapping(slots,:)=[B.source_id,B.original_us,(t(slots)-start-elapsed)*1e6];
end
end

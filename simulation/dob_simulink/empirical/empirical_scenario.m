function [stimulus,truth,physical,mapping]=empirical_scenario(c,name,seed)
[stimulus,truth]=dob_scenario(c,'step',seed);t=stimulus(:,1);physical=[t,zeros(size(t))];
mapping=zeros(numel(t),3); % source_id, original_us, nearest-grid timing error_us
if name=="nominal",return;end
E=readtable(c.event_library,'TextType','string');rng(seed,'twister');
if name=="measured_once",starts=3.8;
elseif name=="unloaded_stress",starts=2.3:.040:5.8;truth(:,2)=0;
else,starts=c.event_schedule_s;end
for j=1:numel(starts)
 if name=="measured_once",source=1;else,source=randi(2);end
 B=E(E.source_id==source,:);
 % Explicit synthetic regridding, preserving values/pairing. No interpolation
 % across the excluded 16ms recovery tail or claims of original 1kHz cadence.
 elapsed=B.relative_us*1e-6;slots=round((starts(j)+elapsed)/c.dt)+1;
 assert(numel(unique(slots))==height(B)&&all(slots>=1&slots<=numel(t)));
 stimulus(slots,5)=B.id_raw_a;
 if name=="torque_train"
  physical(slots,2)=B.iq_residual_a; % alternative: actual torque-current pulse
 else
  stimulus(slots,4)=stimulus(slots,4)+B.iq_residual_a; % observation-only artifact
 end
 mapping(slots,:)=[B.source_id,B.original_us,(t(slots)-starts(j)-elapsed)*1e6];
end
end

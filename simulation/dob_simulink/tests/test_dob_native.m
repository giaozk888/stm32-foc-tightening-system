function results=test_dob_native(c)
% Executes the compiled ORIGINAL C monitor/admission/feedback, not a MATLAB
% rewrite. Source faults remain faults; scalar excursions are not declared
% physically impossible by an invented absolute bound.
dll=fullfile(c.build,'dob_host.dll');names=dob_schema();idx=@(s)find(names==s);
model=[.0003782906586526162,.0015676864325576986,.11945168237076952,.0005496600325149542];
tests={};
for direction=[1,-1]
 w=20*direction;load=.02*direction;
 iq=model(2)*w+model(3)*direction+model(4)+load;
 u=[w*60/(2*pi),w,iq,0,0,.005,1,0,0,1];
 dob_bridge_mex('reset',dll,[1,.25,.025]);
 for k=0:2999,y=dob_bridge_mex('step',k*.001,u);end
 assert(y(idx('dob_valid'))==1&&abs(y(idx('dob_estimate_a'))-load)<1e-5);
 assert(abs(y(idx('iq_dob_a'))-.25*load)<1e-5);
 tests{end+1}=sprintf('signed disturbance/compensation %d',direction); %#ok<AGROW>
 before=y;u(6)=.700;y=dob_bridge_mex('step',3,u);
 assert(y(idx('lpf_updated'))==0&&y(idx('abs_id_lpf_a'))==before(idx('abs_id_lpf_a')));
 assert(y(idx('epoch_resets'))==0&&y(idx('dob_valid'))==0);
 assert(y(idx('warmup_s'))==before(idx('warmup_s')));
 assert(y(idx('id_bad_us'))==before(idx('id_bad_us')));
 u(6)=.005;y=dob_bridge_mex('step',3.001,u);
 assert(y(idx('epoch_resets'))==0&&y(idx('dob_valid'))==0);
 for k=3002:3020,y=dob_bridge_mex('step',k*.001,u);end
 assert(y(idx('dob_valid'))==1);
 tests{end+1}='single700mA isolated before LPF; no reset or warmup loss'; %#ok<AGROW>
 for k=3021:3220,u(6)=.09;y=dob_bridge_mex('step',k*.001,u);end
 assert(y(idx('dob_valid'))==0&&y(idx('id_bad_us'))>=20000);
 assert(y(idx('dob_status'))==256&&abs(y(idx('iq_dob_a')))<1e-8);
 tests{end+1}='persistent Id detected; feedback expired'; %#ok<AGROW>
 for k=3221:4020,u(6)=.005;y=dob_bridge_mex('step',k*.001,u);end
 assert(y(idx('dob_valid'))==1);
 tests{end+1}='persistent Id recovery/re-warmup'; %#ok<AGROW>
 % Idempotency if Simulink evaluates the same major timestamp twice.
 again=dob_bridge_mex('step',4.020,u);assert(isequal(y,again));
 tests{end+1}='same-epoch repeated Outputs is idempotent'; %#ok<AGROW>
 u(9)=3000;y=dob_bridge_mex('step',4.021,u);
 assert(y(idx('dob_valid'))==0&&bitand(uint32(y(idx('dob_status'))),64));
 tests{end+1}='encoder age check remains active'; %#ok<AGROW>
end
% Test hard long trusted-data gap via non-coherent observations. Rejected
% samples do not poison LPF; expiration is recoverable, not a run latch.
dob_bridge_mex('reset',dll,[1,1,.025]);u=[240,8*pi,.2,0,0,.005,1,0,0,1];
for k=0:2999,y=dob_bridge_mex('step',k*.001,u);end
reset_before=y(idx('reset_count'));lpf_before=y(idx('abs_id_lpf_a'));
for k=3000:3015,u(6)=.7*(-1)^k;y=dob_bridge_mex('step',k*.001,u);end
assert(y(idx('reset_count'))==reset_before+1);
assert(y(idx('abs_id_lpf_a'))==lpf_before);
for k=3016:3816,u(6)=.005;y=dob_bridge_mex('step',k*.001,u);end
assert(y(idx('dob_valid'))==1);tests{end+1}='long incoherent gap resets once and recovers';
% Large gains cannot bypass cap or aggregate clamp. Direct input speed/source
% still admissible; maximum actual output also checked on every scenario.
dob_bridge_mex('reset',dll,[1,100,.025]);u=[240,8*pi,.3,0,0,.005,1,0,0,1];
for k=0:3499
 y=dob_bridge_mex('step',k*.001,u);
 assert(abs(y(idx('iq_dob_a')))<=.025+1e-7&&abs(y(idx('iq_cmd_a')))<=.5+1e-7);
 assert(abs(y(idx('speed_integrator_a')))<=.35+1e-7);
end
u(10)=0;y=dob_bridge_mex('step',3.5,u);
assert(y(idx('iq_cmd_a'))==0&&y(idx('iq_dob_a'))==0);
tests{end+1}='compensation/total/integrator limits and STOP';
for bad=[NaN,Inf,-Inf]
 dob_bridge_mex('reset',dll,[1,.25,.025]);u=[240,20,.2,0,0,.005,1,0,0,1];u(2)=bad;
 y=dob_bridge_mex('step',0,u);
 assert(y(idx('simulation_guard_fault'))==1&&y(idx('iq_cmd_a'))==0&&y(idx('iq_dob_a'))==0&&y(idx('dob_valid'))==0);
end
tests{end+1}='NaN/Inf explicit invalidation and zero command';
dob_bridge_mex('reset',dll,[0,0,.025]);w=20;
iq=model(2)*w+model(3)+model(4)+.02;
for k=0:1499
 now=100000+k*1000;u=[now+20,now,1000,w,.005,iq,k*20+20,now-20,now,1,0,0,1,0];
 y=dob_bridge_mex('observe',u);
end
assert(y(idx('dob_valid'))==1&&abs(y(idx('dob_estimate_a'))-.02)<1e-5);
tests{end+1}='metadata-exact observer-only epoch replay';
u(1:2)=u(1:2)+1000;u(8:9)=u(8:9)+1000;
y=dob_bridge_mex('observe',u); % Intentionally duplicate actual ADC sequence.
assert(y(idx('dob_valid'))==0&&bitand(uint32(y(idx('dob_status'))),512));
tests{end+1}='observer replay rejects duplicate ADC sequence';
u(1:2)=u(1:2)+1000;u(7)=u(7)+20;u(8:9)=u(8:9)+1000;u(8)=u(1)-500;
y=dob_bridge_mex('observe',u);
assert(y(idx('dob_valid'))==0&&bitand(uint32(y(idx('dob_status'))),64));
tests{end+1}='observer replay retains actual source-age failure';
results=struct('passed',true,'count',numel(tests),'tests',{tests}, ...
 'hardware_access',false,'physical_performance_validated',false);
dob_write_json(fullfile(c.results,'native_regressions.json'),results);
fprintf('PASS: %d native C contracts\n',numel(tests));
end

function [stimulus,plant]=load_speed_inputs(c,name,seed,enabled)
% Pre-generated exogenous sequences identical between each OFF/ON pair.
rng(25000+seed,'twister');t=(0:.001:10)';n=numel(t);direction=1;
if strcmp(name,'negative_load'),direction=-1;end
target=direction*240*double(t>=.2);sn=.4*randn(n,1);qn=.002*randn(n,1);
id=.005+.003*randn(n,1);valid=ones(n,1);sat=zeros(n,1);age=zeros(n,1);
run=ones(n,1);run(end)=0;stop=zeros(n,1);fault=zeros(n,1);load=zeros(n,1);fixture=zeros(n,1);angle=1e6*ones(n,1);
switch string(name)
    case 'no_load'
    case {'step','negative_load'},load(t>=3)=.080;
    case 'ramp',load=.08*min(1,max(0,(t-3)/2));
    case 'unload',load(t>=3&t<5)=.100;
    case 'spike',id(abs(t-3.8)<.0001)=.700;
    case 'id_anomaly',load(t>=3)=.080;id(t>=4&t<4.5)=.090;
    case 'source_gap',load(t>=3)=.080;valid(t>=4&t<4.4)=0;
    case 'noise',load(t>=3&t<5)=.080;sn=3*sn;qn=5*qn;
    case 'replay'
        load(t>=3&t<5)=.080;E=readtable(fullfile(c.root,'real_five','data','events.csv'));
        if seed<=5,pool=1:3;else,pool=4:5;end
        for start=2.2:.192:8
            block=E(E.source_id==pool(randi(numel(pool))),:);
            index=round((start+block.relative_us*1e-6)/.001)+1;good=index<=n;index=index(good);block=block(good,:);
            sn(index)=sn(index)+block.speed_highpass_rpm;qn(index)=qn(index)+block.iq_residual_a;id(index)=block.id_raw_a;
        end
    case {'contact_early','contact_late'}
        load(t>=2)=.040;fixture(:)=1;
        if strcmp(name,'contact_early'),value=3200;else,value=6000;end
        angle(:)=value*(.9+.2*rand());
    case 'stop',load(t>=3)=.080;stop(t>=4.3)=1;
    case 'fault',load(t>=3)=.080;fault(t>=4.3)=1;
    otherwise,error('Unknown stage2 scenario %s',name);
end
load=direction*load;
% Declared parameter uncertainty: paired identical plant, ±10% inertial,
% ±10% viscous, ±5% Coulomb; no change to frozen observer constants.
plant=reshape(c.m.plant,1,[]);plant(1)=plant(1)*(.9+.2*rand());
plant(2)=plant(2)*(.9+.2*rand());plant(3)=plant(3)*(.95+.1*rand());
stimulus=[t,target,sn,qn,id,valid,sat,age,run,enabled*ones(n,1),direction*ones(n,1),stop,fault,load,angle,fixture];
end

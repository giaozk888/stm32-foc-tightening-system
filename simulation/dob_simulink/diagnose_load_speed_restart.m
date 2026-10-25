function diagnose_load_speed_restart()
% Software-only reproduction of non-tunable parameter caching; never a plant test.
c=build_load_speed_contact('legacy');storage=dob_storage_session(c); %#ok<NASGU>
set_param(c.model,'FastRestart','on');items=[];
for seed=1:2
    [stimulus,plant]=load_speed_contact_inputs(c,'no_load',seed);
    stimulus(:,1)=stimulus(:,1)-1e-9;
    si=Simulink.SimulationInput(c.model);si=si.setVariable('stimulus',stimulus,'Workspace',c.model);
    si=si.setVariable('plant_parameters',plant,'Workspace',c.model);out=sim(si);
    P=out.get('truth_log');actual=squeeze(P.Data(1,8:12));
    items=[items;struct('seed',seed,'requested',plant,'consumed',reshape(actual,1,[]), ...
        'match',isequal(reshape(actual,1,[]),plant))]; %#ok<AGROW>
end
set_param(c.model,'FastRestart','off');close_system(c.model,0);
dob_write_json(fullfile(c.build,'restart_parameter_probe.json'),items);
disp(items);
end

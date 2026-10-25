function report=run_load_speed_contact(mode,resume_dest)
if nargin<1,mode='full';end
root=fileparts(mfilename('fullpath'));stamp=char(datetime('now','Format','yyyyMMdd_HHmmss'));
if nargin<2,dest=fullfile(root,'load_speed_contact_results',stamp);mkdir(dest);else,dest=resume_dest;end
scenes=["no_load","contact_early","contact_late","contact_cancel","source_gap","unload","stop","fault"];
seeds=[1,2,3,4,5,61,62,63,64,65];
if strcmp(mode,'smoke'),scenes=["contact_early","contact_cancel"];seeds=1;end
config=struct('scenarios',scenes,'seeds',seeds,'hardware_access',false, ...
    'physical_performance_validated',false,'fixture_release_after_contact_s',.080, ...
    'workspace_source_time_shift_s',-1e-9,'pi_and_protections_unchanged',true);
if nargin<2
    dob_write_json(fullfile(dest,'config.json'),config);
else
    assert(isequal(jsondecode(fileread(fullfile(dest,'config.json'))),jsondecode(jsonencode(config))), 'Resume config changed');
end
index=0;
for revision=["legacy","candidate"]
    c=build_load_speed_contact(char(revision));storage=dob_storage_session(c); %#ok<NASGU>
    copyfile(fullfile(c.build,[c.model '.slx']),fullfile(dest,[c.model '.slx']));
    if revision=="legacy",names=c.m.legacy_output_names;else,names=c.m.output_names;end
    set_param(c.model,'FastRestart','on');
    for scene=scenes
        for seed=seeds
            file=fullfile(dest,sprintf('%s_seed%03d_%s.csv',scene,seed,revision));
            if nargin>=2 && isfile([file,'.gz'])
                % Independent final audit reads every file, including resumed records.
                index=index+1;continue;
            end
            [stimulus,plant]=load_speed_contact_inputs(c,scene,seed);
            shifted=stimulus;shifted(:,1)=shifted(:,1)-1e-9;
            si=Simulink.SimulationInput(c.model);si=si.setVariable('stimulus',shifted,'Workspace',c.model);
            si=si.setVariable('plant_parameters',plant,'Workspace',c.model);out=sim(si);
            Y=out.get('control_log');U=out.get('inputs_log');P=out.get('truth_log');E=out.get('scenario_log');
            assert(numel(Y.Time)==10001 && isequal(squeeze(E.Data),stimulus(:,2:end)), 'Consumed input alignment');
            T=[table(Y.Time,'VariableNames',{'time_s'}),array2table(squeeze(Y.Data),'VariableNames',cellstr(string(names))), ...
                array2table(squeeze(U.Data),'VariableNames',cellstr("input_"+string(c.m.input_names)))];
            truth={'omega_true_rad_s','iq_true_a','position_true_deg','load_truth_a','fixture_contact','travel_true_deg','fixture_contact_age_s'};
            T=[T,array2table(squeeze(P.Data),'VariableNames',truth)];
            T.external_load_a=stimulus(:,14);T.fixture_angle_deg=stimulus(:,15);T.fixture_enabled=stimulus(:,16);
            T.plant_j_over_kt=repmat(plant(1),height(T),1);T.plant_b_over_kt=repmat(plant(2),height(T),1);
            T.plant_ic_over_kt=repmat(plant(3),height(T),1);
            assert(all(isfinite(T{:,:}),'all'),'NaN/Inf');
            writetable(T,file);gzip(file);delete(file);
            index=index+1;dob_write_json(fullfile(dest,'progress.json'),struct('runs',index,'total',numel(scenes)*numel(seeds)*2));
            fprintf('CONTACT %s %s seed%d complete\n',revision,scene,seed);
        end
    end
    set_param(c.model,'FastRestart','off');close_system(c.model,0);
end
for k=1:numel(c.m.sources),assert(strcmp(dob_sha256(c.m.sources(k).path),c.m.sources(k).sha256),'Source changed');end
assert(strcmp(dob_sha256(c.m.legacy_dll),c.m.legacy_dll_sha256),'Legacy DLL changed');
copyfile(fullfile(c.build,'manifest.json'),fullfile(dest,'manifest.json'));
report=struct('completed',true,'runs',index,'results',dest,'hardware_access',false,'physical_performance_validated',false);
dob_write_json(fullfile(dest,'report.json'),report);fid=fopen(fullfile(c.build,'latest_results.txt'),'w');fprintf(fid,'%s',dest);fclose(fid);
fprintf('COMPLETE CONTACT %d runs -> %s\n',index,dest);
end

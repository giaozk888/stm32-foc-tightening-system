function [c,p]=build_load_repair()
% Two independent DLL/MEX instances: loader caches may NOT switch DLL paths.
[c,p]=build_load_phase1();native=fullfile(c.root,'native');common=fullfile(c.repo,'firmware_common');
legacy=fullfile(native,'legacy_phase1');pins=jsondecode(fileread(fullfile(legacy,'source_pins.json')));
assert(strcmp(dob_sha256(fullfile(legacy,'load_features.c')),pins.load_features_c));
assert(strcmp(dob_sha256(fullfile(legacy,'load_features.h')),pins.load_features_h));
mex('-silent',['-I',legacy],'-output','load_features_legacy_sfun','-outdir',c.model_dir, ...
    fullfile(legacy,'load_features_sfun.c'),fullfile(legacy,'load_features.c'));
manifest=jsondecode(fileread(fullfile(c.build,'source_manifest.json')));
flags=reshape(string(manifest.flags),1,[]);flags(end+1)="DOB_OFFLINE_SOURCE_GAP_FIX=1";
sources={fullfile(native,'dob_host.c'),fullfile(common,'mechanical_dob_monitor.c'), ...
    fullfile(common,'speed_scurve.c'),fullfile(common,'speed_accel_feedforward.c'), ...
    fullfile(common,'speed_friction_compensation.c')};
c.fixed_dll=fullfile(c.model_dir,'dob_host_fixed.dll');
gcc='D:\Qt\Tools\mingw1310_64\bin\gcc.exe';
cmd=sprintf('"%s" -std=c11 -O2 -Wall -Wextra -Werror -shared -include "%s" -I"%s" ', ...
    gcc,fullfile(native,'host_compat.h'),common);
for f=flags,cmd=[cmd,' -D',char(f)];end %#ok<AGROW>
for f=sources,cmd=[cmd,' "',f{1},'"'];end %#ok<AGROW>
[rc,txt]=system([cmd,' -o "',c.fixed_dll,'"']);assert(rc==0,'%s',txt);
mex('-silent','-DDOB_CONTROLLER_SFUN_NAME=dob_controller_fixed_sfun', ...
    '-output','dob_controller_fixed_sfun','-outdir',c.model_dir,fullfile(native,'dob_controller_sfun.c'));
ws=get_param(c.model,'ModelWorkspace');assignin(ws,'legacy_features_config',p.features(1:8));
add_block('simulink/User-Defined Functions/S-Function',[c.model '/Legacy_Classification'], ...
    'FunctionName','load_features_legacy_sfun','Parameters','features_enabled, legacy_features_config', ...
    'Position',[900 680 1130 740]);
add_block('simulink/Sinks/To Workspace',[c.model '/Legacy_Classification_Log'], ...
    'VariableName','legacy_features_log','SaveFormat','Timeseries','SampleTime','.001', ...
    'MaxDataPoints','inf','Position',[1230 680 1400 720]);
set_param(c.model,'SimulationCommand','update');
add_line(c.model,'Original_C_SpeedPI_Scurve_DOB_Quality/1','Legacy_Classification/1','autorouting','on');
add_line(c.model,'Controller_Inputs/1','Legacy_Classification/2','autorouting','on');
add_line(c.model,'Legacy_Classification/1','Legacy_Classification_Log/1');
p.legacy_model='dob_load_repair_legacy';p.fixed_model='dob_load_repair_fixed';
save_system(c.model,fullfile(c.model_dir,[p.legacy_model '.slx']));
if ~bdIsLoaded(p.legacy_model),load_system(fullfile(c.model_dir,[p.legacy_model '.slx']));end
save_system(p.legacy_model,fullfile(c.model_dir,[p.fixed_model '.slx']));
if ~bdIsLoaded(p.fixed_model),load_system(fullfile(c.model_dir,[p.fixed_model '.slx']));end
set_param([p.fixed_model '/Original_C_SpeedPI_Scurve_DOB_Quality'], ...
    'FunctionName','dob_controller_fixed_sfun');
ws=get_param(p.fixed_model,'ModelWorkspace');assignin(ws,'host_dll',c.fixed_dll);
save_system(p.fixed_model,fullfile(c.model_dir,[p.fixed_model '.slx']));
load_system(fullfile(c.model_dir,[p.legacy_model '.slx']));
for f={'load_features.c','load_features.h','load_features_sfun.c','source_pins.json'}
    path=fullfile(legacy,f{1});
    manifest.sources(end+1)=struct('path',path,'sha256',dob_sha256(path));
end
manifest.fixed_flags=flags;manifest.fixed_dll_sha256=dob_sha256(c.fixed_dll);
dob_write_json(fullfile(c.build,'source_manifest.json'),manifest);
fprintf('PASS: frozen legacy classifier + isolated fixed source-gap DLL/MEX\n');
end

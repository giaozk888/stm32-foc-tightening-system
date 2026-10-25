function c=build_load_speed_contact(revision)
% Separate models and S-function modules prevent static DLL loader aliasing.
root=fileparts(mfilename('fullpath'));build=fullfile(root,'load_speed_contact_work');
source=fileread(fullfile(root,'build_load_speed.m'));
source=strrep(source,'function c=build_load_speed()','function c=build_contact_generated()');
source=strrep(source,'c.root=fileparts(mfilename(''fullpath''))','c.root=fileparts(fileparts(mfilename(''fullpath'')))');
source=strrep(source,'''load_speed_work''','''load_speed_contact_work''');
source=strrep(source,'''dob_rundown_load_speed''',['''dob_load_contact_',revision,'''']);
source=strrep(source,'load_speed_controller_sfun',['contact_',revision,'_controller_sfun']);
source=strrep(source,'load_speed_plant_sfun','load_speed_contact_plant_sfun');
line='mex(''-silent'',''-outdir'',c.build,fullfile(native,''load_speed_contact_plant_sfun.c''));';
source=strrep(source,line,['if ~isfile(fullfile(c.build,[''load_speed_contact_plant_sfun.'',mexext])),',line,'end']);
source=strrep(source,'''Outputs'',''6''','''Outputs'',''7''');
if strcmp(revision,'candidate')
    source=strrep(source,'PortWidth(S,0,64)','PortWidth(S,0,66)');
    source=strrep(source,'''InputPortWidth'',''64''','''InputPortWidth'',''66''');
else
    source=strrep(source,'''host_dll'',c.m.dll','''host_dll'',c.m.legacy_dll');
end
% Each generated function retains the actual Simulink construction sequence.
path=fullfile(build,'build_contact_generated.m');fid=fopen(path,'w');fwrite(fid,source);fclose(fid);
addpath(build);clear build_contact_generated;c=build_contact_generated();
c.revision=revision;
end

function c=build_load_gain()
% Separate SOFTWARE model. Existing S-function construction reused verbatim.
root=fileparts(mfilename('fullpath'));build=fullfile(root,'load_gain_work');
source=fileread(fullfile(root,'build_load_speed.m'));
source=strrep(source,'function c=build_load_speed()','function c=build_gain_generated()');
source=strrep(source,'c.root=fileparts(mfilename(''fullpath''))','c.root=fileparts(fileparts(mfilename(''fullpath'')))');
source=strrep(source,'''load_speed_work''','''load_gain_work''');
source=strrep(source,'''dob_rundown_load_speed''','''dob_load_gain_policy''');
source=strrep(source,'load_speed_controller_sfun','load_gain_controller_sfun');
source=strrep(source,'load_speed_plant_sfun','load_speed_contact_plant_sfun');
source=strrep(source,'''Outputs'',''6''','''Outputs'',''12''');
source=strrep(source,'PortWidth(S,0,64)','PortWidth(S,0,80)');
source=strrep(source,'''InputPortWidth'',''64''','''InputPortWidth'',''80''');
source=strrep(source,'[1,.25,.025]','[1,.25,.025,0]');
path=fullfile(build,'build_gain_generated.m');fid=fopen(path,'w');fwrite(fid,source);fclose(fid);
addpath(build);clear build_gain_generated;c=build_gain_generated();
end

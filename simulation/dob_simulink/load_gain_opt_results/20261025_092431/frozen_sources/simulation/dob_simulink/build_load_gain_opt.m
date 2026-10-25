function c=build_load_gain_opt()
root=fileparts(mfilename('fullpath'));build=fullfile(root,'load_gain_opt_work');
source=fileread(fullfile(root,'build_load_gain.m'));
source=strrep(source,'function c=build_load_gain()','function c=build_gain_opt_generated()');
source=strrep(source,'root=fileparts(mfilename(''fullpath''))','root=fileparts(fileparts(mfilename(''fullpath'')))');
source=strrep(source,'''load_gain_work''','''load_gain_opt_work''');
source=strrep(source,'dob_load_gain_policy','dob_load_gain_optimisation');
source=strrep(source,'load_gain_controller_sfun','load_gain_opt_controller_sfun');
source=strrep(source,'build_gain_generated','build_gain_opt_model');
path=fullfile(build,'build_gain_opt_generated.m');fid=fopen(path,'w');fwrite(fid,source);fclose(fid);
addpath(build);clear build_gain_opt_generated;c=build_gain_opt_generated();
end

function c=prepare_real_five()
c.root=fileparts(mfilename('fullpath'));parent=fileparts(c.root);
addpath(parent,fullfile(parent,'empirical'));base=dob_config();
c=base;c.root=fileparts(mfilename('fullpath'));c.base=base;
c.results=fullfile(c.root,'results');c.model='dob_real_five';
c.model_dir=fullfile(c.root,'build');c.events=fullfile(c.root,'data','events.csv');
c.gains=[.15,.25,.5];c.caps_a=[.00625,.0125,.025];c.seeds=1:100;
addpath(c.build,c.root);assert(isfile(c.events),'Export five verified real windows first');
if ~isfolder(c.results),mkdir(c.results);end
if ~isfolder(c.model_dir),mkdir(c.model_dir);end
if bdIsLoaded(c.model),close_system(c.model,0);end
load_system(fullfile(parent,'empirical','build','dob_empirical.slx'));
save_system('dob_empirical',fullfile(c.model_dir,[c.model '.slx']));
if ~bdIsLoaded(c.model),load_system(fullfile(c.model_dir,[c.model '.slx']));end
end

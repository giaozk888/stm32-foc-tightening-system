function [stimulus,plant]=load_speed_contact_inputs(c,name,seed)
% Both revisions receive exactly the same exogenous samples and plant.
if strcmp(name,'contact_cancel')
    [stimulus,plant]=load_speed_inputs(c,'contact_early',seed,1);
    stimulus(:,16)=2; % Independent fixture release80ms after physical contact.
else
    [stimulus,plant]=load_speed_inputs(c,name,seed,1);
end
end

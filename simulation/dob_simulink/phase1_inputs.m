function [stimulus,truth,physical,mapping]=phase1_inputs(c,name,seed)
mapping=[];
if startsWith(name,"real_")
    realc=c;realc.events=fullfile(c.root,'real_five','data','events.csv');
    [stimulus,truth,physical,mapping]=real_five_inputs(realc,extractAfter(name,"real_"),seed);
else
    [stimulus,truth]=dob_scenario(c,name,seed);
    physical=[stimulus(:,1),zeros(size(stimulus,1),1)];
    if name=="step" % Sustained load differs explicitly from the unload case.
        truth(:,2)=c.load_a*double(truth(:,1)>=c.event_s);
    elseif name=="spike" % Isolated Id outlier with NO external load.
        truth(:,2)=0;
    end
end
end

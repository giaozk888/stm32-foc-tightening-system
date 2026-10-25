function plot_load_speed(result_dir)
if nargin<1
    root=fileparts(mfilename('fullpath'));result_dir=strtrim(fileread(fullfile(root,'load_speed_work','latest_results.txt')));
end
folder=fullfile(result_dir,'plot_inputs');if ~isfolder(folder),mkdir(folder);end
for name=["contact_early","unload","source_gap"]
    pair=cell(1,2);
    for enabled=0:1
        files=gunzip(fullfile(result_dir,sprintf('%s_seed001_enabled%d.csv.gz',name,enabled)),folder);
        pair{enabled+1}=readtable(files{1});
    end
    A=pair{1};B=pair{2};f=figure('Visible','off','Color','white','Position',[100 100 1300 1000]);
    tiledlayout(4,1,'TileSpacing','compact');
    nexttile;plot(A.time_s,A.omega_true_rad_s*30/pi,B.time_s,B.omega_true_rad_s*30/pi, ...
        B.time_s,B.selected_target_rpm,'--',B.time_s,B.speed_ref_rpm,':','LineWidth',1.2);
    yline(20,':');grid on;ylabel('rpm');legend('OFF measured','ON measured','ON selected target','ON S-curve','CONTACT20','Location','best');
    title(strrep(name,'_',' '));
    nexttile;plot(B.time_s,B.external_load_a,'k--',B.time_s,B.load_truth_a, ...
        B.time_s,B.dob_estimate_a,B.time_s,B.load_mean_a,'LineWidth',1.1);grid on;ylabel('A equivalent');
    legend('Independent external load','Total physical load','DOB','Classifier mean','Location','best');
    nexttile;plot(A.time_s,A.iq_cmd_a,B.time_s,B.iq_cmd_a,'LineWidth',1.1);yline(.5,':');yline(-.5,':');
    grid on;ylabel('Iq command A');legend('OFF','ON','Location','best');
    nexttile;stairs(A.time_s,A.fsm_state);hold on;stairs(B.time_s,B.fsm_state);stairs(B.time_s,B.schedule_slow*3,':');
    grid on;yticks(0:10);ylabel('FSM state');xlabel('Time s');legend('OFF FSM','ON FSM','ON slow x3','Location','best');
    sgtitle('Software only: same external conditions; current lag and ideal fixture assumed; no real motor validation');
    exportgraphics(f,fullfile(result_dir,char(name+"_comparison.png")),'Resolution',130);close(f);
end
S=readtable(fullfile(result_dir,'metrics_mean_std.csv'));
f=figure('Visible','off','Color','white','Position',[100 100 1200 650]);tiledlayout(1,3);
for k=1:3
    nexttile;
    if k==1,metric='contact_entry_speed_rpm';label='Contact entry speed rpm';
    elseif k==2,metric='done_s';label='Completion time s';else,metric='saturation_ms';label='Current saturation ms';end
    hold on;
    for side=0:1
        group=S(string(S.scenario)=="contact_early"&S.enabled==side,:);
        errorbar(side,group.([metric '_mean']),group.([metric '_std']),'o','LineWidth',1.6);
    end
    xticks([0 1]);xticklabels({'OFF','ON'});xlim([-.5 1.5]);ylabel(label);grid on;
end
sgtitle('Early contact model: mean +/- sample SD,10 paired seeds; inspect slower completion as well as gentler contact');
exportgraphics(f,fullfile(result_dir,'contact_tradeoff_mean_std.png'),'Resolution',140);close(f);
end

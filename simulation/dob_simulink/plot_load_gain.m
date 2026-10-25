function plot_load_gain(result_dir)
% SOFTWARE validation plots, distinct from hardware/load-torque evidence.
folder=fullfile(result_dir,'plot_inputs');if ~isfolder(folder),mkdir(folder);end
for scene=["no_load","step","unload","source_gap","contact_early"]
    f=figure('Visible','off','Color','white','Position',[70 70 1300 1000]);tiledlayout(4,1,'TileSpacing','compact');
    colours=lines(3);variants=["off","fixed","adaptive"];
    for k=1:3
        files=gunzip(fullfile(result_dir,sprintf('%s_seed001_%s.csv.gz',scene,variants(k))),folder);T=readtable(files{1});
        nexttile(1);hold on;plot(T.time_s,T.omega_true_rad_s*30/pi,'Color',colours(k,:),'LineWidth',1.1);
        nexttile(2);hold on;plot(T.time_s,T.gain_selected,'Color',colours(k,:),'LineWidth',1.1);
        nexttile(3);hold on;plot(T.time_s,T.iq_dob_a*1000,'Color',colours(k,:),'LineWidth',1.1);
        nexttile(4);hold on;plot(T.time_s,T.iq_cmd_a,'Color',colours(k,:),'LineWidth',1.1);
    end
    nexttile(1);yline(240,':');ylabel('True model rpm');grid on;legend(variants,'Location','best');title(strrep(scene,'_',' '));
    nexttile(2);yline(.25,':');ylabel('Selected gain');grid on;
    nexttile(3);yline(25,':');yline(-25,':');ylabel('DOB current mA');grid on;
    nexttile(4);yline(.5,':');yline(-.5,':');ylabel('Total Iq command A');xlabel('Time s');grid on;
    sgtitle('SOFTWARE ONLY: paired independent load/noise/plant, fixed speed policy, original PI and caps');
    exportgraphics(f,fullfile(result_dir,char(scene+"_comparison.png")),'Resolution',135);close(f);
end
S=readtable(fullfile(result_dir,'metrics_mean_std.csv'));
f=figure('Visible','off','Color','white','Position',[70 70 1300 580]);tiledlayout(1,3);
for n=1:3
    nexttile;hold on;
    if n==1,scene='step';key='loaded_mae';label='Step tracking MAE rpm';
    elseif n==2,scene='unload';key='unload_peak_rpm';label='Unload overshoot rpm';
    else,scene='no_load';key='compensation_abs_mean_a';label='No-load |comp| mean A';end
    for k=1:3
        g=S(string(S.scene)==scene&string(S.variant)==variants(k),:);
        errorbar(k,g.([key,'_mean']),g.([key,'_std']),'o','LineWidth',1.5);
    end
    ylabel(label);xticks(1:3);xticklabels(variants);xlim([.5 3.5]);grid on;
end
sgtitle('10 paired seeds per group, mean +/- sample SD; all failures retained');
exportgraphics(f,fullfile(result_dir,'gain_mean_std.png'),'Resolution',140);close(f);
end

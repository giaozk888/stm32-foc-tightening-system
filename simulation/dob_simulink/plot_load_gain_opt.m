function plot_load_gain_opt(result_dir)
folder=fullfile(result_dir,'plot_inputs');if ~isfolder(folder),mkdir(folder);end
variants=["fixed","adaptive","fast","floor","combined"];
for scene=["step","unload","no_load","source_gap"]
    f=figure('Visible','off','Color','white','Position',[70 70 1300 1000]);tiledlayout(4,1,'TileSpacing','compact');colours=lines(5);
    for k=1:5
        files=gunzip(fullfile(result_dir,sprintf('%s_seed001_%s.csv.gz',scene,variants(k))),folder);T=readtable(files{1});
        nexttile(1);hold on;plot(T.time_s,T.omega_true_rad_s*30/pi,'Color',colours(k,:),'LineWidth',1.2);
        nexttile(2);hold on;plot(T.time_s,T.gain_selected,'Color',colours(k,:),'LineWidth',1.2);
        nexttile(3);hold on;plot(T.time_s,T.iq_dob_a*1000,'Color',colours(k,:),'LineWidth',1.2);
        nexttile(4);hold on;plot(T.time_s,T.iq_cmd_a,'Color',colours(k,:),'LineWidth',1.2);
    end
    nexttile(1);ylabel('Model rpm');grid on;legend(variants,'Location','best');title(scene);
    nexttile(2);ylabel('Gain');grid on;nexttile(3);ylabel('DOB comp mA');grid on;
    nexttile(4);ylabel('Total Iq A');xlabel('Time s');grid on;
    sgtitle('SOFTWARE ONLY: floor/rise factorial comparison, unchanged controllers and caps');
    exportgraphics(f,fullfile(result_dir,char(scene+"_optimisation.png")),'Resolution',135);close(f);
end
S=readtable(fullfile(result_dir,'metrics_mean_std.csv'));
f=figure('Visible','off','Color','white','Position',[70 70 1350 560]);tiledlayout(1,3);
for n=1:3
    nexttile;hold on;
    if n==1,scene='step';key='loaded_mae';label='Step tracking MAE rpm';
    elseif n==2,scene='unload';key='unload_recovery_ms';label='Unload recovery ms';
    else,scene='no_load';key='compensation_abs_mean_a';label='No-load |comp| A';end
    for k=1:5
        g=S(string(S.scene)==scene&string(S.variant)==variants(k),:);
        errorbar(k,g.([key,'_mean']),g.([key,'_std']),'o','LineWidth',1.5);
    end
    xticks(1:5);xticklabels(variants);xlim([.5 5.5]);ylabel(label);grid on;
end
sgtitle('10 paired seeds per group; mean +/- sample SD; original failures retained');
exportgraphics(f,fullfile(result_dir,'optimisation_mean_std.png'),'Resolution',140);close(f);
end

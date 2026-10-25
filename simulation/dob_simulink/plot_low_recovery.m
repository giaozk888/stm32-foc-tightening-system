function plot_low_recovery(result_dir)
if nargin<1
    root=fileparts(mfilename('fullpath'));result_dir=strtrim(fileread(fullfile(root,'low_recovery_work','latest_results.txt')));
end
scenes=["short60","spike","real_measurement"];
f=figure('Visible','off','Color','white','Position',[50 50 1650 1000]);tiledlayout(3,3,'TileSpacing','compact','Padding','compact');
for k=1:3
    files=gunzip(fullfile(result_dir,char(scenes(k)+"_seed001.csv.gz")),fullfile(result_dir,'plot_inputs'));
    T=readtable(files{1});t=T.time_s;
    nexttile;plot(t,T.omega_true_rad_s*30/pi,'k--','LineWidth',1.2);hold on;
    plot(t,T.omega_meas_rad_s*30/pi,'Color',[.4 .4 .4]);yline(10,':');xlim([2.9 4.1]);grid on;
    ylabel('Prescribed speed (rpm)');title(strrep(scenes(k),'_',' '));
    if k==1,legend('Independent speed','Measurement','10 rpm','Location','best');end
    nexttile;stairs(t,T.baseline_valid,'LineWidth',1.1);hold on;stairs(t,1.4+T.retain200_valid,'LineWidth',1.1);
    xlim([2.9 4.1]);ylim([-.1 2.6]);grid on;yticks([0 1 1.4 2.4]);yticklabels({'0','Baseline valid','0','Fast valid'});
    title('Validity (offset)');
    nexttile;plot(t,T.load_truth_a*1000,'k--','LineWidth',1.3);hold on;
    base=T.baseline_estimate_a;fast=T.retain200_estimate_a;
    base(T.baseline_valid==0)=NaN;fast(T.retain200_valid==0)=NaN;
    plot(t,base*1000,'LineWidth',1.1);plot(t,fast*1000,'LineWidth',1.1);xlim([2.9 4.1]);grid on;
    ylabel('Load (mA equivalent)');title('Only valid estimates shown');
    if k==1,legend('Independent load truth','Baseline','Fast200','Location','best');end
end
sgtitle('Offline estimator-only Simulink test: no feedback to plant; current/speed prescribed; not a real motor performance test');
exportgraphics(f,fullfile(result_dir,'low_recovery_comparison.png'),'Resolution',140);close(f);
end

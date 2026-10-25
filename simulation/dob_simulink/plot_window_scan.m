function plot_window_scan(result_dir)
if nargin<1
    root=fileparts(mfilename('fullpath'));
    result_dir=strtrim(fileread(fullfile(root,'window_scan_work','latest_results.txt')));
end
m=jsondecode(fileread(fullfile(result_dir,'manifest.json')));
scenes=["step","unload","noise","real_measurement"];
f=figure('Visible','off','Color','white','Position',[60 60 1600 1050]);
tiledlayout(4,3,'TileSpacing','compact','Padding','compact');colors=lines(4);
for k=1:numel(scenes)
    paths=gunzip(fullfile(result_dir,char(scenes(k)+"_seed001.csv.gz")),fullfile(result_dir,'plot_inputs'));
    T=readtable(paths{1});t=T.time_s;
    nexttile;plot(t,T.load_ground_truth_a*1000,'k--','LineWidth',1.5);hold on;
    for j=1:4
        w=m.windows_ms(j);plot(t,T.("w"+w+"_mean_a")*1000,'Color',colors(j,:),'LineWidth',1);
    end
    xlim([2.3 6.9]);grid on;ylabel('Load mean (mA equiv)');title(strrep(scenes(k),'_',' '));
    if k==1,legend('Simulator truth','100 ms','75 ms','50 ms','30 ms','Location','best');end
    nexttile;hold on;
    for j=1:4
        w=m.windows_ms(j);plot(t,T.("w"+w+"_filtered_slope_a_s")*1000,'Color',colors(j,:));
    end
    yline(20,'k:');yline(-20,'k:');xlim([2.3 6.9]);grid on;ylabel('Filtered slope (mA/s)');
    nexttile;hold on;
    for j=1:4
        w=m.windows_ms(j);y=T.("w"+w+"_trend");good=T.("w"+w+"_trend_valid");
        stairs(t,4*(j-1)+y,'Color',colors(j,:),'LineWidth',1);
        plot(t(good==0),4*(j-1)+y(good==0),'.','Color',[.7 .7 .7],'MarkerSize',2);
    end
    xlim([2.3 6.9]);ylim([-.2 15.3]);yticks([1 5 9 13]);
    yticklabels({'100 ms','75 ms','50 ms','30 ms'});grid on;title('Trend labels (offset); grey = invalid');
end
sgtitle('Offline actual-C classifier replay: window only; 100 ms slope LPF / 80 ms confirmation unchanged');
exportgraphics(f,fullfile(result_dir,'window_comparison.png'),'Resolution',140);close(f);
end

function plot_load_speed_contact_board(receipt)
row=jsondecode(fileread(receipt));[folder,name]=fileparts(receipt);
T=readtable(fullfile(folder,[name '.trend.csv']));e=row.load_speed_capture.events;
t=([e.timestamp_us]-row.trend_capture.header.start_us)*1e-6;
f=figure('Visible','off','Color','white','Position',[80 80 1250 900]);tiledlayout(3,1,'TileSpacing','compact');
nexttile;plot(T.time_from_run_start_s,T.speed_meas_rpm,'LineWidth',1.2);hold on;
scatter(t,[e.selected_rpm],80,'v','filled');yline(120,':');yline(240,':');
grid on;ylabel('rpm');legend('Recorded speed ~60ms','Retained selected-target events','120','240','Location','best');
title(sprintf('Measured slowdown/recovery; %d retained policy events, %d overwritten; reference not reconstructed',numel(e),row.load_speed_capture.middle_events_overwritten));
nexttile;estimate=T.disturbance_a;average=T.directional_mean_a;
good=strcmpi(string(T.dob_valid),'true')|strcmp(string(T.dob_valid),'1');
class_good=strcmpi(string(T.class_valid),'true')|strcmp(string(T.class_valid),'1');
estimate(~good)=NaN;average(~class_good)=NaN;
plot(T.time_from_run_start_s,estimate*1000,T.time_from_run_start_s,average*1000,'LineWidth',1.1);
grid on;ylabel('mA equivalent');legend('Valid DOB record','Valid classifier mean','Location','best');
nexttile;s=row.samples;stime=[s.elapsed_s];current=zeros(size(stime));
for k=1:numel(s),current(k)=str2double(erase(string(s(k).status.IqRef),'mA'))/1000;end
plot(stime,current,'LineWidth',1.1);hold on;yline(.5,':');yline(-.5,':');grid on;
ylabel('Iq command A');xlabel('Time s (UART timing approximately aligned to START)');
legend('STATUS IqRef','+limit','-limit','Location','best');
sgtitle('One supervised hardware run: manual brake, no synchronized force truth or matched OFF trial');
exportgraphics(f,fullfile(folder,[name '.board.png']),'Resolution',140);close(f);
end

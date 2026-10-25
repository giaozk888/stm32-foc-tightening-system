function plot_load_speed_contact(result_dir)
% Standard MATLAB plots of SOFTWARE traces; no motor performance claim.
folder=fullfile(result_dir,'plot_inputs');if ~isfolder(folder),mkdir(folder);end
for scene=["contact_early","contact_cancel"]
    pair=cell(1,2);
    for k=1:2
        revision=["legacy","candidate"];
        files=gunzip(fullfile(result_dir,sprintf('%s_seed001_%s.csv.gz',scene,revision(k))),folder);
        pair{k}=readtable(files{1});
    end
    A=pair{1};B=pair{2};f=figure('Visible','off','Color','white','Position',[60 60 1250 950]);
    tiledlayout(4,1,'TileSpacing','compact');
    nexttile;plot(A.time_s,A.selected_target_rpm,B.time_s,B.selected_target_rpm,'LineWidth',1.3);
    ylabel('Selected target rpm');legend('V1','V2 contact hold','Location','best');grid on;title(strrep(scene,'_',' '));
    nexttile;plot(A.time_s,A.speed_ref_rpm,B.time_s,B.speed_ref_rpm, ...
        A.time_s,A.omega_true_rad_s*30/pi,':',B.time_s,B.omega_true_rad_s*30/pi,':','LineWidth',1.2);
    ylabel('rpm');legend('V1 ref','V2 ref','V1 plant','V2 plant','Location','best');grid on;
    nexttile;plot(A.time_s,A.iq_cmd_a,B.time_s,B.iq_cmd_a,'LineWidth',1.2);yline(.5,':');
    ylabel('Iq command A');legend('V1','V2','Location','best');grid on;
    nexttile;stairs(A.time_s,A.fsm_state);hold on;stairs(B.time_s,B.fsm_state);
    stairs(B.time_s,B.contact_held*4,':');ylabel('FSM / held x4');xlabel('Time s');grid on;
    legend('V1 FSM','V2 FSM','V2 held','Location','best');
    for ax=findall(f,'Type','axes')',xlim(ax,[3.6 4.8]);end
    sgtitle('Software-only contact seam: same independent fixture and noise; original PI, S-curve and current caps');
    exportgraphics(f,fullfile(result_dir,char(scene+"_boundary.png")),'Resolution',140);close(f);
end
S=readtable(fullfile(result_dir,'contact_summary.csv'));
f=figure('Visible','off','Color','white','Position',[60 60 1150 550]);tiledlayout(1,3);
for k=1:3
    nexttile;hold on;
    if k==1,key='target_raise_on_contact';label='Target jumps on contact entry';
    elseif k==2,key='done_s';label='Early fixture completion s (successful subset)';
    else,key='iq_sat_ms';label='Early fixture saturation ms';end
    for j=1:2
        rev=["legacy","candidate"];g=S(string(S.scene)=="contact_early"&string(S.revision)==rev(j),:);
        errorbar(j,g.([key,'_mean']),g.([key,'_std']),'o','LineWidth',1.5);
    end
    xlim([.5 2.5]);xticks([1 2]);xticklabels({'V1','V2'});ylabel(label);grid on;
end
sgtitle('10 paired seeds; mean +/- sample SD. Boundary repair does not solve late-contact timeouts.');
exportgraphics(f,fullfile(result_dir,'boundary_mean_std.png'),'Resolution',140);close(f);
end

function dob_plot_case(T,path,label)
f=figure('Visible','off','Position',[100 100 1200 900]);g=onCleanup(@()close(f));
tiledlayout(4,1,'TileSpacing','compact');
nexttile;plot(T.time_s,[T.speed_ref_rpm,T.speed_meas_rpm,T.rpm_true]);
ylabel('rpm');legend('reference','measurement LPF','plant truth');title(label,'Interpreter','none');grid on;
nexttile;plot(T.time_s,[T.load_ground_truth_a,T.dob_estimate_a,T.iq_dob_a]);
ylabel('A equivalent');legend('independent true load','DOB estimate','bounded compensation');grid on;
nexttile;plot(T.time_s,[T.iq_cmd_a,T.iq_true_a,T.id_raw_a,T.abs_id_lpf_a]);
ylabel('A');legend('Iq command','actual modeled Iq','raw measured Id','DOB absId LPF');grid on;
nexttile;stairs(T.time_s,[T.dob_valid,T.warmup_s,T.epoch_resets]);
legend('valid','warmup seconds','reset calls');xlabel('time s');grid on;
exportgraphics(f,path,'Resolution',130);
end

function dob_plot_historical(folder)
% Evidence visualization only. NaN truth, missing epochs remain missing.
meta=jsondecode(fileread(fullfile(folder,'historical_metadata.json')));
assert(~meta.ground_truth_available&&~meta.dense_epoch_replay_allowed);
T=readtable(fullfile(folder,'historical_sparse.csv'));
if ismember('timestamp_us',T.Properties.VariableNames)
 t=(T.timestamp_us-T.timestamp_us(1))*1e-6;id=T.id_meas_a;
 filtered=T.abs_id_lpf_a;warmup=T.warmup_s;
else
 t=(T.sample_us-T.sample_us(1))*1e-6;id=T.id_a;
 filtered=NaN(size(t));warmup=NaN(size(t));
end
f=figure('Visible','off','Position',[100 100 1000 650]);g=onCleanup(@()close(f));
tiledlayout(2,1);nexttile;plot(t,id,'.-',t,filtered,'.-');grid on;
ylabel('A');legend('historical raw Id','historical absId LPF');
title('Sparse historical evidence: connecting lines are NOT reconstructed samples');
nexttile;plot(t,warmup,'.-');grid on;ylabel('warmup s');xlabel('relative time s');
exportgraphics(f,fullfile(folder,'historical_sparse.png'),'Resolution',140);
end

function dob_write_report(c,M,S,P,report)
fid=fopen(fullfile(c.results,'RESULTS.md'),'w','n','UTF-8');assert(fid>=0);g=onCleanup(@()fclose(fid));
fprintf(fid,'# DOB Simulink 离线验证实际结果\n\n');
fprintf(fid,'**未访问硬件，未烧录，不能据此宣称真实电机/工件性能已验证。**\n\n');
fprintf(fid,'MATLAB %s；%d 场景配置试验；每配置 %d 个固定噪声 seed。\n\n',version,height(M),report.repeats);
fprintf(fid,'估计阶段门：%s；ON 扫描：%s；固件源文件哈希未改变：%s。\n\n', ...
 string(report.estimator_passed),string(report.on_scan_executed),string(report.firmware_sources_unchanged));
fprintf(fid,'## OFF 估计器（均值 ± 样本标准差）\n\n');
fprintf(fid,'|场景|RMSE mA|有效率 %%|重置次数|检测延迟 ms|卸载估计恢复 ms|\n|---|---:|---:|---:|---:|---:|\n');
R=S(S.gain==0,:);
for k=1:height(R)
 fprintf(fid,'|%s|%.3f ± %.3f|%.2f ± %.2f|%.2f ± %.2f|%.1f ± %.1f|%.1f ± %.1f|\n', ...
 R.scenario(k),1e3*R.mean_estimate_rmse_a(k),1e3*R.std_estimate_rmse_a(k), ...
 100*R.mean_valid_rate(k),100*R.std_valid_rate(k),R.mean_reset_calls(k),R.std_reset_calls(k), ...
 1e3*R.mean_detection_delay_s(k),1e3*R.std_detection_delay_s(k), ...
 1e3*R.mean_estimate_recovery_s(k),1e3*R.std_estimate_recovery_s(k));
end
fprintf(fid,'\nNaN 表示无该事件/未达到，不是 0。RMSE 是有效帧指标；有效率/重置列保留不可用代价。\n\n');
if ~isempty(P)
 fprintf(fid,'## 阶跃/卸载：配对 ON−OFF（均值 ± 标准差）\n\n');
 fprintf(fid,'除有效率外，差值 <0 表示改善，>0 表示恶化。下面所有 seed 的 OFF 与 ON 外部扰动/噪声一致。\n\n');
 Q=P(P.scenario=="step"&abs(P.cap_a-.025)<1e-9,:);
 fprintf(fid,'|增益|速度跌落 Δrpm|负载段 MAE Δrpm|卸载超调 Δrpm|Iq峰值 ΔmA|跌落改善比例|超调恶化比例|\n|---|---:|---:|---:|---:|---:|---:|\n');
 for k=1:height(Q)
  fprintf(fid,'|%.2f|%.4f ± %.4f|%.4f ± %.4f|%.4f ± %.4f|%.3f ± %.3f|%.0f%%|%.0f%%|\n', ...
   Q.gain(k),Q.mean_delta_speed_dip_rpm(k),Q.std_delta_speed_dip_rpm(k), ...
   Q.mean_delta_load_speed_mae_rpm(k),Q.std_delta_load_speed_mae_rpm(k), ...
   Q.mean_delta_unload_overshoot_rpm(k),Q.std_delta_unload_overshoot_rpm(k), ...
   1e3*Q.mean_delta_iq_peak_a(k),1e3*Q.std_delta_iq_peak_a(k), ...
   100*Q.mean_improved_speed_dip_rpm(k),100*Q.mean_worsened_unload_overshoot_rpm(k));
 end
 fprintf(fid,'\n这不是“所有指标都更好”的通过判据。完整 gain/cap/场景比较见 CSV；空载误补偿、有效率、恢复时间与限幅时间必须一起判断。没有自动选优或写回固件参数。\n\n');
end
fprintf(fid,'## 通过 / 未通过与未覆盖\n\n');
fprintf(fid,'- 原 C 正反符号、尖峰 LPF 隔离、持续异常检出/恢复、限幅、STOP、NaN/Inf 回归执行结果：见 native_regressions.json。\n');
fprintf(fid,'- CSV 完整逐点回放一致性见 replay_check.json；实际入口记录而非索引猜测。\n');
fprintf(fid,'- 全部运行 finite=%d、独立补偿限幅=%d、总 Iq 限幅=%d；软件数值守卫故障总数=%d。\n', ...
 all(M.finite),all(M.cap_obeyed),all(M.total_limit_obeyed),sum(M.guard_faults));
fprintf(fid,'- 持续 Id/来源缺口/电压饱和使估计不可用或重新预热是应报告的限制，不因降低有效率而取消门控。\n');
fprintf(fid,'- 不保证大增益更好。卸载超调或空载误补偿恶化时必须保留失败/权衡结果。\n');
fprintf(fid,'- **未覆盖**真实 FOC 电气响应、ADC/PWM/IRQ/过流执行、CPU deadline/WCET、真实负载扭矩与工件拧紧。没有真实平台，本轮不能验证这些项。\n');
fprintf(fid,'- 当前 current tau=1ms 与零速静摩擦是模型假设；重复统计仅覆盖固定 plant 的随机测量噪声，不等于参数/硬件鲁棒性验证。\n');
fprintf(fid,'\n下一步：先扫描执行器时间常数和 J/Kt、B/Kt 不确定性；补足电气/柔性工件模型；获得平台后做独立真值对照。仿真优选不直接升级正式 B。\n');
end

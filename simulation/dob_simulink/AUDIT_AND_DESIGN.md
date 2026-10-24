# DOB 离线审查与 Simulink 验证设计

日期：2026-10-23。仅软件仿真/文件回放；不连接硬件，不修改 A/B 固件默认行为。

## 1. 已审查的实际实现

|功能|实际源文件|结论|
|---|---|---|
|机械辨识/发布|`firmware_common/mechanical_identification.{h,c}`、`tools/mechanical_bidirectional_fit.py`|输入机械 rad/s、rad/s²、dq A；不是绝对 J/B/Kt 标定|
|DOB|`mechanical_dob_shadow.h`、`mechanical_dob_monitor.{h,c}`|2 Hz，机械归一化模型；有效预热为 5/g，约 398 ms|
|质量|`dob_current_admission.h`、`dob_id_pre_lpf_quality.h`|200 mA 相对可信基准跳变先隔离；3 个一致的新水平才接纳最新实际点；不回灌可疑历史点|
|Id 门控|同上/monitor.c|abs(Id) 的 20 ms LPF 连续超过 60 mA 达 20 ms 才失效；这是模型质量门，不是 IdRef 或硬件过流|
|反馈适配|`dob_feedback_candidate.h`|正扰动代表阻碍正转的负载，补偿为 +gain*dhat；独立 ±25 mA/5% 总限幅、0.25 A/s 变化率，再统一总 Iq 限幅|
|速度环|`foc2_app_a/Core/Src/main.c:FOC_EncoderSpeedUpdate`|Kp=.003 A/rpm；Ki=.020 A/(rpm*s)，积分 ±.35 A；SB2 积分卸载/增长整形仍生效，SB3 关闭|
|轨迹/前馈|`speed_scurve.{h,c}`、`speed_accel_feedforward.{h,c}`、`speed_friction_compensation.{h,c}`|200 rpm/s、1000 rpm/s²；Ka=.000046875 A/(rpm/s)；摩擦 FF=.105 A、deadband=2 rpm|
|日志|`pw_log_store.h`、`dob_id_trace.{h,c}`、`mechanical_dob_report.py`|token 日志/有界 RAM 快照；已有 64 ms 间隔瞬时点不是 1 kHz 连续采样|

速度 PI 外环约 1 ms、FOC 50 us。机械速度控制 LPF 为 20 ms；DOB 的 Iq 匹配 LPF 也是 20 ms。正常顺序是：本次同帧 S 曲线 speed/accel → PI 候选积分 → 读取前一已完成 DOB 帧并经过补偿适配 → PI+accel FF+friction+DOB → 总 Iq 限幅 → 新的真实电流/编码器证据 → DOB Observe。仿真保留这一个外环 epoch 的因果延迟，不用本时刻的未来估计量。

AW 使用所有项相加后的 raw/ref，而不是只看 PI。反馈新鲜度 2 ms；短无效保持到 5 ms，淡出到 20 ms；STOP/故障清零。候选 CONTACT20/OBSERVE10：观察下限 10 rpm，新的反馈源仍须 ≥20 rpm；本环境采用该候选质量编译标志。

## 2. Id 尖峰审查结论

当前 V7 代码已经在 LPF **之前**隔离首个可疑点。拒绝点不更新 abs_id_lpf、Iq LPF、Id 计时基准、预热及有效统计。短缺口不硬清空；恢复端点本帧无效且不获得预热时间。超过 10 ms 缺口可恢复重置。持续新水平仍可能在 3 点确认后进入 LPF：跳变筛选不能替代“物理不可能范围”的独立标定，当前没有可靠的绝对原始 Id 上限可凭空加入。

仍可能重置的现有行为：电流/时间/序号来源异常、总 Iq 饱和/电压饱和、持续 Id、低速等。因此有效率不是补偿控制可靠性的充分条件。仿真必须报告这些真实状态，不通过取消门控提高有效率。

## 3. 单位与参数来源

模型：`a*domega/dt = iq - b*omega - Ic*sign(omega) - bias - load_A`。

- omega=mechanical_rpm*2*pi/60；a=J/Kt [A*s²/rad]，b=B/Kt [A*s/rad]。
- 初始 **plant**：a=.000386049，b=.00155158（用户指定正向拟合）；Ic=.11945168237076952 A，bias=.0005496600325149542 A（双向联合辨识）。这是明确的参数组合/模型误差实验，不宣称新标定。
- 固件 **observer** 仍直接引用 C 常量：a=.0003782906586526162，b=.0015676864325576986，Ic/bias 同上。不覆盖固件参数。
- 旧正向截距 .120735 A 是摩擦+偏置之和，不能直接同时当作 Ic 和 bias。Kt 未独立标定，扰动真值/估计均以 A 等效表示，不输出伪 N*m。

## 4. 分层架构与阶段门

1. 审查和本设计先落盘；冻结源文件哈希、实际编译参数及数据契约。
2. `dob_offline.slx` 由 MATLAB builder 可重复生成：独立场景/真值源 → 50 us 电流执行器/机械 plant → 1 ms C 固件控制/DOB → 独立补偿限幅+总 Iq 限幅 → 50 us Unit Delay → plant。所有随机序列预生成，OFF/ON 同 seed 完全相同。
3. C 动态库直接编译原 S-curve、FF、friction、DOB monitor/shadow/admission/feedback 实现。速度 PI 外层编排使用最小主机适配，并自动核验 main.c 的常量/分支；不复制另一套 DOB 算法。主机编译的内存屏障 shim 只用于单线程 x86 构建，绝不写回固件头文件。
4. 先运行 OFF 的估计独立验证及尖峰/持续异常/长短缺口/符号/限幅回归，输出阶段门。估计门失败则禁止该次 suite 的 ON 扫描；不能靠忽略失败继续。
5. 门通过后，仅在主机仿真副本扫描增益与补偿上限（不超过 .025 A 或总限幅 5%）；OFF/ON 重复试验报告均值、标准差及配对差异。
6. 回放只消费明确时间戳、单位、序号及来源元数据的记录；不将稀疏点补成“真实 1 kHz”。历史记录没有负载真值，RMSE/检测延迟记为不可得。完整合成记录可以逐点回放并检查相等。

## 5. 模型边界与验收

本轮是机械层/外环验证：电流执行器为可配置一阶响应（默认 1 ms **假设**），保留 50 us 命令延迟。**没有仿真电气 FOC、ADC 开关波形、SVPWM、硬件保护执行延迟或 CPU WCET**；不能声称因此验证 current PI、CUR_CONFIRM、CURRENT_INVALID、PWM 时序或真实电机性能。电压饱和可注入，但无电压余量模型时不能预测真实电压饱和。安全数值守卫不替代硬件保护。

机械 plant 零速用有界静摩擦平衡防止离散 Coulomb chatter，此零速细节是仿真假设，非实测辨识值。噪声、尖峰只注入测量通道，不改真实机械扰动；负载卸载由独立 ground-truth 源触发。

每场景输出逐点 CSV/PNG、重复试验指标 CSV、均值/标准差、配对 OFF/ON 差异、通过/未通过/不可评估项。有效帧指标和全时域不可用率分开；不以仅选稳定有效点掩盖坏窗口。恢复必须满足连续驻留，未恢复为 NaN/未达到而不是 0。

接口实现参考：[MathWorks S-Function](https://www.mathworks.com/help/simulink/slref/sfunction.html)、[离散采样时间](https://www.mathworks.com/help/simulink/sfg/s-function-concepts.html)。使用本机 R2025b 的 C MEX S-function 接口，无需 Simscape。

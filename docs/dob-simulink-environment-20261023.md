# DOB Simulink 离线验证环境交付记录

## 范围与执行

仅软件模型/已保存文件回放；没有访问调试器、串口或任何电机硬件，没有烧录、START、参数写回或正式 B 提升。原脏工作区修改保留，本轮新增文件位于 `simulation/dob_simulink/`，另新增 `tests/test_dob_simulink_environment.py`。

先写 `AUDIT_AND_DESIGN.md` 审查实际机械辨识、DOB/质量/反馈、速度 PI/S-curve/FF/摩擦/限幅与日志；随后实现原 C 主机桥接和 Simulink 模型，再按估计阶段门开放仿真补偿。没有修改任何既有固件默认值/保护逻辑。

本机实际 MATLAB R2025b 25.2、Simulink、MSVC2022 C MEX 与项目 MinGW GCC 构建通过：

- 原 C 机械 DOB/质量/轨迹/FF/摩擦/反馈 DLL。
- Controller/plant 两个 C MEX S-function、一个直接回放 MEX。
- `simulation/dob_simulink/build/dob_offline.slx`。

`build/source_manifest.json` 保存实际源内容哈希、主机编译 flags；完整运行结束核验所有已捕获源文件无变化，包括既有 A/B main 与 CMake 配置、共用保护代码和本轮控制桥接。后续语义归约仅将无事件的空载恢复指标规范为 N/A；原始统计和归约哈希另存 `results/analysis_provenance.json`，不修改任何动态算法。

## 仿真模型

`a*domega/dt = iq - b*omega - Ic*sign(omega) - bias - load_A`。

- Plant 初值：a=0.000386049 A·s²/rad、b=0.00155158 A·s/rad；Ic=0.11945168237076952 A、bias=0.0005496600325149542 A。
- Observer：直接使用当前 C 双向联合模型，a=0.0003782906586526162、b=0.0015676864325576986；不覆盖固件常量。
- speed controller 用 rpm；模型/DOB 使用机械 rad/s；Ka=0.000046875 A/(rpm/s)，摩擦前馈0.105 A。
- 控制1 ms、机械/current-lag plant50 us、单PWM周期命令延迟50 us。
- current tau=1 ms 和零速摩擦平衡是明确的**建模假设**。未模拟真实电气 FOC/ADC/硬件保护、BEMF电压裕量、IRQ/WCET/CCR时序，未建立实际工件接触模型。
- 真实负载由独立外部源生成并单独记录；不用 DOB 输出作真值。扰动为 A 等效，没有伪造绝对 J/B/Kt 或 N·m。

## 实际验证结果

完整执行 11 个场景标签 × 每配置5个 seed：55组 OFF 估计 + 440组 ON 增益/限幅扫描 = **495组**。`step`/`unload` 是同一个突加—保持—卸载协议的两种关注标签，不当成独立物理证据。

估计阶段门通过才运行 ON。增益0/.15/.25/.5/1，独立补偿上限.0125/.025 A，总 Iq ±.50 A，既有 PI、S-curve、Ka、摩擦及模型门控未调参。

- 原 C MATLAB 主机契约18项通过；新增 Python DLL/快照/来源检查5项通过；既有相关离线测试60项通过（S-curve/AW/accelerationFF/friction/SB2/DOB反馈45，pre-LPF7，normal4，CONTACT20/OBSERVE10四项）。合计83项相关回归/契约检查，不冒称全仓库所有测试。
- 独立文件审计：495组、**440个同 seed OFF/ON 配对**的实际消费输入哈希一致；NaN/Inf、补偿/总电流/积分限幅、隔离点LPF不变检查通过。
- 完整合成CSV逐点C回放：最大差5.0022e-12，状态/计数严格一致。
- 历史72点 Id记录经过原ELF/BIN/Flash/RAM来源验证后导出/绘图；这是历史稀疏证据，真值缺失，未伪装成新1kHz实测。

五种子阶跃估计 RMSE **6.369 ±0.031 mA**；平均偏差约−0.399 mA；半幅检测延迟**79.0 ±0.7 ms**；卸载估计恢复**148.4 ±2.7 ms**。这些均为本模型软件结果。

增益.25、补偿上限.025 A，五种子阶跃均值：

|指标|OFF|ON .25|变化|
|---|---:|---:|---:|
|负载段平均绝对跟踪误差 rpm|1.2733|0.9678|改善约24.0%|
|速度跌落 rpm|18.7466|18.3753|改善约0.3712 rpm|
|卸载超调 rpm|14.9889|14.8952|改善约0.0937 rpm|
|Iq命令峰值 A|0.212593|0.214056|增加约1.462 mA|

代价不能隐藏：总命令峰值增加、空载补偿从0变为小非零值；更高增益并非所有指标都更好。gain1的卸载超调配对略增加约0.0002 rpm，软件统计可重复但不据此推断物理显著性。不自动选优或改正式参数。

## 审查确认的质量/重置边界

- 原始+700 mA单点在 DOB LPF之前隔离，不硬重置，实际有效率99.96%，不是“强行100%”。
- 持续90 mA Id进入既有60 mA滤波值/20 ms持续门控，重置1次并恢复预热；有效率约85.54%。
- 现有来源质量失败路径逐失败epoch重置：3ms来源缺失重置3次，30ms缺失/电压饱和重置30次。这与短暂尖峰隔离路径不同，是后续可审查的重复重置问题；本轮保留默认行为，没有通过取消检查提升有效率。
- “预热”原字段是observer.elapsed_s，有效后仍累加。补充表单列显式WARMUP状态累计时间，不能把约6s末值误当成预热用了6s。

## 交付与重现

入口：`simulation/dob_simulink/run_dob_simulink_suite.m`。MATLAB添加该目录后运行 `run_dob_simulink_suite('full')`；细节见该目录README。

最终文件：

- `results/RESULTS.md`：通过/未覆盖、估计和配对对比。
- `metrics_per_trial.csv`、`metrics_mean_std.csv`、`paired_on_minus_off.csv`：逐次、均值/样本标准差、同seed配对差异与改善/恶化比例。
- `metrics_supplement.csv`：独立补偿限幅时间、plant实际Iq峰值、显式预热状态时间。
- 每组CSV及PNG：真值、实际输入、控制器、DOB、LPF、复位/预热。
- `report.json`、`native_regressions.json`、`estimator_gate.json`、`replay_check.json`、`independent_files_audit.json`。

原始完整日志：`tmp/dob-simulink-full.log`；正式统计语义归约：`tmp/dob-simulink-final-report.log`。开发中发现过记录盘空间关闭及From Workspace边界索引回放偏差，最终以实际入口记录和独立审计解决；早期差异文件归档到tmp，不混入最终通过证据。

下一步先扫描机械参数/电流执行器时常不确定性，补足电气及柔性/工件模型和更完整测量回放；获得真实平台后才能进行独立真值验证。**本轮不能宣称真实电机性能、实际拧紧质量或硬件保护时序已经验证。**

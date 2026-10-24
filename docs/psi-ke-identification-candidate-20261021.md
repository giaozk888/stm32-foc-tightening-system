# ψf/Ke 稳态dq辨识候选 A

仅新增独立diagnostic，不刷板、不启动电机、不连接板端，不修改正式B或启动选择。
当前没有新ψf/Ke实测值；本文件是实现、离线验证与人工板测准备。

## 公式、来源和局限

沿用当前candidate A参数，不自动切到厂家参数：

- `CURRENT_PI_CANDIDATE_RS_OHM=0.78` Ω。
- `CURRENT_PI_CANDIDATE_LD_H=20.03e-6` H。
- `pole_pairs=10`，当前PI、速度PI、S-curve、Acceleration FF及0.105 A摩擦补偿均不变。
- 当前dq交叉解耦为OFF，保持OFF；已有BEMF前馈亦为OFF，辨识结果不自动接入。

```
omega_e = pole_pairs * mechanical_rpm * 2*pi/60       [electrical rad/s]
Vq_resistive = Rs * Iq                              [V]
Vq_cross = omega_e * Ld * Id                        [V]
bemf_est = Vq - Vq_resistive - Vq_cross              [V]
psi_f_est = bemf_est / omega_e                      [Wb]
```

稳态dq模型依据[Microchip PMSM dq电压方程](https://microchiptech.github.io/mcaf-doc/6.0.2/algorithms/foc/introduction.html#pmsm-voltage-equations)。
此处忽略稳态下的`Lq*dIq/dt`。默认最小有效机械速度50 rpm，即10极对时约52.36 electrical rad/s。
低于门限、非有限输入、重复/不新鲜ADC帧、CURRENT_VALIDATOR非normal、CUR_CONFIRM未clear、
速度/参考尚未稳定或电压饱和均不进入估计统计；这些是估计器准入，不改变运行保护。

**当前Vq来自PI后、原统一矢量限幅后的PWM电压命令，不是外部仪器测量的相端电压。**
原一拍pipeline、latch、采样完全未改；只在参考/速度稳定的平台取固定平均窗口，
不把瞬时同帧Vq解释成采样时已经施加的电压。PWM死区、母线标定和功率器件压降仍可产生偏差。
Rs/Ld仍是此前未资格化的假设，尤其Rs误差可能随Iq/转速变化影响拟合斜率。
因此结果明确标记为`COMMAND_VOLTAGE`等效candidate，`qualified_physical_flux=false`，
即使R²较高也不能冒充开路线间反电动势测量或自动成为正式参数。

## 实时与记录结构

无需新增ADC ISR插桩：复用已有`bemf_frame`的同一accepted PI帧，任务层短暂复制52 B，
从该帧的有符号omega_e反算它代表的mechanical_rpm，保持原编码器单位/方向来源；
不是用speed target代替measured speed，也不是独立验证极对数。
`FOC_CurrentLoopStep`、速度更新、PI/PWM/IRQ/保护主体预处理代码与原A逐函数相同。
所有ψf除法、Welford均值/方差、日志在任务层执行，不在20 kHz ISR执行。
source timestamp保持附着原ADC seq；稳定/窗口进度独立使用任务观察时钟，拒绝帧不会冻结窗口时钟。

独立模式只接受本地`MOTOR TEST PSI RUN 100/200/300/400`显式请求。
普通UART START不会变成辨识动作，也不会执行正常tightening；STOP仍立即调用原关断路径。
每boot至多一个点，保留原ClSession单次准入/功率使能事务、NO_ROTATION、行程及12秒lease。
不自行写CCR、SD、MOE/AOE，不清故障、不重试、不改IRQ优先级。

每点先要求参考到达、accel_ref=0、实测速度处于`max(2 rpm,5% target)`内持续500 ms，
再固定采2秒窗口，每50 ms一个任务观察，通常41帧；至少38有效帧，拒绝比例不超过5%。
超时未完成窗口只能QUALITY_FAILED，不能靠不足2秒的样本提前PASS。
每点最多5秒驱动，之后原S-curve减速，最晚7秒结束；原独立12秒lease不变。
采集质量失败可以记录后继续下一独立点；任一保护、关断/身份/时序证据异常立即停止整批。

每帧四个同index的tokenized日志，20 Hz，实际32 B codec验证无截断：

| 行 | 字段 |
|---|---|
| PSI R | index、ADC seq、source timestamp us、mechanical_rpm、omega_e_rad_s |
| PSI I | index、Id、Iq、Vd、Vq |
| PSI E | index、Rs*Iq、omega_e*Ld*Id、bemf_est、psi_f_est |
| PSI S | index、quality、voltage_saturation、fault flags、diagnostic stage |

R/I/E/S严格按同index合并，禁止按接近的串口接收时间拼接。
任务统计使用有效帧，不用拒绝样本替换原值。最终结果保存在168 B `psi_ident`，
含平均rpm、Id/Iq、Vq、bemf、ψf、omega_e、Vd和ψf的Welford M2/样本数。
最终`MOTOR TEST PSI RESULT`只在producer停止后读取不可变聚合，避免任务半更新撕裂。
主机完整停机RAM再解码并核对实际ELF；标准差按样本SD `sqrt(M2/(n-1))`。
串口窗口覆盖度单独报告，缺失/部分帧不填0，不能声称日志全速率或完整无缺。

## 一次批次与有效转速

预设`PsiKeIdentificationDiagnostic`继承当前`BemfFeedforwardCandidate`，诊断开关默认OFF。
新增`tools/psi_ke_board.py`默认只核验文件/输出计划，不连接设备。

| 请求转速 rpm | 当前处理 | 原因 |
|---:|---|---|
| 100 | 计划一次 | 原API允许范围内 |
| 200 | 计划一次 | 原API允许范围内 |
| 300 | SKIPPED | 原API上限250 rpm，且达到原300 rpm独立超速边界 |
| 400 | SKIPPED | 超过原API和超速边界 |

不偷偷把300/400钳成250后冒充该转速已测。固件直接RUN 300/400同样返回SKIPPED，不消耗一次准入。
当前批次只执行100→200，各一次；点间输出关闭/抓停/完整Flash和RAM保存、核验无保护，
再复位同一确认A重新校准/预检，不刷下一个镜像、不改B应用或slot算法。
一轮人工授权覆盖整个固定批次，不要求每档重新点击；任何保护失败后不自动恢复/补跑。
若100或200的稳态窗口不合格，保留失败点，不用它参与正式多点拟合，也不自动重测。

## 拟合与单位

主机用各合格稳态点的`mean_bemf`与`mean_omega_e`做带截距普通最小二乘：

```
mean_bemf = psi_f_fit * mean_omega_e + offset
```

输出ψf_fit[Wb]、offset[V]、R²、残差RMS、自由度、各点均值/标准差和质量标记。
最终candidate优先采用此斜率，不用某个瞬时或单点ψf直接标定。
模型Rs/Ld/极对数不一致的数据禁止混拟合；少于两个独立有效转速不给candidate。
当前只允许100/200两个点：若都通过可得到代数斜率/截距，但残差自由度为0，
两点R²=1不是独立验证，报告明确`TWO_POINTS_ZERO_RESIDUAL_DOF`。
不为增加拟合点而提高保护或擅自增加新转速。非正磁链保留数值但显式警告，禁止自动采用。

Ke只附加输出一种定义：

```
Ke_phase_peak = pole_pairs * psi_f_fit
单位：相对中性点、峰值 V/(机械 rad/s)
```

不混用机械/电角速度、rpm/krpm、RMS/peak、线间/相值。
结果保存在批次JSON的`analysis.candidate`；独立`psi_ke_report.py --batch ... --output ...`
可以另存candidate报告。没有KVS、PI、前馈系数或B固件写入接口。

## 修改文件

- `firmware_common/psi_ke_identification.h/.c`：模型、窗口准入、统计、质量/停止状态。
- `firmware_common/psi_ke_identification_log.cc`：任务层压缩日志。
- `firmware_common/psi_ke_identification_binding.inc`：独立Task及显式命令。
- `firmware_common/latest_original_fsm.inc`、`protected_closed_loop.inc`：仅诊断宏内的原准入/命令适配。
- `foc2_app_a/Core/Src/main.c`、`CMakeLists.txt`、`CMakePresets.json`：A-only条件编译。
- `tools/psi_ke_board.py`、`psi_ke_report.py`：受监督批次、精确镜像/停机证据与离线拟合。
- `tests/psi_ke_identification_host.c`、`psi_ke_log_host.cc`、`test_psi_ke_identification.py`：回归。

## 构建和测试

| 构建 | Flash B | 静态RAM B | 状态 |
|---|---:|---:|---|
| A `PsiKeIdentificationDiagnostic` | 215860 | 129408 | PASS |
| A `PsiNormalBaseline`（诊断OFF） | 219132 | 129440 | PASS，与原BemfFeedforwardCandidate BIN逐字节一致 |
| B `BemfBUnchanged`（已有tokenized配置隔离重编译） | 210540 | 128792 | PASS，不替换正式B |

13条原unused/RWX警告类别不变，没有新增警告类别或未解决编译错误。
诊断A BIN SHA256=`a260cc660b1c6bedaf8bc098c31e53505fd1c7fdd11595a9a1b95d985d186859`。
精确ELF SHA256=`76fb625066eb9520500d69a21d68f18de9f37ed9ab8e18944186fbafee37647d`。
正常A BIN SHA256仍为`fbf2000cb8b343add0a889ae05600b188af61fb89efb90afb45378f6e74554e5`。
原保存B文件SHA256仍为`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
B隔离重构建SHA仍为`174ebaa1dd2580222cf5a48bb331b03eb06c1247cb2cd44c0e40b7cef57bfe5b`。
这些保存文件不能混同板上B payload；本轮未连接硬件，未改变板上启动元数据。

新增14项回归及104项相关既有回归通过（合计118，非全仓库全量测试），日志：
`tmp/psi-tests.log`、`tmp/psi-regression.log`；构建日志`tmp/psi-build-{a,normal,b}.log`。
包括真实C模型正反符号/近零/非有限、固定窗口/提前结束/质量拒绝、已结束不可覆盖、
真实本地命令所有busy/输出阻挡、正常START拒绝、限速跳过、一boot只准入一次、
多点斜率/截距/Ke单位、两点自由度、失败点保留、混模型/坏数据拒绝、精确同index日志、
32 B真实token codec、FOC/速度/保护/pipeline/IRQ冻结、默认files-only和批次故障停止。

## 人工板测步骤（本轮未执行）

1. 人工确认12 V关闭、MCU供电，**解除锁轴、脱开负载、空载固定并保留防护**；
   保持U/V/W和IU→PA0、IV→PA1、PC6→CTRL_SD原接法、电源12 V/限流0.5 A，
   操作者整组全程在现场、可立即断电。不是之前锁轴Rs/L测试。
2. 按新镜像固定SHA，在12 V关闭时仅暂存非活动A、两次完整回读、保留原B。
3. 人工确认开启12 V且无报警后，只执行一个受监督批次；先校准/原时序预检，
   通过才发一次`MOTOR TEST PSI RUN 100`，关断核验/抓停/保存后再重新校准执行200。
   300/400只记录SKIPPED，无运动命令，无保护恢复重试。
4. 预检/每点停机快照核对50 us deadline、CCR late、实际margin、encoder和CUR_CONFIRM。
   新候选未板测，不能把旧版33 us耗时当成本版时序验收。
5. 整组结束、输出关闭/MCU停住后，提示人工关闭12 V，再恢复原B启动选择，停在入口。
   输出candidate拟合和各点数据；保持前馈OFF，待人工审核，不自动采用结果。

命令（本轮仅files-only默认入口已运行）：

```
python tools/psi_ke_board.py
python tools/psi_ke_report.py
```

未来明确授权后的分离入口：

```
python tools/psi_ke_board.py --stage-off --drive-off-unlocked-no-load-fixed
python tools/psi_ke_board.py --execute-batch <stage.json> --operator-present-whole-batch-drive-on-no-alarm-05a
python tools/psi_ke_board.py --restore-b-drive-off <batch.json> --drive-off-unlocked-no-load-fixed
```

只有真实现场条件符合时才能声明相应标志，不能把预填标志当现场测量。
默认基于上次完整核验的B932回执准备；若实际板端状态有变化，严格比较会拒绝，
应先只读核对，不绕过比较、改SHA或强行确认。

ψf/Ke 参数辨识候选已就绪，等待人工板测。

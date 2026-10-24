# Ld/Lq：Rs 准入策略适配与六段重复诊断

## 范围

独立 A preset `MotorParameterIdentificationLAdmissionDiagnostic`，新增开关
`FOC_IDENT_L_RS_ADMISSION_ENABLE` 默认 OFF。只适配辨识样本准入，不改运行时
TWO_SAMPLE、CUR_CONFIRM、PI、SVPWM、PWM pipeline、IRQ、硬保护或 B。

- 软件 owner 时间差：L 轴由45–55 us改为45–100 us，和当前Rs一致。
- ±0.20 A是估计器样本包络：越界样本拒绝、计数，不进入32帧估计窗口；
  总数及连续数不再单独终止，8位连续统计仍饱和255。
- 可解释hold缺样：每次最多2对，seq与hold增量一致，45–55 us/seq；
  累计只计数，不插值、不补样、不延长测试。
- Ld/Lq仍是50→100 mA，100 ms预偏置、104 ms固定总时限，99.8 ms后记录32对。
- 原0.20 V诊断退出、2 rpm退出、非有限量退出、session/encoder/current/timing等
  独立保护保持。0.10°位移退出沿用此前Rs镜像的OFF设置，不是新取消。
- 新旧诊断同为1740 B ABI；没有新增RAM结构或减栈/heap。

## 固定实验计划

操作员确认锁轴、夹具、防护、12 V/0.5 A并全程在场后：

LD1 → LQ1 → LD2 → LQ2 → LD3 → LQ3。

每段单次boot、重新校准/预检、一次命令、终止后先关断再读日志、保存Flash/RAM。
段间MCU停住且输出关闭至少1秒。质量未通过保留并继续下一个**预定段**；
无未知ACK重发、无故障clear重启捷径、无自动升流。

真正保护、编码器故障、deadline miss/CCR late、未证实关断、传输或镜像异常，
必须中止剩余段。不要把“批量完成”理解为忽略这些故障。

## 参数有效性

Rs=0.78 Ω是用户选择的临时假设，并非已合格电阻标定。
即使获得条件电感，也明确保留此依赖，不写PI/NVM。

电感动态模型还要求独立的PWM生效/采样aperture对齐证据。没有该证据时
`latch_evidence.verified=false`，输出TIMING_UNQUALIFIED、Ld/Lq=null。
软件100 us准入不是将100 us假装成物理50 us；host电感拟合仍要求32帧连续、
seq逐1、45–55 us相邻时间差和正确pending source，不插值绕过。
因此“采集DONE”与“参数有效”完全分开。禁止填一个猜测latch fraction来出数。

## 构建与离线

|构建|Flash|RAM|结果|
|---|---:|---:|---|
|新A诊断|215156 B|130912/131008 B|通过，RAM剩96 B|
|B FrictionBUnchanged|228300 B|128792 B|通过，BIN哈希未变|

A BIN `13b237a70625218bfddb8924b13022a95410b1313f14547238036de2f9e5c786`。
A ELF `08f4fe731598162155fd34cb4432a208d5e6cd5a40dabde2c68185c152b06ea0`。
B BIN `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
构建仍有既有unused/RWX warnings，不能称零warning。

104项motor-ident相关host测试通过（不是整个仓库测试）。包括实际57 us失败重放、
两轴300次拒绝不入估计、解释缺样/拒绝不明缺样、固定104ms时限、原保护退出、
正式控制函数冻结、旧策略/旧镜像不被静默升级、六段质量失败仍记录完成和真实保护停止。

构建日志 `tmp/motor-ident-l-admission-build.log`、
`tmp/motor-ident-l-b-verify-build.log`；回归日志
`tmp/motor-ident-l-repeat-regression.log`。

阶段脚本 `tools/motor_ident_l_repeat_batch.py`，默认仅离线文件核验，不连接设备。
本次baseline是关断且停在入口的原B864，原A长度215132 B。
刷写仅非活动A，完整回读后另一次独立回读，B/boot/config不变；上电需单独确认。

## 本次实测：六段均采集完成

stage：`tmp/motor-ident-l-repeat-stage-1792559713701929200.json`，
批次：`tmp/motor-ident-l-repeat-batch-1792559788606362800.json`。
六个子收据保存各段完整UART、Flash、RAM及原保护证据。

所有段都是固件DONE/REASON=0、32帧；没有因质量失败跳过后续段。
采集完成不表示电感拟合通过：六段均缺少独立sample/bottom/latch对齐证据，
`TIMING_UNQUALIFIED`，Ld/Lq保持null。没有改PI，没有把临时0.78 Ω标为已合格Rs。

|段|轴/次数|窗口平均轴电流 mA|平均轴电压命令 mV|窗口32帧连续|全段拒绝/解释hold对数|
|---|---|---:|---:|---|---|
|1|Ld/1|59.261|44.727|是，49–51 us|45 / 5|
|2|Lq/1|59.693|57.352|否，有100 us间隔|41 / 4|
|3|Ld/2|61.566|49.262|否，有100 us间隔|37 / 9|
|4|Lq/2|61.014|52.732|是，49–50 us|34 / 7|
|5|Ld/3|59.121|45.291|是，50 us|45 / 8|
|6|Lq/3|62.198|52.555|是，49–51 us|49 / 11|

表中是阶跃前后约1.55ms窗口的均值，不是100mA平台的稳态电流或Rs测量。
记录前后有拒绝不等于32帧窗口一定缺样，分别检查原seq；第2/3段窗口不连续，
不能用于当前连续RL估计器。其余4段保留以待对齐证据和模型噪声检查，并非已通过拟合。
Vdq为控制器命令，不是独立物理相电压测量。

全组原保护/时序：最大FOC wall **36.782 us**，deadline miss **0**，
实际CCR late **0**，最小actual margin **12.459 us**。
六段encoder timeout/dma error/schedule miss/control stale均为0；无独立保护触发。
结束输出已关闭、CPU停住；用户确认12 V关闭后，仅按原bootloader流程恢复B，
不运行B应用、不再注入电流。

恢复收据：`tmp/motor-ident-l-repeat-restore-1792559974775747900.json`。

下一步不是继续重复同一实验或放宽拟合：应核验本镜像TIM1双端UEV/RCR=0、
CCR preload、TRGO2/ADC aperture与入口commit实际生效的关系，再确定适用的
离线电压延迟模型。当前只读记录尚不能独立证明电压生效与物理采样对齐，不能填猜测fraction。

补充核验见 `docs/ld-lq-alignment-audit-20261021.md`：已经推导数字加载关系，
并在不伪造时序验证字段的前提下做离线理想模型残差检查。
4段连续窗口的最小预测RMS仍为16.58–33.65mA，超过原5mA门限；
因此“不可信”并非仅因缺一个latch verified标志。

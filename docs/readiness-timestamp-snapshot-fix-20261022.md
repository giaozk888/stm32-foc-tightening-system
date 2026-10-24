# 启动准入时间戳竞态修复（仅新候选 A）

## 故障证据与结论边界

来源 `tmp/mechanical-ident-run-1792674046856577300.json`：三次500rpm完成后，首个600rpm请求返回 `7809 ERR MECH NOT_READY`，未获得运动准入。此前 SELFTEST READY=1，STATUS IDLE、BUSY=0、FLT=0、CTRL=0.1rpm；这不能证明命令执行瞬间全部准入条件仍为真。

原 `ProtectedLoop_Ready` 的实际已测 ELF（MechanicalOuterCompletionCandidate）反汇编证明：先调用 `AS5047P_DmaNowUs`，随后加载 `cl_last_us`，再执行无符号减法并与100比较。FreeRTOS临界区BASEPRI屏蔽优先级5及以下，而ADC为优先级2，可以在两次读取之间抢占。ADC会更新 `cl_last_us`，由此存在“旧now减新reference”回绕误拒绝。

例如：task读now=1000，ADC抢占并发布last=1005，task回来得到 `(uint32_t)(1000-1005)=4294967291 > 100`。这是可复现的代码竞态，但旧固件没有逐条件失败锁存，不能倒推该次NOT_READY必由它触发，也不能排除命令瞬间其他门禁不满足。

## 修复及隔离

新预设 `MechanicalReadinessSnapshotCandidate` 继承当前 `MechanicalOuterCompletionCandidate`，仅开启默认OFF的 `FOC_READY_TIMESTAMP_SNAPSHOT`。普通A、旧候选和B保持原表达式及原行为。

新准入时间检查顺序：

1. 通过volatile 32位读取保存ADC发布的reference。
2. DMB保证读顺序。
3. 读取当前TIM2微秒时间。
4. 对同一个保存的reference计算age，仍要求 `age <= 100us`。

ADC随后更新共享时间戳，不会改变本次已保存的reference。若task确实被延迟导致保存的reference过期，仍保守拒绝；没有自动重采、自动重试或把负差值钳为零。32位TIM2正常回绕按无符号差处理。

不增加PRIMASK/BASEPRI屏蔽，不改IRQ优先级，不向ISR增加工作或printf，不修改任何运行时保护、PI、S-curve、FF、相序、角度、采样、PWM pipeline、2ms/2.5ms看门狗或100us门限。原实际功率启动入口与最后准入复核保持不变。

## 具体失败原因锁存

新增只读UART命令 `MOTOR TEST MECH READY`，示例：

```
OK MECH READY FIX=1 VALID=1 FAIL=0x00020000 CLOCK=1 ADC=899 NOW=1000 AGE=101 RPM=600 ATTEMPT=4
```

- `VALID=0`：本次boot尚未有拒绝记录。
- `FAIL`：实际请求的首个失败条件，保留原 `&&` 短路顺序；**不是对所有门禁做同一时刻的完整扫描**。
- `CLOCK=1`才表示执行过时间差判断；早于该判断被拒绝时为0，不把零值冒充有效时间戳。
- `ADC/NOW/AGE`：本次实际参与判断的时间戳及差值，不在打印时重新计算。
- `RPM/ATTEMPT`：被拒绝的档位与本次boot的请求序号。
- 后续普通ready检查、成功请求和只读查询不会覆盖上次拒绝快照；新的失败请求会替换它。
- 原 `ERR MECH NOT_READY` 回复和成功排队回复不变，不新增自动启动/清故障/重试路径。

位定义（从0起）：0 session state；1 session used；2 armed；3 pending request；4 ADC fault；5 FOC fault；6 zero；7 firmware update；8 boot confirmation；9 UART；10 PWM neutral/timing；11 FOC work；12 outer work；13 encoder periodic；14 current protection；15 timer/IRQ健康；16 output gate状态；17 ADC age；18 encoder valid；19 idle speed finite且≤2rpm；20 motor mode；21 tightening busy；22 START pending；23 STOP pending；24 mechanical session used；25 friction enable；26 SD；27 MOE/AOE；28 CCER。定义见 `firmware_common/protected_readiness.h`。

## 离线验证与构建

- 新增 `tests/test_readiness_snapshot.py`：在-Os/-O2下编译执行实际预处理准入/命令函数，复现旧竞态并验证新路径；覆盖0/100/101us、计时器回绕、ISR更新时仍拒绝真正过期reference、全部准入条件、拒绝不排队、不使能输出、拒绝快照不被后续ready覆盖、UART查询。
- 实际ARM反汇编确认：先 `ldr r4,[r2]` 保存reference，再 `dmb sy`，再调用时钟函数，最后 `subs r2,r0,r4`，仍比较100。
- 逐函数比较：FOC、encoder控制、TaskService、ADC/guard IRQ、fault capture、PWM、原admit、power enable/disable、setpoint与测试owner不变；ADC/encoder/zero/FSM/S-curve/机械估计/前馈对象与上一候选逐字节相同。
- 两个既有dq静态测试原先对未预处理的互斥条件分支直接数大括号而报IndexError；仅将测试输入改为实际预处理FOC函数，保持补偿先于限幅/逆Park的断言，不改控制代码。
- A/B构建成功；与旧候选比较main编译warning集合不增加，既有unused/RWX warning保留，不声称原工程零warning。
- 最终相关离线回归 **219项全部通过**，耗时130.404s，记录 `tmp/readiness-snapshot-regressions-final.log`。覆盖新快照5项及既有encoder、outer、protected loop、mechanical、speed、dq/BEMF、PWM、FSM回归；不是声称仓库所有其他项目的全部测试都已执行。
- 新A BIN：209656B，RAM129544/131008B，余1464B；未缩减heap或线程栈。
- 新A BIN SHA256：`abffd548ede6d1b9b635d4ce170554b728cb44f6ba9425f4db43124b00ca5706`。
- 新A ELF SHA256：`38e59b25fc650d602e1091c7dab7298feff8b8f8e9c8d6f34d3729c590a89299`。
- B复编BIN SHA256仍为 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，原已测A镜像未覆盖。

## 人工后续验证

本轮未调用串口、SWD、复位或刷写工具，未启动电机，不改变板端B选择。只生成独立候选构建。

下一轮需以新镜像身份准备诊断A、核验回读并保留B回退，不能复用旧镜像的stage收据或假称旧板端已装入此修复。经现场条件与实际上电确认后，先校准和功率关闭预检，再仅做一次原条件600rpm测试；若再NOT_READY，在任何复位前查询 `MOTOR TEST MECH READY` 并保存实际拒绝位及时间戳。任何真实保护仍停止，不自动重试或提高门限。

## 后续人工授权补测批次

用户随后要求一次完成验证，并重新确认12V关闭、MCU供电、转轴解锁、空载固定防护、接线和0.5A限流不变、可全程在场。批次按上轮实际未完成项目准备600/700/800rpm各3次，共9轮；不把上轮已完成的500rpm三轮伪称为本次新版本结果。

- 新脚本 `tools/readiness_snapshot_batch.py` 固定新BIN/ELF身份，先按旧身份核验真实1031代B恢复链，再安装新身份，不重解释旧收据。默认仅检查文件，不访问硬件。
- RUN前只读查询 `MOTOR TEST MECH READY` 核验FIX=1。只有明确 `ERR MECH NOT_READY` 才在STOP清理前查询实际拒绝快照；ACK不明/传输失败直接进入原STOP/输出关断清理，不延迟关断取证、不重发RUN。
- 完整RAM保存后，同时解码本次匹配ELF的outer trace、上次准入检查和最近拒绝锁存，保留时间戳与第一失败条件语义。
- 新批次及原runner相关27项离线测试全部通过，`tmp/readiness-batch-regressions.log`。
- 断电暂存收据 `tmp/mechanical-ident-stage-1792675766204211500.json` PASS，两次完整回读通过；仅A编程，B/boot/private/config未变。activation=false、motor_commands=0、输出关闭、CPU halted。
- 当前仅提示用户开启12V并确认无报警/全程可立即断电；没有据此自动推断已上电，也没有开始九轮运动。

用户随后明确确认上电条件，九轮已实际全部完成；批次 `tmp/mechanical-ident-batch-1792675998078677600.json` PASS。九轮无NOT_READY、无保护、deadline miss/CCR late为0，具体稳态、时间戳、归一化模型及限制见 `docs/readiness-snapshot-nine-results-20261022.md`。这条后续结果不追溯改变上面断电暂存阶段的状态。

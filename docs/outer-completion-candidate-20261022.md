# 外环完成时序候选：控制完成与任务诊断统计分离

## 本次新故障，不与旧 600rpm 门限问题混淆

用户要求补完其余八轮。实际第一轮 600rpm 完成，第二轮刚起步独立保护退出，700/800 未执行：

- 批次 `tmp/mechanical-ident-batch-1792672632711877100.json` stopped，成功 child `tmp/mechanical-ident-run-1792672632774085000.json`，失败 child `tmp/mechanical-ident-run-1792672676073127300.json`。
- 失败首故障 flags=512（outer stale），`now_us=8139512`、`outer_us=8137505`、elapsed=2007µs，原 deadline=2000µs。随后累计 flags=544 包含 encoder control stale。
- 编码器 control deadline=8140005，now=8140006；SPI transaction timeout=0、DMA error=0、schedule miss=0。
- glitch_count=0、glitch_streak=0；cursor 已消费 sequence6649 / sample_us8139303，prev_raw/angle 已推进，说明不能直接断言整个控制任务没有被调度。
- 当时 filtered speed≈0.982rpm，trajectory reference≈13.955rpm，非 1000rpm 超速，也非旧 600rpm 合理性拒绝。
- FOC max32.724µs、deadline miss=0、CCR late=0；CUR_CONFIRM49/49/0，unresolved max1。

用户确认 12V 关闭后，恢复原 B：`tmp/mechanical-ident-restore-1792672777028793500.json` PASS；原 B/boot/config 不变、B 未运行、输出关闭、CPU halted。

## 证据边界

旧实现把 FF 误差统计、机械辨识窗积分、摩擦统计和 plateau 汇总都放在 `FOC_EncoderSpeedUpdate` 返回之前；这些**不参与控制输出**的工作也因此占用角度发布/真实 ACK/outer-completed 心跳之前的时间。

本次存在“已消费新 sample，但完成时间戳仍旧”的实际证据，但没有保存完整任务调度/PC/每段耗时，**不能先证明所有延迟都来自上述诊断统计，也不能声称任务饥饿已排除**。下述顺序修正针对已知结构耦合，并加入阶段证据；是否解决真实超时必须重测，失败不继续。

## 最小流程修正，仅新 A

新预设 `MechanicalOuterCompletionCandidate`，继承已验证编码器准入修复版，新增默认关闭开关 `FOC_OUTER_OBSERVE_AFTER_ACK`。

旧：

`consume → 原速度/PI/S-curve计算 → 非控制统计 → stall等原保护 → angle发布 → 真实encoder ACK → outer完成时间戳`

新：

`consume → 同一原速度/PI/S-curve计算并保存诊断输入 → 同一stall等原保护 → 同一angle发布 → 同一真实encoder ACK → outer完成时间戳 → 非控制统计`

- 所有控制数学、保护判断和角度预测代码不变，不在控制未完成时提前喂狗。
- 真正 HAL_OK、cl_armed、无 ADC/FOC fault 才可做后置统计；BUSY/reject/fault 不刷新完成心跳、不执行残留统计。
- 在原观察点保存 coherent MechanicalCurrent、sample_us、观察时刻、实际 dt/delta/omega/saturation，后置机械积分仍使用这些同一轮数据，不把稍后的 ADC 样本混入旧 encoder 样本。
- 后置 helper 没有 PI、setpoint、angle、PWM 或 watchdog 写入；仍在同一个 MotorControlTask 内执行，不新增任务、ISR、RTOS API 或 IRQ 屏蔽。
- 原保护在统计执行期间仍可抢占并关闭输出；若整个 task 真正卡住，原期限仍到期。
- 参数/保护：Ka0.000046875 A/(rpm/s)、Iq±0.50A、电压1.60V、超速1000rpm、行程30000°、outer2000µs、control2500µs、sample age1500µs、transaction200µs、IRQ优先级和12s lease全未变。
- 普通 A、旧候选、正式 B 均默认关闭，不修改其行为或旧镜像身份。

## 新阶段证据

任务内 16×36B 环加 current/metadata 共644B，记录 entry_us、consume_us、sample_us、seq、commit_us、observe_begin/end、HAL status、phase，以及最大 entry gap/core/observe 耗时。它们是 wall time，包含 IRQ 抢占，最大值也包含预检阶段，不冒充纯 CPU 时间。

phase：1 task entry；2 consumed fresh sample；3 core+ACK+outer committed；4 task-only observations；5 observations finished。

首故障原有临界区中仅增加两次整数写：保存 fault_phase 并 frozen=1；不扫描 ring、不格式化、不读时钟、不增加 IRQ mask、不延长 watchdog。现场 ISR/任务处理阶段之后可能有尾部单条 store，但独立保存的 first-fault phase 不被后续 trace 改写。

正常关断后的 idle trace 可能覆盖末尾 ring，因此正常结果主要看最大值及故障计数；故障时 ring 冻结用于排查。未声称能从此 trace 直接恢复精确 ISR PC 或完整任务调度图。

## 编译与测试

- 新 A Flash209084B、RAM129488/131008B，静态余量1520B；heap/线程栈未缩减。
- BIN SHA256 `e2f875992a94830d729155137d7aa70fee48feec6f801f61f3788c65db7b0e84`。
- ELF SHA256 `6b2ed548cb4751f6dc99b8f16ade53c59667dc0751d576ee7ff06a4348bc6a8f`。
- 专项六项通过：实际预处理 control diff、实际 service/flush 执行顺序、BUSY/error不确认、独立fault冻结、微秒wrap、warning集合、只读镜像及真实恢复身份、powered/OFF门禁。
- 除两个显式观测路径变动外，实际 encoder-control 函数去掉观测部分逐 token 相同；current FOC、PWM、IRQ/encoder/ADC/zero/FSM/mechanical模块对象未变，保护门限未变。
- B 独立复编通过，BIN SHA仍 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
- 没有新增 warning 集合；保留已有 unused/RWX警告。
- 全部相关回归 **158项通过**：encoder30、mechanical34、speed88、outer专项/脚本6；未进行板测的数据不填入耗时结论。

## 单次重测计划

用户已要求修复后重新测，并确认 12V 关闭。脚本 `tools/outer_completion_board.py` 仅一次600rpm，默认只读文件；先核验实际旧修复版恢复链，再安装新镜像身份。新只读limits必须返回 `PLAUSIBLE_RPM=1000 REJECT_BUSY=1 OBS_AFTER_ACK=1`，不匹配即不启动。

回归通过后仅写非活动A并完整独立回读。人工另行确认实际上电/无报警/空载固定/转轴解锁/限流0.5A/现场可立即断电后才执行，故障不重试、不接着跑700/800；保存完整Flash/RAM及新trace。采完要求12V关闭后，仅恢复原B，不自动启用DOB或应用模型。

### 已完成断电暂存

`tmp/mechanical-ident-stage-1792673499755037900.json` PASS；仅新非活动 A 写入、独立完整回读通过，原 B/boot/config 未改。activation=false、motor_commands=0、输出关闭、CPU halted；等待另行实际开启 12V/无报警确认，不代表重测已经完成。

## 一次 600rpm 真实重测结果

人工确认上电、无报警、可立即断电后，仅执行一次600rpm；批次 `tmp/mechanical-ident-batch-1792673560319977700.json` PASS，唯一 child `tmp/mechanical-ident-run-1792673560432965500.json`。没有重试或700/800rpm命令。

正常约7.86秒完成原5秒命令及S-curve减速关断，未触发task10.5秒或独立12秒lease。MOTOR TEST FAULT VALID=0/FLAGS=0，first_fault.valid=0。

| 项目 | 实测 |
|---|---:|
| 固定3.65~4.95秒稳态窗口平均速度 | 599.265rpm |
| 同窗口平均Iq | 0.216613A |
| 同窗口平均绝对Id | 0.039573A |
| 完整64ms同步窗口 | 121，flags=0 |
| FOC最大wall time | 33.494µs |
| deadline miss / CCR late | 0 / 0 |
| 最小实际CCR余量 | 15.159µs |
| actual CCR commit | 290632 |
| CUR_CONFIRM enter / clear / fault | 111 / 111 / 0 |
| encoder control stale / transaction timeout / DMA error / schedule miss | 0 / 0 / 0 / 0 |
| encoder glitch count / streak | 0 / 0 |

新阶段记录读回：count14779、frozen=0、fault_phase=0；最大task进入间隔1089µs，最大core计算/发布耗时147µs，最大后置观察统计144µs。均为wall time、包含IRQ抢占和预检阶段；各最大值不一定发生在同一次更新，不相加冒充单轮最大耗时。

同会话BIN/ELF/Flash/RAM SHA、完整来源/关断/保护资格核验均通过。仅新候选本轮通过，支持此顺序修正可行，**不能据此证明上一轮2007µs延迟唯一由统计引起，也不代表重复性或700/800rpm已验证**。2ms/2.5ms和所有原限幅/保护没有改大，DOB仍未参与控制。

### 已恢复原B并停止

用户确认“关了”后，仅恢复原B启动选择：`tmp/mechanical-ident-restore-1792673660935323300.json` PASS。原B大小227964B/CRC627317606，boot/config/private核验未变；最终VTOR=0x08040000、SD/BDTR/CCER=0、CPU halted、B application not run、motor_commands=0，不再运行电机。

# 启动超速：首因修复与定向记录候选

## 当前结论

已修复一个可由生产绑定代码离线复现的诊断缺陷：独立保护已关闭输出并解除 cl_armed 后，外环更新返回 HAL_ERROR，原 TaskService 又追加 CL_BAD_ENCODER，混淆超速与编码器故障。新候选在外环返回后先检查是否已被独立保护撤销；已经撤销则不再追加编码器错误。真正的编码器失败仍关闭输出并记录 CL_BAD_ENCODER，没有关闭任何保护。

这不是“超速本体已修好”。B549 的实际 START 仍是目标 20 rpm、约 28.879 ms 后记录 60.7 rpm 超速；现有证据不足以区分电流跟随、方向／电角度、速度估算及调参问题。不能仅凭速度反馈的 20 ms 低通就断言唯一根因，也没有盲目更改滤波时间常数、PI 增益、相序或电角度零位。

## 新候选做了什么

- 独立构建配置 `LatestOriginalStartupEvidence` 继承 `LatestFeedbackOriginalFsmCountOnly`，增加 `FOC_STARTUP_TRACE=1`。历史构建目录和哈希绑定工具不覆盖。
- 保留最新自适应四点电流筛选与旧 START／拧紧状态机、零点累计数量只计数策略。20 rpm／400 ms 单次验收范围、60 rpm 超速、筛选电流 4 A 的 2/3 确认、反馈／编码器时效和 50 µs 计算截止均未改。
- 仅运行期间在实际外环更新结束后记录一帧，保存最近 32 帧；不在 20 kHz ADC 路径增加日志打印或缓冲写入。外环通常约 1 kHz，但不能把每帧间隔假定成精确 1 ms，应看时间戳。
- 记录速度参考、瞬时／低通速度、Iq 指令、Id/Iq 反馈、Vd/Vq、d/q 积分、编码器原码与时间戳、物理 ADC 原码和序号。
- 首次故障先关闭 SD/PWM，再冻结首因标志和故障现场，随后才清电流参考。后续 STOP／安全清理和追加标志不能覆盖这份首因。正常 STOP 也冻结环形记录。
- 数据仅在冻结后读取；不存在清故障、清记录后重新准入或自动重试命令。重置记录必须复位，并且仍受原单次准入约束。

“外环完成帧”是在短 PRIMASK 区间内复制软件状态，不是所有传感器在同一物理瞬间采到的帧。电流数据来自最近一次完成的内环，RAW 为最近物理 ADC 对；筛选反馈可能有一对延迟。首次故障帧可能打断外环计算，速度参考与速度 PI 更新阶段也可能不同。不得将这些帧冒充严格同步电流／位置测量或硬件电流精度证明。

## 停机后读取

沿用本地带请求编号的串口命令协议；以下只列命令正文，不是自动上板执行脚本：

```text
MOTOR TEST STARTUP CONFIG
MOTOR TEST STARTUP
MOTOR TEST STARTUP FAULT
MOTOR TEST STARTUP FRAME 0
```

CONFIG 可查询功能身份和占用；其他命令在未冻结时返回 STARTUP_NOT_FROZEN。摘要 N 是可读帧数，FRAME 索引范围 0 到 N-1，按时间先后返回；FAULT 只有首个故障有效时可读。不允许负数、越界、超长整数或带尾部垃圾的索引。若输出空间不足则返回显式格式错误，不伪装成完整成功帧。

字段含义：

- US：相对本次准入时间的微秒数；若准入前就发生故障，尚无启动基准，不能按运行时长解释。
- SEQ：最新物理 ADC 序号；ENC_US：最近外环消费的编码器采样时间戳。
- RAW：编码器角度原码、U 物理 ADC 原码、V 物理 ADC 原码。
- RPM10：参考、瞬时、低通速度，单位 0.1 rpm。
- MA：Iq 指令、Id 反馈、Iq 反馈，单位 mA。
- MV／INT_MV：d/q 电压与 d/q 积分，单位 mV。
- FIRST_FLAGS：首次关闭路径收到的健康标志，与旧 MOTOR TEST FAULT 中的累计 FLAGS 分开。若由电流确认等非健康位原因关断，FIRST_FLAGS 可能为 0，须结合 MOTOR TEST PROTECTION 的原因码；0 不代表无故障。
- 非有限或超出格式化范围的浮点数显示为 INT32_MIN，不当作有效测量值。

后续分析先看：速度参考是否按斜坡增长；速度反馈超过参考后 Iq 指令是否反向修正；Iq 反馈是否跟随指令；是否电压已饱和；编码器原码增量与实际时间差是否一致。软件反馈的方向不等于独立仪表确认的实际电流方向，不能据此擅自反接电流输入或翻转电角度。

## 离线验证及资源

新增 4 项回归通过：环形缓冲与时间回绕、首因／冻结／非法浮点格式化、实际生产绑定的保护抢占与真实编码器失败、配置拒绝及新旧镜像身份。C 测试分别以 -Os/-O2、警告视为错误运行，覆盖正常 STOP、冻结前拒绝读取、合法帧及非法索引。

连同旧 START 适配、零点策略、保护链、原速度状态机兼容性、自适应筛选与主机准入，总计 63 项回归通过。首次宽泛 discover 因工具目录不在 Python 搜索路径，两个验收测试未加载；补充 tests/tools 搜索路径后全部 63 项通过。这些是离线测试，不是电机动力学、真实采样精度或本候选 50 µs 上板验收。

| 镜像 | BIN | 链接 RAM | 链接剩余 RAM | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| A | 211004 B | 124792 B | 6216 B | b9ef16c8561d279e93db06419237d0cb5e81daafe40f964c51e33dd115aae411 |
| B | 210116 B | 124776 B | 6232 B | 2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b |

cl_startup 静态对象为 2000 B，无堆分配。链接剩余 RAM 不是任务剩余栈证明。编译器静态栈报告中，ProtocolTask 864 B、Protocol_HandleLine 736 B、ProtectedLoop_Command 312 B、格式化函数 120 B；这些是各函数自身帧，不能替代完整含 libc／异常入栈的峰值。ProtocolTask 原配置为 1024 字（4 KB），未擅自缩减。EmergencyOff 自身帧由原 16 B 增至 152 B，实际最坏关断时序和 MSP 峰值仍需本候选实测，不能套用旧镜像结论。

A/B Release 构建通过，仍有已有未使用函数／变量和 RAM 热段 RWX 链接警告。尽管不在 ADC 20 kHz 路径增加记录，外环短临界区和代码布局变化仍可能影响总时序，必须重新测量，不能继承旧 49 µs 数值。

源码为 firmware_common/foc_startup_trace.h、foc_startup_trace_binding.inc，接入点在 protected_closed_loop.inc 与 latest_original_fsm.inc；测试入口 tests/test_foc_startup_evidence.py。构建在各槽工程执行 cmake --preset LatestOriginalStartupEvidence 与同名 build preset。

本轮只修改代码、构建和离线验证，没有连接硬件、刷写、复位、清故障或发送 START。板端仍是上一轮 B549，不因源码修改自动更新。继续刷写前需要当前驱动板 12 V 关闭状态；本轮没有确认或改变现场供电。

## 后续：断电暂存 A 槽（已完成，未激活）

收到用户“关了”的 12 V 关闭确认后，执行独立、哈希绑定的 `tools/foc_startup_evidence_stage.py`。板端最新确认槽是 B549，故写入非活动 A，未沿用旧脚本切回 A 再覆盖 B 的流程。

- 先核验 MCU 已暂停、VTOR 为 B、SD/PWM/定时器均关闭；整片 Flash 与上次 B549 停机备份逐字节一致，才允许编程。
- 受控 reset-halt 后仅在 `0x08008000` 写入上表 211004 B 的 A 候选；原非活动 A 已被替换，但旧镜像和本次完整刷写前备份保留，可恢复。
- 独立 verify_image 与整片 Flash 回读通过，A 镜像逐字节一致；A 槽外所有字节保持不变，包含 B549、bootloader、KVS、参数与升级元数据。确认槽仍 B，generation 仍 549。
- 不写试运行邮箱、不强制确认、不激活应用、不发送 START。最终 MCU 停在 bootloader 暂停态，SD=0、BDTR=0、CCER=0，TIM1 CEN=0。
- 刷写工具与候选相关 9 项离线回归通过；默认模式、缺少断电许可、目标地址约束、禁止恢复执行及槽外任意改动拒绝均已覆盖。

本次回执：`safety_backups/protected-closed-loop-20261014/startup-evidence-a-stage-1792059910937437500.json`。完整原始 Flash 备份留在原有受限 private 目录，不公开内容。

这是暂存验收，不是启动超速修复验收；候选尚未运行，也没有得到新启动记录或新的 50 µs 时序结果。A 的升级元数据仍为原值，后续激活须经现有正常 A/B 试运行流程，不应直接跳转运行候选或修改 Flash 元数据绕过确认。

## 后续：一次正常试运行验证（未通过）

用户要求“验证一下”，随后回复驱动板电源“开了”。本轮严格限定计算验收，没有发送 START 或使能功率桥。新增独立验收工具 `tools/foc_startup_evidence_acceptance.py`，通过 14 项相关离线回归后，向现有 bootloader 提交一次 B→A START_TRIAL；没有重新刷 APP、强制确认、清故障或失败重试。

回执：`safety_backups/protected-closed-loop-20261014/startup-evidence-a-compute-1792060167970913800.json`。

实测结果：

- **启动零点失败，未进入 FOC 计算验收。** 已接受零点窗口 N=2525/4000，ZERO STATE=4、REASON=3（不稳定），稳健零点 FLAGS=4（FOC_ROBUST_BURST）。这表示失败的某一个 5 对原始输入块中，至少 2 对的 U 或 V 偏离对应块中值超过 40 个计数；并非累计 33 对异常触发总数上限。累计 OUTLIERS=33、MAX=OFF、SEG_MAX=OFF，总数配额确实已关闭。
- 已通过块的中心范围 U=1555～1570、V=1555～1566，NOM=1558；失败现场最后一对原码 U=1655、V=1639。此最后一对不是整个失败 5 对窗口，不能据其单独重建全部窗口或判定电气根因。
- **新记录接口及首次故障冻结已实机读通。** CONFIG ENABLED=1、ROWS=32、FIRST_CAUSE=1、BYTES=2000；冻结摘要 N=0、TOTAL=0、FAULT=1、FIRST_FLAGS=8（CL_BAD_ZERO），累计旧 FLAGS=12。没有电机 START，故无运行外环帧，不能声称已捕获超速启动轨迹。首因帧的 US=1238387 为未准入时的时钟值，不是电机运行时长。
- ADC PAIRS=22530、MISS=0、PF=0、MAX_CYC=2536；按 170 MHz 约 14.92 µs，但这里只经过采样/校准路径，FOC WORK=0、MATH_MAX_US=0，**不能据此宣称完整 FOC 小于 50 µs**。
- 编码器启动校验 20/20，DMA READS=21、FAIL/TIMEOUT/IO/SCHED/STALE 均 0；这仅覆盖本次短启动观测，不是运行期编码器长期验收。
- STOP 与 ANALOG SAFE 均收到确认，最终经 SWD 校验关闭输出并暂停 MCU。所有 APP、bootloader、KVS 和私有参数字节未变，升级元数据由正常试运行流程更新为 generation 551，confirmed=B、pending=A、attempts=1；**没有正常确认 A，也没有另行复位回退 B**。保留暂停现场，不应直接恢复失败 A 的执行。

已提示关闭驱动板 12 V，后续只分析保存数据。本次通过的是记录接口身份/首次故障冻结及输出锁定，不是零点、完整 FOC 耗时、电机闭环或超速修复验收。未擅自放宽 BURST 条件或绕过失败继续启动电机。

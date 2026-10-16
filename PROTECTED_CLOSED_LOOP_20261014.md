# 保留保护的闭环短测版本

这次新增 `ProtectedClosedLoop` 独立构建配置：接入真实编码器、双 ADC 注入反馈、原速度 PI 和电流 PI，不用虚拟电机。它不是工业扭矩精度验收，也没有完成真实电机带电验收。

## 首轮怎么运行

开机先保持 SD、MOE、CCER 为零，只做新的零点校准和影子 FOC 计算。A/B 健康确认结束、反馈正常、转子静止后，才接受本地 UART 的 `MOTOR TEST SPEED`。Router、CAN、RPC 和普通 START 不能代替这个入口。

首轮目标固定为 20 rpm，最长 0.4 秒，沿用速度环的 0.40 A Iq 指令限幅。4 A 是保护判据，不是本次驱动电流指令。每次启动只允许一次请求；STOP 或故障后不自动重试。`MOTOR TEST STOP` 立即关闭功率输出；`ANALOG SAFE` 进一步停止影子计算、采样触发和独立监护定时器，便于升级维护。

## 筛选与保护各管什么

- 四点候选筛选给控制环提供反馈，只修补符合规则的孤立点；每 32 对最多修补 6 对，连续最多 4 对。
- 筛选反馈超过 4 A，按 2/3 确认规则锁存停机。该实验配置不使用单个原码 4 A 立即停机，但仍检查原始 ADC 的合法性、连续性及新鲜度。普通构建的原码保护没有修改。
- TIM7 每 25 µs 独立检查：采样超时 100 µs、外环心跳超时 2 ms、运行超过 0.4 秒、过速 60 rpm、输出状态异常等都会关闭输出。
- 编码器/DMA 错误、ADC 错误、HardFault、计算耗时达到 50 µs 都走锁存关断。不依赖串口 STOP 及时到达。
- 不修改驱动板独立过流关断。用户说明它存在；本次离线测试不能证明其物理动作时间或覆盖范围。

IU/IV 使用手册所示低侧 U/V 电阻采样的窗口配置。采样窗口配置及软件保护通过离线检查，不代表物理栅极极性、带开关电流反馈或实际闭环稳定性已经验收。

## 最初版本的证据与边界（历史记录）

2026-10-14：最终回归 69 项 Python 单元测试通过，其中实际绑定代码的寄存器模拟覆盖 21 个场景，包括启动、取消排队、STOP、租约到时、停止 ADC、停止外环、过速、筛选过流、修补预算、定时器配置错误、故障锁存及维护关断；新增检查启动校准阶段不提前启动周期编码器 DMA，以及暂时没有新编码器快照时不伪造心跳、外环超时仍关断。另覆盖 bootloader 正常回退清除失败槽长度/CRC 标记、不接受被篡改的 A 或异常元数据。A/B 新配置和普通配置均编译通过。

| 镜像 | 字节 | SHA-256 |
| --- | ---: | --- |
| A 修正候选（未部署） | 206040 | `c4e3431e322c0d0ad60e9d44d1e6035b850b5a7b3cd2e500c05bd601dd1e3339` |
| B 启动修正版（当时已暂存，后来短测失败） | 205152 | `c5bb72af17b8a9b486aab0af53aeeba1cce4435476176fbbacffa547adfb191a` |

首次暂存前板端只读查询确认 A466，SD/MOE/CCER/CEN/FOC 关闭。`tools/protected_closed_loop_stage.py` 只允许把精确 B 镜像通过官方 UART `pw_transfer` 暂存到非活动槽，拒绝 FW END、复位和任何运动指令；校验完整 Flash，要求锁定 A、bootloader、KVS、参数和元数据不变。修正版暂存也接受经过完整证据链验证的回退 A（GEN470），不接受任意基线。只有成功的 stage JSON 才能证明实际暂存通过。

## 首次实机结果：未启动电机

初始 B 镜像 `7c948941...` 暂存和回读通过，A/bootloader/参数/元数据不变，随后只提交一次 FW END。启动期间编码器 DMA 的 2.5 ms 控制消费监护超时；零点采样只处理了 49 对原码（中值校准器接受 46 对，还在 settling），没有完成校准。启动日志笼统显示 ZERO FAILED，随后进入 ADC 低频错误处理，控制台尚未创建，因而健康确认及串口收尾都失败。

独立 SWD 读取确认：VTOR=`08040000`，GPIOC ODR=`0`，TIM1 BDTR=`02002055`，CR1=`00000020`，CCER=`0`，CFSR=`0`。SD/MOE/AOE/CCER/CEN 均关闭，没有 HardFault 证据。编码器 `control_stale=1`，`schedule_misses=0`，`dma_errors=0`，`timeouts=0`，实际 DMA sample status=`8`（`AS_DMA_CONTROL_STALE`）。主机电机命令数为 **0**。不能写成闭环短测通过，也不能把这次失败归为电流幅值越界。

修正候选把编码器周期 DMA 的启动移到实际 1 kHz 控制任务的首次调用，保留 2.5 ms 监护，不在无消费者的启动校准阶段提前启动；必须已有实际外环更新才允许接收短测请求。同时保留启动失败后的锁定通信服务，让 A/B 健康逻辑拒绝确认并正常回退。主机另修正 ZERO READY 枚举检查为 3，拒绝自动重试已失败的旧镜像。

首次失败证据：`safety_backups/protected-closed-loop-20261014/stage-1791942124393828900.json`、`trial-1791942706728658000.json`、`FIRST_FAILURE.md`；初始 B BIN/ELF 已另存用于故障符号解析。当时板端是未确认、输出关闭的初始 B；随后恢复及修正版部署结果见下节。

后续真实短测需另记录：实际动力线/供电状态、新零点、A/B 自动健康确认、反馈保护状态、运行时长、转速/Iq 与最终关断状态。尚未完成这些，不能写成“闭环验收通过”。

## 断电恢复结果

用户随后确认驱动板 12 V 已关闭。现有 bootloader 经两次受控复位消耗旧 B 剩余试运行次数并回退，GEN 从 468 到 469，再到 470；confirmed=A、pending=none、attempts=0。没有直接写入 Flash 元数据、强制确认或发送电机指令。

bootloader 的正常回退同时将失败 B 的 metadata 长度/CRC 清零，B 的实际 Flash 数据并未擦写。最初的回退脚本误要求该标记保留，导致在已回退的 A 上报验证失败；按源码修正该规则后仅只读复核，没有追加复位。

复核证据 `safety_backups/protected-closed-loop-20261014/rollback-1791944009356429100.json`：完整 Flash 回读确认 bootloader、原 A、实际 B 数据、KVS 和参数区与首次暂存快照一致；VTOR=A，SD/MOE/AOE/CCER/CEN=0、CFSR=0；UART 的 `ANALOG SAFE` 锁定确认通过。

修正版随后经官方 pw_transfer 暂存 B 并通过完整回读：`safety_backups/protected-closed-loop-20261014/stage-1791944031520921800.json`，205152 字节，CRC32=`3879C379`。所有 B 槽之外的字节（含 bootloader、原 A、KVS、参数和元数据）不变，寄存器仍证明 A 上 SD/MOE/AOE/CCER/CEN 关闭、CFSR=0。没有提交 FW END、复位、激活 B 或发送电机指令。

当次暂存结束时：A 已恢复且锁定，B 启动修正版已写入但尚未试运行。随后试运行和短测结果见下节；最新状态见文末。

## 修正版首次真实闭环短测：未通过

用户回复“开了”后提交一次 FW END。B 校准成功并通过连续 5 秒健康门，现有 bootloader 自动确认 B，GEN473，无 pending。自动确认复位期间主机的 MOTOR TEST STATUS 查询超时，收尾 FW STATUS 也因重启窗口超时；该阶段未发送电机命令，记录 `trial-1791944557452413600.json`。

随后只读证明 B 已确认且 READY/USED=0/ZERO=3/FLAGS=0/FAULT=0，SD/MOE/CCER=0。主机增加受限的“继续准备”入口：仅接受该确认复位中断、之前电机命令数为零、精确 staged Flash 的证据；不重发 FW END、复位或清故障。再次完整回读确认镜像及保护区一致后，仅发送一次 MOTOR TEST SPEED。

结果记录 `safety_backups/protected-closed-loop-20261014/trial-1791944717018072100.json`：

- 运行前：4000 对中值零点通过，U0=1563、V0=1560、nominal=1561；中值范围 U=1521..1604、V=1518..1603。原码校准旁路仍显示 RAW_STATE=4/RAW_REASON=2；不据此宣称原码零点也通过。
- 真实 FOC 计算的已统计最大耗时为 40 µs（不是端到端 WCET 或物理响应时间）；外环在正常运行，保护无故障。
- 短测请求接受，20 rpm/最多 400000 µs；主机电机命令总数为 1，没有重试。
- 软件记录 start=148162373 µs、off=148162468 µs，即 95 µs 后锁存关断，未完成 0.4 秒运行，不能验收转速/扭矩或闭环稳定性。
- 故障 FLAGS=4（CL_BAD_ADC），REASON=3（HEALTH），最近有效对时间 148162288 µs，关断记录距它 180 µs；原码快照 U=1563、V=1559，接近零点，不是本记录证明的 4 A 幅值过流。
- 后续只读回读 cl_guard_us=148162421 µs，距最后有效对 133 µs，已超过 100 µs 新鲜度限值。ADC TIMING 显示 MISS=0、PF=0。证据指向采样新鲜度/启动切换时序，尚不能区分临界区阻塞、触发间隙等具体根因，也不据此归因硬件电流尖峰。
- ADC TIMING 的粗略 deadline_misses 计数为 2937692，并非零；其口径是 IRQ 入口至出口与计数器剩余时间比较，不等同于 MOTOR TEST TIMING 的 LATE。不能用后者 LATE=0 掩盖这个时序告警。
- STOP、ANALOG SAFE 及完整 Flash/寄存器收尾全部通过。B 仍正常确认但故障锁定；SD/MOE/AOE/CCER/CEN=0、FOC=0、CFSR=0，A/bootloader/KVS/参数保持不变。不再启动或复位本轮测试。

本轮真实闭环结论：**未通过**。没有通过“已校准”或“请求已接受”来替代电机实际运行证据。下一步应定位启动切换的采样时序，不是放宽 4 A 阈值或屏蔽新鲜度保护。

## 时序软件问题及离线修正候选

继续检查发现，旧版 `ProtectedLoop_Ready()`、`ProtectedLoop_TaskService()` 的准入关中断区调用 `BootHealth_IsCurrentTrial()`；运行期间 `ProtectedLoop_Health()` 也调用该函数，使 25 µs TIM7 监护和 ADC 回调在 RUNNING 后进入同一路径。该函数不是一个单纯的 RAM 标志读取，而是调用 `BootMeta_ReadV3()` 读取两份 Flash 元数据，对每份有效记录的 44 字节重新计算位循环 CRC32。

旧 B ELF 的 `ProtectedLoop_Health` 在 `0x08046002` 有 `bl BootHealth_IsCurrentTrial`，TIM7 调用它时 PRIMASK=1；准入调用同样位于 PRIMASK=1 区间。这是明确的实时路径设计缺陷。它与“开始前已距上次样本 85 µs，开始后第一次监护见 133 µs 样本年龄”的快照一致，是目前主要软件原因；尚未通过修正版实机对照证明它是全部原因，不宣称已经测得 CRC 实际耗时。

修正只修改独立 ProtectedClosedLoop 绑定：在开机、输出关闭、ADC/监护尚未 armed 时，前台验证元数据一次。仅 `confirmed_slot==APP_THIS_SLOT && pending_slot==NONE && attempts_left==0` 才发布本次启动的已确认标志，缺失或无效元数据默认拒绝电机准入。试运行仍允许功率关闭校准/正常健康门，但必须经现有 bootloader 自动确认复位后，下一次开机才能取得准入标志。实时路径只读这个 RAM 状态，不反复做 Flash/CRC。

4 A 筛选 2/3 保护、100 µs 采样新鲜度、2 ms 外环新鲜度、400 ms 租约和全部错误关断未放宽。Flash 元数据只由 bootloader 在复位时改变；升级 active 会拒绝准入，维护锁定不会重新置 armed。本修正不增加清故障或自动重试入口。

离线验证：70 项 Python 回归通过，实际寄存器绑定模拟 24 个场景，包括“元数据只能在前台且监护未启动时读取”“连续 1000 对 RUNNING 样本仍仅一次元数据读取”“试运行/无效元数据拒绝启动”“准入标志丢失立即关断”。A/B 编译通过；新 B 的 Health 反汇编无 BootHealth/BootMeta/CRC 调用。

| 时序候选路径 | 字节 | SHA-256 |
| --- | ---: | --- |
| `foc2_app_a/build/ProtectedTimingFix/foc2.bin` | 206112 | `b2b2152bb42649cc5836ef68d2a2766c80f54a73483b1b806107a7194361985e` |
| `foc2_app_b/build/ProtectedTimingFix/foc2.bin`（现已确认，短测失败并锁定） | 205200 | `a0c55c4dc76fbd240a02a33d34a17e8b5dd687c67c6d921600c5df10a221815e` |

使用独立 build 目录，没有覆盖旧 B 对应的 BIN/ELF、旧 pinned 上传脚本或故障证据。离线修正完成时板端为 B473 故障锁定；随后部署结果见下节，仍不能写成“时序故障已在实机消除”。

## 时序修正版暂存完成：尚未带电复测

用户本轮回复“关了”，驱动板 12 V 关闭。`tools/protected_timing_fix_stage.py` 首先完整回读并核对精确 B473 故障快照、保留的原 A 镜像及既有证据链，然后仅发送一次 `BOOT A`，由现有 bootloader 校验已知 A 的大小/CRC 并选择它。不是强制确认新候选，没有直接写元数据或清故障。原 A 已运行并锁定，GEN474；所有 APP、bootloader、KVS 和参数字节不变，仅发生预期的 bootloader 元数据选择事务。

选择证据：`safety_backups/protected-closed-loop-20261014/timing-select-original-a-1791945988744038600.json`，PASS。

随后官方 UART `pw_transfer` 将时序修正版 B（205200 字节，CRC32=`356FA2C9`）写入非活动槽。完整 512 KiB 回读逐字节证明精确新 B，**B 槽之外所有字节不变**，包括原 A、bootloader、KVS、参数和全部 Flash 元数据。未发送 FW END、未激活新 B、未发送运动指令。

暂存证据：`safety_backups/protected-closed-loop-20261014/timing-stage-1791946019330136500.json`，PASS。

末次寄存器：VTOR=`08008000`、GPIOC ODR=`0`、TIM1 BDTR=`02002055`、CR1=`00000020`、CCER=`0`、CFSR=`0`；SD/MOE/AOE/CCER/CEN 均关闭。FW STATUS：CURRENT=A、CONFIRMED=A、GEN474、PENDING=none、ATTEMPTS=0、TARGET=B、ACTIVE=1、RX=SIZE=205200。ACTIVE=1 表示升级事务已暂存，**不是电机运行**。

新增部署/验收脚本测试后，完整回归为 74 项通过，实际寄存器模拟仍覆盖 24 个场景。验收须显式选择 `--timing-fix`，只接受新候选的精确暂存和原 A 选择证据；旧失败记录不会授权重试旧电机命令。当次暂存结束时为：12 V 关闭、原 A 锁定、新 B 暂存未激活。随后真实短测及最新状态如下。

## 时序修正版真实短测：13.955 ms 后关断，未通过

用户回复“开了”后，主机执行一次 FW END。B 零点及连续 5 秒健康门通过，现有 bootloader 自动确认、复位，GEN477，pending=none。没有强制确认或追加主机复位。自动确认复位期间仅继续只读观察，没有重发 FW END。

证据：`safety_backups/protected-closed-loop-20261014/trial-1791946470411344800.json`。

- 新启动中值零点：N=4000、U0=1563、V0=1561、nominal=1561、RET=0；范围 U=1521..1611、V=1521..1600。RAW_STATE=4/RAW_REASON=2 仍是原码旁路审计，不宣称原码也通过。
- 启动前 READY/USED=0/ARMED=1/ZERO=3/FLAGS=0/FAULT=0，采样与外环有真实工作量，FOC 已统计最大耗时 40 µs。完整 Flash 和输出关闭回读通过后，仅发送一次 `MOTOR TEST SPEED`，目标 20 rpm、最多 400000 µs。
- 结果 STATE=FAULT、USED=1、ARMED=0，软件运行时长 **13955 µs**（约 13.96 ms），FLAGS=4、FAULT=1，未完成 400 ms。故障 STATUS 为 POS=-2.65 deg、CTRL=-11.2 rpm、DET=-12.2 rpm；这是停机后快照，不是目标转速达成或稳定闭环证据。
- 故障 REASON=3（HEALTH）、FLAGS=4（CL_BAD_ADC），SEQ=134573，原码 U=2072/V=1113，最后有效对时间 6846182 µs、输出关闭记录 6846289 µs，两者相差 **107 µs**。本记录不是 4 A 确认过流触发。
- 随后只读 SWD：cl_guard_us=6846268、cl_last_us=6846182，两者差 86 µs；cl_session.start_us=6832333、outer_us=6846253、state=4/used=1/started=1；adc_fault=0。ADC TIMING：IRQ=PAIRS=134574、MISS=0、PF=0。最近一次 TIM7 检查尚未超时，但下一对进入处理时已有超过 100 µs 的样本间隔；这些证据指向 Pair 路径的新鲜度检查，而非双 ADC 配对缺失或窗口计划失败。
- 停机后只读计算统计 MAX_US=47、LATE=0；完整 ADC IRQ 已统计 MAX_CYC=8796，在 170 MHz 下约 **51.74 µs**，超过 20 kHz 的 50 µs 周期。它包含中断抢占等 IRQ 入口至出口耗时，不能仅用计算主体 47 µs 或 LATE=0 宣称完整实时链通过。ADC 的粗略 LATE=110567 仍非零，不能忽略。
- 当前资料还不能唯一确定 107 µs 间隔由 IRQ 延迟、动态 CH4 采样相位/预装载提交还是其他临界区造成；这次数据不能据此归因 EMI，也不能证明删除实时 Flash CRC 已消除全部问题。后续应记录相邻采样时间、触发提交相位和完整 IRQ/关中断耗时；本轮未继续修改或试运行。

收尾 STOP、ANALOG SAFE、完整 Flash 和寄存器检查通过。B477 已确认但故障锁定，SD/MOE/AOE/CCER/CEN/FOC=0、CFSR=0；原 A、bootloader、KVS、参数仍不变。主机 FW END=1、电机命令=1，没有自动重试、清故障、放宽保护或第二次启动。已提示用户关闭 12 V；提示后未收到新的关闭确认，不能把物理供电状态记成“已关闭”。

结论：此次比旧版 95 µs 瞬停运行得更久，但**闭环短测仍未通过**；不算工业速度、扭矩精度或持续稳定性验收。

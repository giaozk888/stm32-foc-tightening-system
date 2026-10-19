# 升流继续：+0.12 / +0.15 / +0.18 A 已做，+0.20 A 前发生 CURRENT_INVALID

用户明确要求继续升流，不因前一次 0.11° 的小回摆停住。此次不重刷、不改任何 PI、相序、电角度、硬过流、CUR_CONFIRM、current discriminator 或 PWM pipeline。

## 主机调整（不改变板端控制/保护）

此前 `standstill` 要求从第一次读取开始 1 秒内位置范围≤0.10°；任何一次超过即退出，实际仅 0.11° 的短时回摆也会中止。

改为最多等待 5 秒，寻找至少 1 秒、至少 10 次观测的连续稳定窗口，仍要求输出关闭、IDLE、无 fault、CTRL/DET 均≤1 rpm、窗口内位置范围≤0.10°。短时回摆/尚未停稳会重新等待，不立刻 abort；超过 5 秒仍无稳定窗口、通信失败、非有限数、板端 fault 仍停止。没有在桥带电时热切换参考值。

增加只接受“此前正常 DONE、无板端 fault、仅旧主机 coast 检查失败”的人工继续入口 `--resume-after-coast`。它校验同次完整 Flash、SRAM、原命令、已确认 A metadata、B/boot/private 和电流/时序证据，从下一档开始，不重跑 +0.10 A。不能用此入口继续 CURRENT_INVALID、超速、过流、命令不明或时序故障。

离线记录边界也改为读取同次 SRAM 的 `cl_stop_us - cl_session.start_us`。首档实际关断=5000010 us，最后观测=5000003 us，确实在关断前；不再仅因比名义 5 秒多 3 us 丢失完整运动记录。要求起始时间匹配、停止时间位于既有名义租约与 post-stop terminal 之间、全部原门状态/数据/保护检查仍通过。不截断时间戳、不修改板端 5 秒租约或保护。首档按这一修正重解码为 STICK_SLIP，未改成稳定旋转。

## 真实实验

下表只有前四行实际运行，各一次、每次约 5 秒。+0.10 A 来自上一批首档，本次没有重复。

| IqRef | 平均 Iq（保存帧） | 编码器净位移 | 判读 | 实际关断时间 |
|---|---:|---:|---|---:|
| +0.10 A（此前） | 0.09458 A | +1.07666° | STICK_SLIP | 5000010 us |
| +0.12 A | 0.12289 A | +0.74707° | STICK_SLIP | 5000010 us |
| +0.15 A | 0.14733 A | +1.07666° | STICK_SLIP | 5000010 us |
| +0.18 A | 0.16194 A | +1.47217° | STICK_SLIP | 5000006 us |
| +0.20 A | 未启动 | 未测 | 启动前 CURRENT_INVALID | 无 Iq 命令 |
| 负向各档 | 未启动 | 未测 | 批次已中止 | 无 Iq 命令 |

+0.12、+0.15、+0.18 A 都通过新的档间稳定检查；实际分别等待 36、12、11 次位置/速度观测，不再被旧的瞬时回摆判断中止。没有出现该三档板端 fault、FOC deadline miss 或 CCR late；三档 FOC max 分别为 28.87059、28.88235、28.91176 us，最小 actual margin 分别为 3.14706、2.55294、2.48824 us。

净位移仍只有约 1°，末段净位移接近 0；没有稳定持续转动证据。原码任务级累计绝对路程含编码器微小抖动，不能将该大累计值直接解释成真实机械走过的路程。软件 Iq 均值接近参考也不独立证明真实机械转矩、相位对应或摩擦根因。

## +0.20 A 尚未启动时的真实板端故障

重启同一 A 后零点通过：valid=4000、reject=43、total=4045、最长连续 reject=1、zero U/V=1560/1563。随后等待 5 秒时序报告期间从 READY 转 FAULT。

- `pulse_attempts=0`，没有发送 POS 200 或任何 START。
- fault snapshot valid=1，domain=2、reason=11（`FOC_FP_CURRENT_INVALID`）。
- `current_unresolved_consecutive=3`、max=3；suspect_total=373、confirmed_spike=340、confirmed_transition=22、unresolved_total=17。
- 故障时 MODE=IDLE、IqRef=0、SD/MOE/CCER 保持关闭。保存的 Iq=-0.43103 A、Id=-0.07410 A 是软件采样/变换读数，不能在输出关闭时当作已证实的真实相电流。
- FOC wall max=36.66471 us，deadline miss=0、CCR late=0；CUR_CONFIRM=22 enter / 22 clear / 0 fault。

**这次不是主机小位移限制，而是保留的板端 current-discriminator fault；也不能归因于已经执行了 0.20 A，因为该档根本没开始。** 按原保护约定停止，不自动清故障、重启或继续负向。

## 最终状态及证据

输出已关闭、MCU 停住，VTOR=A，DHCSR=0x30003、SD=0、MOE/AOE=0、CCER=0；启动选择仍 A696。完整 Flash 与升流前相同，SHA256 `df7c649c600ea750dfa8bc5e2b2384dcd7f5eef2b36503e5113741f815547f35`；B、bootloader、metadata、私有参数均未变。未进行新的固件写入。

- 本次批次：`tmp/breakaway5-batch-1792388770354256100.json`
- +0.12 / +0.15 / +0.18 A 子收据：同名前缀 `-01.json` / `-02.json` / `-03.json`
- +0.20 A 前故障：同名前缀 `-04.json`，同次 `-04-ram.bin` / `-04-flash.bin` 保留，不能用它冒充 0.20 A 电机数据。
- 汇总：`tmp/breakaway5-continuation-summary-20261019.json`
- 40 项相关离线测试通过：`tmp/breakaway5-continuation-tests.log`，覆盖回摆等待、持续不静止失败、真实前档继续、板端 fault 禁止继续、实际关断时间/样本边界及原有用例。

当前没有测得稳定起转的最小电流，正负 BREAKAWAY_IQ 和正式摩擦补偿均保持未知；缺失的 0.20 A / 负方向及三次重复不补数值。不自动将电流限幅提高到 0.25 A。

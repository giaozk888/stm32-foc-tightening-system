# 240 rpm 空载候选配置（4 转/秒）

10 月 20 日进一步完成[状态机自然结束观察](rundown240-fsm-board-20261020.md)：约 3.47 秒达到 3000° 行程边界，报告 RUNDOWN_TIMEOUT，无 CONTACT/OK；FOC max=31.641 µs、deadline/CCR late=0。已恢复原 B741，输出关闭、MCU 停在入口。下面的 B737/未刷板等描述对应更早的历史阶段。

后续更新：已经完成一次人工空载短测，能够建立运动并 arm，日志观察最高 228.7 rpm；尾段平均 204.13 rpm，240 rpm 稳速未通过。FOC max=31.40 µs、deadline/CCR late=0。详见[本次板测记录](rundown240-500ma-board-20261019.md)。用户关闭 12 V 后已恢复原 B 启动选择（generation 737），停在 B 应用入口、输出关闭、MCU halted，未运行 B 应用；下面的“未刷板”段落保留为此前准备阶段记录。

状态：仅修改、编译和离线验证。没有连接调试器/串口、刷板、复位、改变启动选择或启动电机。板端保持上一轮恢复后的原 B733，不宣称已取得 240 rpm 实测结果。

后续同日按用户明确的 `0.5 A` 请求，将此候选的速度模式 Iq 上限从 ±0.40 A 调为 ±0.50 A；下文镜像身份、大小和测试结果已更新。原 0.40 A 的 240 rpm 候选也未上板，不与历史 20 rpm 实测混淆。

## 本次配置

单独 A preset：`Tightening240rpmCandidate`，继承 `TighteningCommonModeCandidate`，显式打开默认关闭的 `FOC_RUNDOWN240_CANDIDATE`。B 不增加该 preset。

| 项目 | 新 A 候选 | 原 CommonMode 候选 |
| --- | --- | --- |
| 本轮 rundown 目标 | 240 rpm（4 转/秒） | 主机临时配置 20 rpm |
| protected 超速停机边界 | 300 rpm，绝对速度超出即走原故障路径 | 60 rpm |
| 通用速度环超速边界 | 300 rpm，不改 | 300 rpm |
| 通用速度接口范围 | ±250 rpm，不改 | ±250 rpm |
| 速度环 Iq 上限 | ±0.50 A，仅新 A 的 SPEED 模式 | ±0.40 A |
| 速度参考斜坡 | 200 rpm/s，不改 | 200 rpm/s |
| 单次 session lease | 12 秒，不改 | 12 秒 |
| 配方 rundown 允许上限 | 240 rpm，仅新 A | 120 rpm |
| SAVE PARAMS | 禁止写入 | 原实现 |

300 rpm 是候选边界，与现有通用速度保护对齐；不是已经验证安全的机械额定速度，也不是电流指令。原比较条件为 `abs(speed) > limit`，未改其实现。

新 A 在正常读取配方或恢复默认后、控制任务启动前，只将 RAM 中的 `rundown_rpm` 设为 240、标记 dirty，并打印 `RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF; manual START`。其他配方字段保持加载值。`GET RUNDOWN_RPM` 可看到有效 RAM 目标。`LOAD PARAMS` 仍可显式恢复原保存配方；不会谎报它已持久化成 240。

共享 V1 配方仍为 72 B、存储记录仍为 96 B。候选 `TightenParams_StorageSave` 直接拒绝，不执行保存回调；旧记录迁移也不能把扩展范围写回 B 共用的存储。原配方的载入/校验不改。

`MOTOR TEST PROFILE` 显示 `RPM=240`，保留完整 `QUALIFIED=0`，没有扩大响应缓冲区。原精确哈希、20 rpm 身份锁定的板测脚本保留不动，不能拿旧脚本直接启动新镜像。

## 未修改的控制与保护

速度/电流 PI 参数、积分上限、SB2/SB3 制动算法、参考斜坡、Clarke/Park、SVPWM、相序、电角零点、电流映射、PWM/ADC 频率、IRQ、一拍 pending/入口 commit、CUR_CONFIRM、TWO_SAMPLE、硬过流、encoder stale、时序和行程/超时保护均不变。POSITION 模式的通用 Iq 上限仍为 ±0.40 A，直接 IQ 模式仍为 ±0.20 A；软件相电流保护阈值仍为 4 A，未跟随命令上限放宽。

目标升高会改变原速度 PI 的误差和自然输出，但没有直接注入固定 Iq。静止且参考已达 240 rpm 时，比例项理论上是 0.72 A，最终仍受 ±0.50 A 限幅。参考从零按原斜坡到 240 rpm 理论需 1.2 秒。不能据此保证电机一定持续起转。

原 rundown guard 仍要求两个速度估计同时达到目标的 50%（这里为 120 rpm）、持续 100 ms 且同窗口前进至少 3°；NO_ROTATION、CONTACT/OK 前置条件不放宽。原机械行程和 12 秒 lease 仍可能先终止空载实验，不应解释成自动执行完整拧紧。

## 编译及离线验证

- 新 A：`cmake --preset Tightening240rpmCandidate` / `cmake --build --preset Tightening240rpmCandidate`，通过。
- 原 A/B `TighteningCommonModeCandidate` 重新编译通过，BIN SHA256 与修改前逐字节一致。
- 新 A Flash：228540 / 229376 B（余 836 B）。RAM：128808 / 131008 B（余 2200 B）；不是新的运行期任务栈实测。
- 编译告警集合与原 A 相同：12 项既有未使用函数及 1 项既有 RWX linker 告警，未新增告警；不宣称零告警。
- 74 项定向 Python/offline regression 全通过，含新 6 项配置/真实 FSM/真实配方存储/真实速度限幅测试，以及原 FSM、共模 planner、板测脚本、ADC 原因映射、CUR_CONFIRM、零点 admission、SB1/SB2/SB3、closed-loop pipeline。
- 3 项原配方 CTest（recipe/storage/x2 offline）全部通过。
- 本轮未重跑整个历史大套件，不能把定向通过说成全部历史测试已绿。

新测试在 -Os/-O2 下验证：正常载入旧 70 rpm 配方；仅 RAM 目标改 240、其他字段及模拟存储字节不变；SAVE 不触及后端；241/300 rpm 配方目标被拒绝；240/300 配置通过 FSM 预检；正常运动可 arm；不起转仍 NO_ROTATION；保护仍关闭控制意图。编译真实速度模式限幅赋值及最终 ClampFloat，确认 ±0.60 A 输入饱和到 ±0.50 A、较小请求保持原值；同时确认 FSM config 和 ControlIntentPort 都为 0.50 A，直接 IQ 仍 0.20 A。预处理对比只允许 SPEED 上限常量改变，关键控制数学、PI 参数和保护函数未改，profile 不截断，错误组合编译失败。

镜像身份：

- 新 A BIN `foc2_app_a/build/Tightening240rpmCandidate/foc2.bin`：`478715341f0b6e52e58a9a2c5ff818257369f4e0c82fa76a40d7bede0076443d`
- 新 A ELF：`824aa4c535342cb8249ae1538e1b9e71c0769cc467a3f8f361aba98d161852ee`
- 原 A CommonMode BIN：`814d6254a29dfe186309f35b00a8dc1752a597f6bc8b51f2254f19dff03fa886`
- 原 B CommonMode 交叉构建 BIN：`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。这不是板上 B 的替换镜像，本轮未写板。

当前 0.50 A 版日志：`tmp/rundown240-500ma-build.log`、`tmp/rundown240-500ma-regression.log`。此前 `rundown240-build.log` / `rundown240-regression.log` 仅对应 0.40 A 历史候选。候选尚未上板，未取得新 FOC 耗时、CCR margin、速度跟踪或机械安全证据。

## 后续人工板测准备（尚未执行）

新增 `tools/rundown240_speed_board.py`，精确锁定上面的 0.50 A BIN/ELF 和已保存 B733 全 Flash 基线（SHA256 `3a6f471f59b05e55183ed6e8e5e70d0f8247affcd33e8779b3ca60fea92f387e`）。默认只验证文件，不打开设备；分开进行 drive-OFF 非活动 A 暂存/完整独立回读、人工上电后的正常 A/B 试运行确认/校准/时序预检、一次最多 2 秒原 START、drive-OFF 恢复 B 并停在应用入口。

不更改旧 20 rpm 脚本或绕过其身份锁；不保存配方、不注入 CONTACT、不重复 START、不自动重试。候选必须报告 `RPM=240` 且 RAM 配方为 240；不匹配则拒绝 START。原 board 12 秒独立 lease 和保护未改，2 秒是主机 STOP 观察窗口。开始前等待本次实际电源和现场状态，结束后关输出并保存 Flash/RAM/串口证据；没有新运行收据不能声称已完成测试。

`tests/test_rundown240_speed_board.py` 的 6 项新增离线/模拟设备测试通过：精确镜像/基线、默认不连接设备、物理状态门控、旧 profile 拒绝、预检失败仍抓取且不 START、运行故障只发一次 START 并停止、稀疏日志不能用单个速度峰值充当持续跟踪（其中最后几项按测试方法分组）。此阶段仅通过串口枚举确认 COM5 在列表中，没有打开串口或调试器。

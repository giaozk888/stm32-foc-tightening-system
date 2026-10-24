# 0.105 A 库仑摩擦补偿：空载 OFF/ON 上板对照

## 条件与实现

用户确认 12 V 关闭、MCU 供电、空载固定、原动力线和信号接线不变，
现场可立即断电。每轮另行确认 12 V 开启、限流 0.5 A、无报警后执行。
沿用 240 rpm、Iq 指令总限幅 +/-0.50 A、300 rpm 独立超速、20000 度行程、
8 秒 rundown 和 12 秒独立 lease。全部既有保护、PI、S-curve、FF 保留。
没有工件，不强制 CONTACT，不将 RUNDOWN_TIMEOUT 计为拧紧 OK。

两轮使用同一 `Tightening240rpmFriction105OnCandidate` 镜像，RAM 命令只切换
FRIC OFF/ON。I_FRIC=0.105 A、deadband=2 rpm，FF ON/Ka=0.0001875。
BIN `3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`；
ELF `362662765bc56615f6d264e1356eeae9585603ecbf0693ca960cdbdb44cad406`。
0.105 A 来自探索性模型，不是已经通过完整标定的 breakaway 电流。

新增 `tools/friction105_fsm_board.py` 独立校验精确镜像/ELF/编译参数及
B796 完整 Flash 基线，不绕过旧镜像身份检查。复用原单次 START/校准/
自动确认复位/时序/栈/状态机/安全停机流程。
公共 runner 仅将 host 预期摩擦电流和收据字段参数化，默认仍为 0.20 A；
新 wrapper 显式选 0.105 A，启动前读回 I_UA=105000，否则不发 START。
没有改固件控制算法或保护。

离线：3 项 wrapper/gate 测试和原 runner 14 项测试全部通过。
本轮候选此前的 3 项参数/控制冻结测试与原 FR1 8 项测试已通过。

## 收据

- OFF 暂存/独立回读：`tmp/friction-fsm-stage-1792494452224362100.json` PASS。
  仅写非活动 A；B/boot/private/metadata 不变。
- OFF 运行：`tmp/friction-fsm-run-1792494492969011900.json`。
  一次 START，8000 次外环更新，RUNDOWN_TIMEOUT/CONTACT=0/FLT=0。
- OFF 后关闭 12 V 恢复 B：`tmp/friction-fsm-restore-1792494556887126100.json`
  PASS，confirmed B800、pending=0，B 应用未运行，输出关闭且 MCU 停住。
- ON 准备：`tmp/friction-fsm-stage-1792494584853316300.json` PASS。
  同一镜像无需重刷，独立回读通过，尚未激活时才通知上电。
- ON 运行：`tmp/friction-fsm-run-1792494625353182000.json`。
  一次 START，8000 次外环更新，RUNDOWN_TIMEOUT/CONTACT=0/FLT=0。

原始 UART、tokenized 线载荷及匹配 ELF 主机解压结果、停机 Flash/RAM 均由
原 runner 保存，不使用稀疏 STATUS 代替全程 1 kHz owner aggregate。
## 结果

两轮约 8 秒，全部为正向空载；均自然 RUNDOWN_TIMEOUT，未形成真实接触。
runner 因其不是拧紧成功而保留 STOPPED/FAIL 和 `phase=aborted`，
这不是电流/编码器/时序故障，也没有被篡改为拧紧 OK。
两个 `fsm_observation_complete` 均完成，Flash/RAM/安全关断证据完整。

|指标|FRIC OFF|FRIC ON（0.105 A）|
|---|---:|---:|
|起转延迟|436 ms|182 ms|
|低速 MAE（2<abs(ref)<=30 rpm）|13.164 rpm|8.281 rpm|
|匀速 MAE|4.089 rpm|3.739 rpm|
|加速段 MAE|20.795 rpm|14.212 rpm|
|全程最大速度误差|75.129 rpm|81.782 rpm|
|参考到达目标后的定向过冲|6.213 rpm|6.013 rpm|
|最后建立稳定窗口时间|7.620 s|7.276 s|
|speed integrator 绝对峰值|0.163 A|0.057 A|
|Iq_PI 绝对峰值|0.374 A|0.284 A|
|总 IqRef 指令绝对峰值|0.411 A|0.426 A|
|软件 Iq 反馈采样绝对峰值|1.340 A|1.266 A|
|饱和累计|0 ms|0 ms|
|FOC wall max|31.571 us|31.576 us|
|50 us deadline miss|0|0|
|actual CCR commit|298702|298696|
|actual CCR late|0|0|
|actual CCR 最小余量|15.141 us|15.141 us|

表中 UART 指标为整数缩放后的截断值。RAM 起转分别 436.029/182.040 ms，
IqRef 峰值 0.411632/0.426648 A，积分峰值 0.163623/0.057189 A。
两轮低速窗口只有约 0.186 秒，匀速窗口约 6.601 秒；稳定带沿用原
max(2 rpm,目标5%) 并保持 250 ms 的证据规则，不是工业精度认证。
减速阶段的连续 owner 统计没有覆盖（DEC_MAE=-1），不能填为 0 或宣称改善。

起转时间本轮约减少 58%，低速 MAE 约减少 37%，匀速 MAE 约减少 9%，
积分器峰值约减少 65%。与此同时全程最大瞬时误差上升约 8.9%，
总 IqRef 峰值上升约 3.6%；因此不能称所有指标改善。
只有一次 OFF/ON，初始转子位置/温度等自然差异未消除，不能作统计普适结论。
反向 N=0，正反向一致性未验收。

反馈电流峰值为软件采样估计，不是独立电流仪实测，也不是平均电流。
0.50 A 约束的是 IqRef 指令，不代表原码/估算相电流始终低于 0.50 A；
本轮不因此改阈值、滤波或保护。零点两轮均 1561/1564、valid=4000，
reject=52/44。MotorControlTask 预检剩余栈 2552/2520 B，各 6 次观察通过。

机器可读对照：`tmp/friction105-off-on-comparison.json`，由原离线
`friction_compare.compare()` 处理两份同参数完整 metric 回复，另存 FF owner 指标
（FF 两轮始终 ON，未冒称 FF ON/OFF 对照）。

## 最终恢复

用户确认关闭 12 V 后，仅恢复原 B 启动选择：
`tmp/friction-fsm-restore-1792494698352284100.json` PASS。
confirmed B804，pending=0，B length=227964 / CRC=627317606，原 B 字节未变。
A/B 应用和私有区均不因恢复改变，仅合法 boot metadata 更新。
全 Flash SHA256：`0688e4b2e7eea4d0a4ea12684df974416eb7924230f7cafb7ab615a0eb26fd02`。
VTOR=0x08040000，SD=0、BDTR=0、CCER=0、CPU halted，停在 B 入口，
B 应用未运行，恢复期间 motor_commands=0。不再启动或自动增加补偿。

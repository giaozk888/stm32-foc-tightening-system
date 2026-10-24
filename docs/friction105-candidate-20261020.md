# 探索性 0.105 A 库仑摩擦补偿候选 A

## 改动边界

用户要求将刚采集的摩擦电流接入算法作效果对照。本次取探索性库仑项
0.104919 A 的圆整值 **0.105 A**，不把这个估计宣称为正式标定结果。
仅增加候选 A configure/build presets，不改公共算法源代码、正式 B、旧 0.20 A
候选或已有诊断镜像，不写持久化参数，不刷板、不发送 START。

- `Tightening240rpmFriction105OnCandidate`：继承原 FR1 ON，I_FRIC=0.105 A。
- `Tightening240rpmFriction105OffCandidate`：相同参数、FRIC 默认 OFF。
- deadband 保持 2 rpm；FF、S-curve、speed PI anti-windup 保持现状。
- 不加入本次探索拟合的黏性项 `0.000225 A/rpm`，一次只验证库仑项变化。
- 使用原 tightening FSM，不启用 calibration 独占 owner。

## 现有算法接入位置（未改）

`iq_fric = abs(speed_ref) > 2rpm ? 0.105A * sign(speed_ref) : 0`

`iq_raw = iq_pi + iq_acc_ff + iq_fric`

`iq_ref = clamp(iq_raw, -0.50A, +0.50A)`

现有 anti-windup 基于 PI、加速度 FF 和摩擦项的总输出做积分准入；补偿不能绕过
Iq 限幅。位置模式不使用该速度模式补偿；FRIC OFF 与原加速度 FF 路径一致。
0.105 A 是前馈项，不是固定强制 Iq，也不是运行相电流的硬上限。

## 构建与证据

两候选均链接成功，Flash 217420/229376 B。
ON RAM 129152/131008 B，OFF RAM 129160/131008 B；RAM 余量很小，板测仍需栈预检。
已有 unused 和 RWX warning 保留。未改动任何控制函数，预处理回归确认唯一
有意差别为速度输出调用中 Coulomb 参数 `0.20f -> 0.105f`。

ON BIN SHA256：`3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`

ON ELF SHA256：`362662765bc56615f6d264e1356eeae9585603ecbf0693ca960cdbdb44cad406`

OFF BIN SHA256：`5368dd857089f5d349c8fadd030a7368c38ce3c179e3f03114d8bb1719d0b595`

3 项新回归覆盖：正反向/死区/合并限幅/anti-windup/OFF 等价性，控制与保护函数
冻结检查，真实构建参数/日志 tokenization/旧 A 和 B 镜像哈希不变。
原 FR1 8 项回归另行运行。日志在 `tmp/friction105-tests.log`、
`tmp/friction105-existing-tests.log`，构建日志 `tmp/friction105-*-build.log`。

原 0.20 A A BIN 保持：
`c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8`。
原 B build BIN 保持：
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。

## 待人工上板对照

本次没有实测效果，不能把编译/host 测试结果当作起转/速度改善证据。
板端仍为前次恢复的 B796，MCU 停住且输出关闭；本次没有触碰硬件。

建议沿用 240 rpm、空载固定、12 V/0.5 A、Iq 总限幅 +/-0.50 A、300 rpm
独立超速、8 秒 rundown /12 秒 lease、20000 度行程和全部既有保护。
先 OFF 再 ON，使用同一 0.105 A 镜像、只在 idle/output-off 时 RAM 切换；
无工件不能把自然 RUNDOWN_TIMEOUT 当作拧紧 OK。

上板前需要为**新镜像和 B796 baseline**更新独立 pinned runner，并经离线 mock
测试，不能直接改旧 runner 的哈希来绕过镜像检查。原
`tools/friction_fsm_board.py` 明确只接受 0.20 A，不可直接用于新镜像。
每次 motion 前都要读回 `MOTOR TEST FRIC STATUS`，核验 I_UA=105000、
DB_MRPM=2000、FF_ON=1 和所有原 profile/保护/栈/时序前置条件。

比较起转延迟、低速/匀速 MAE、过冲、稳定时间、积分器与 Iq_PI 峰值、总 Iq
指令/测量峰值、饱和时间以及 FOC deadline/CCR late。使用匹配 ELF 解压既有
Pigweed tokenized FRC R/C/I 日志。硬件保护失败立即停止，不自动重试或升流。
如只做正向，必须明确反向效果尚未验收；拟合值尚不能认定为 breakaway 电流。

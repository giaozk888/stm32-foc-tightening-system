# 机械辨识高转速诊断 A：500/600/700/800 rpm 各三次

## 人工授权与范围

用户明确要求超速阈值 1000 rpm，500、600、700、800 rpm 各三次，并确认机械机构允许 800 rpm。另行确认仅诊断 A 的行程上限改为 30000°，12 V 关闭、MCU 供电、空载固定/转轴解锁/防护/接线不变、电源限流 0.5 A、整组现场可立即断电。

- 仅新预设 `MechanicalIdentificationHighSpeedCandidate`，默认关闭；不改正式 B。
- 精确命令白名单只允许正向 500/600/700/800 rpm，拒绝负向、其他转速和普通 START。
- 固定顺序 500×3 → 600×3 → 700×3 → 800×3，各段一次 boot / 一次命令；无故障重试、自动升流、自动模型应用或 DOB 控制。
- 独立保护、身份/快照/关断证据或预检失败立即中止；仅数据/拟合质量失败继续保存后续段。

## 配置

Ka=`0.000046875 A/(rpm/s)`，有效 BEMF ψ=`0.00034866 Wb`，摩擦补偿 0.105 A，Iq ±0.50 A，电压矢量上限 1.60 V，current/speed PI 与 S-curve 参数完全不改。

仅高转速诊断的速度 API 上限 800 rpm，两处原超速保护共用 1000 rpm 阈值；普通预设仍是原 API / 300 rpm 或既有 PSI 专用 500 rpm。

命令速度从启动起保持 5 秒（包含 S-curve 加速），之后命令零速。原加速度 200 rpm/s、jerk 1000 rpm/s²，500/600/700/800 rpm 理论加速分别 2.7/3.2/3.7/4.2 秒，减速相同。原 7 秒 task 关断不足，因此仅高转速诊断 task 最晚关断改为 10.5 秒；host 上限 11 秒，原 ADC/TIM7 独立 12 秒 lease 不变。

理想完整加减速总行程分别约 15000/18000/21000/24000°，因此采用人工批准的 30000°上限。高转速任务使用实际 `encoder_position_deg-start_angle` 检查，持续覆盖减速阶段；不依赖 5 秒后停止更新的旧 plateau 统计。其余保护完全保留。

新增只读 `MOTOR TEST MECH LIMITS`，host 启动前必须读回 API=800、TRIP=1000、IQ_LIMIT=500mA、TRAVEL=30000、DRIVE=5000ms、STOP=10500ms、LEASE=12000000us，否则不发送运动命令。

## 记录和拟合限制

原 128×64ms 同步电流/速度窗口保持不变（约 8.2 秒），覆盖完整加速和部分减速；800 rpm 的完整减速尾段不全在 RAM 窗内，关断/时序/保护另有全程快照。禁止声称记录了全程每个采样点。

所有原始数据与质量失败窗口保留，不按残差挑样本，不自动提高电流/电压。500~800 rpm 的电压或 Iq 饱和也作为质量信息记录，不能为了凑转速扩大限幅。

本批是**仅正向**，`sign(omega)` 和常数列共线，单靠这 12 段不能独立分离库仑摩擦和电流偏置；原四参数拟合会如实拒绝。后续可以把先前正反向六段作为明确标注的跨批次参考进行离线核验，但不把旧数据当新测、不自动资格化 J/B/Kt。

## 构建

- BIN/Flash 208436 B；RAM 128776/131008 B，heap/stack 未缩减。
- BIN SHA256 `442cef6ca8476b15e99e373b01394f881672e89fb5a2ff5a176323e0e3fcec1e`。
- ELF SHA256 `22cf6efdeb090b2358c2f6d29942b68cd10601c87455160ead4dbbc1eef65490`。
- 新旧诊断 main 语法检查的 warning 集合相同，保留已有 unused 和 RWX 警告；无新增类别或编译错误。
- 专项/机械模块回归 24 项通过，包含实际 S-curve C 代码完整加减速、白名单、1000rpm/30000°边界、同一电流环/使能 owner、相同 IRQ/ADC/encoder/zero/FSM 对象、正向不可辨识拒绝、powered/OFF 门禁。
- 原普通低速六段脚本默认行为和历史二进制身份保留，只参数化数量/诊断限时/可选只读 limits 查询。

## 执行与恢复

`tools/mechanical_high_speed_board.py` 默认仅文件核验。

1. 新 A 通过测试后，12 V 关闭条件下 `--prepare-off --drive-off-unlocked-no-load-fixed`，精确核验上次原 B 恢复 receipt，再只写非活动 A 并独立完整回读。
2. 暂存不激活，另行人工确认已上电/无报警/整组现场后，`--execute-twelve <stage> --operator-present-whole-batch-drive-on-no-alarm-05a`。
3. 每段正常校准、真实时序预检、零速检查、唯一显式 MECH 命令、原 STOP/ANALOG SAFE、完整 Flash/RAM/保护证据；故障不重试。
4. 最终确认输出关断/CPU halted，提示人工关闭 12 V 后，使用实际最后 child receipt `--restore-b-drive-off`；恢复原 B 选择，不运行 B。

相关回归合计 **143 项通过**：机械/高转速专项 24、原 FCAL 23、BEMF 8、speed 系列 88。

## 已完成暂存，尚未运动

`tmp/mechanical-ident-stage-1792671010076792900.json` PASS：只写非活动 A，独立完整回读通过；原 B/boot/private/元数据未改，activation=false、motor_commands=0，SD/MOE/PWM 关闭、CPU halted。计划精确包含 500/600/700/800 各三次，TRIP=1000、TRAVEL=30000、Ka=0.000046875。

尚未执行高转速板测；等待另行实际上电/无报警/全程现场确认。

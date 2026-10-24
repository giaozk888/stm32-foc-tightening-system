# 机械参数辨识：六段空载采集计划

## 明确数值，不再用倍率代替 Ka

- `Ka = 0.000046875 A/(rpm/s)`。
- `psi_effective = 0.00034866 Wb`，BEMF ON。
- 摩擦补偿 0.105 A，速度参考 deadband 2 rpm；current PI、speed PI、S-curve、统一电压/Iq 限幅与全部独立保护不变。
- DOB 不进入控制，结果不自动写 PI/模型或正式 B。

## 本轮运行计划

固定顺序 **+100、−100、+200、−200、+240、−240 rpm**，各一段。每段沿用已存在的受保护单次速度诊断 owner：5 秒目标速度（包含原 S-curve 起步），随后命令 0 rpm，由原 S-curve 减速；原 7 秒强制关断界限与 12 秒独立 lease 都保留。

通过独立编译选项 `FOC_MECHANICAL_MOTION_DIAG` 复用 FCAL 的启动/停止路径，而不是重新实现功率使能。与历史摩擦标定模式的差别仅为：固定保持 FRIC ON/BEMF ON，严格白名单支持六个 MECH 命令，旁路采集包含加速/稳态/减速。旧 FCAL 命令、FRIC OFF 约束和普通预设不变。

命令 `MOTOR TEST MECH RUN POS|NEG 100|200|240` 仅允许六种完整字符串；一段一 boot、单次使用，运行中/输出开启/请求排队/状态未就绪拒绝。普通 START 不会自动运行机械辨识。没有自动故障清除、自动重试、升流或参数 SAVE。

每段重新校准和时序预检，START 前要求实际 CTRL/DET 转速均不超过 ±2 rpm、IDLE、无故障，之后只发送一次 MECH 运行命令。一次独立保护、反馈/关断证据异常立即中止整组；纯拟合质量差在采集结束后如实报告，不为通过而删残差或改阈值。

## 数据与可辨识范围

同步 ADC/encoder 二进制 capture 和离线工具沿用 `mechanical-identification-dob-candidate-20261022.md`。输出 J/Kt、B/Kt、Tc/Kt 和 bias；没有独立 Kt 标定时，绝对 J/B 和独立 Kt 不伪造。当前有效 BEMF 前馈系数不当作物理 Kt。

`LEGACY_FCAL_PASS` 是复用结构里历史 FRIC OFF 稳态计数判据的诊断字段，本模式 FRIC ON，不能拿它作为本次机械拟合成功/失败判据。采集资格以原保护、关断证据、完整 RAM/哈希判断，参数资格以同步 capture 的全部有效窗口、条件数、残差、双窗和留出验证判断。

## 构建和测试

- 预设 `MechanicalIdentificationMotionCandidate`。
- BIN 208288 B，Flash 剩余 21088 B；RAM 128776 B，静态余量 2232 B；heap/线程栈没有缩减。
- BIN SHA256 `55551e57859c6b46a718fe1b61a5cf0f42dcb60ec02b939e1c34ec70fb38d5a5`。
- ELF SHA256 `913902c8e0c5f0c61e5b60c4dc86a721142262cb472b7f233e3aa869c89d573b`。
- 150 项定向测试通过：机械模块/候选/板测脚本 18、历史 FCAL 8、历史 FCAL 板测脚本 15、BEMF 8、Ka025 11、flux gain 9、speed 系列 81。
- 单次使能仍由原 `LatestOriginal_Admit` 拥有，保留原队列/启动检查和 PWM invalidate；没有第二条直接写门极路径。主 FOC 电流环和 IRQ/PWM/guard/encoder/zero/FSM 对象与被动采集候选一致。
- 相比正常采集构建，诊断替换常规 TighteningTask 后多出 9 个未使用函数符号告警；告警类别仍为已有 unused-function，另保留已有 RWX 链接告警。没有用屏蔽告警选项掩盖，也没有编译错误。
- `tools/mechanical_identification_board.py` 默认仅文件核验；真实执行必须给明确 powered/全程现场确认。脚本不使用倍率或历史 Ka 身份代替本次固定 Ka 数值。

## 当前板端准备状态

用户已确认 12 V 关闭、MCU 供电、转轴解锁/负载脱开/空载固定/防护和接线不变、限流 0.5 A、全程在场可立即断电。

断电准备 receipt：`tmp/mechanical-ident-stage-1792669380405063200.json`，PASS；只写非活动 A，完整独立回读通过，B/boot/private/元数据未改，activation=false、motor_commands=0，输出关闭、CPU halted。

此文为准备状态，不是已执行六段或辨识出参数。须另行确认实际上电和无报警后才能激活；校准/时序预检失败不发送运动命令。完成后人工关闭 12 V，再恢复原 B 启动选择。

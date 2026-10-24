# 240 rpm / ±0.50 A / 20000° 行程候选

后续板端更新：已尝试正常启动，但在 5 秒健康窗内因 CURRENT_INVALID（连续 unresolved=3）中止，START=0，没有电机运行结果。用户断 12 V 后已清理 pending A、恢复原 B744 并停在入口。见[本次启动中止记录](travel20000-preflight-abort-20261020.md)。下文“尚未激活”等描述保留为准备/暂存阶段的历史状态。

按用户明确请求将本轮空载实验的行程上限改为 20000°（55.56 圈）。单独 A preset `Tightening240rpmTravel20000Candidate` 继承原 240rpm 候选，默认关闭的子开关 `FOC_RUNDOWN240_TRAVEL20000` 只能与该 protected intent FSM 一起启用。

本轮仅新增候选行程范围、默认值和启动 RAM 覆盖：

- 新候选 `MAX_TRAVEL_DEG` 默认及允许最大值为 20000，20001 被拒绝。
- 正常配方及原 240rpm 候选仍为默认 3000、允许最大 10000；原固件哈希不变。
- 从正常 KVS 载入后只将新候选 RAM 的 rundown_rpm=240、max_travel_deg=20000，dirty=1；其他字段不改。
- 继承 RAM-only/SAVE 禁止策略，72 B 配方和 96 B 存储 ABI 不改，扩展范围不会写入 B 共用配置。
- 原目标 240 rpm、SPEED Iq 上限 ±0.50 A、超速 300 rpm、参考斜坡 200 rpm/s、rundown 8 秒超时、12 秒 board lease 均不改。
- PI、电角零点、相序、采样、CURRENT_INVALID/CUR_CONFIRM、硬过流、encoder/timing 保护、IRQ、PWM pipeline 和状态机控制逻辑不改。

20000°不是无限行程：到达仍走原停止路径。在本轮 240 rpm / 8 秒空载范围内，原 8 秒时间边界预期先到；按恒定 240 rpm 计算 8 秒为 11520°，加入从静止理想斜坡后为 10656°。即使按 300 rpm 做 8 秒行程预算也只有 14400°。这些是实验预算，不是机械安全保证或正式螺钉配方。

空载不强制 CONTACT/OK；原 TIGHTEN/HOLD 配方和直接 IQ 限幅不变。现有状态机仍把 rundown 时间/行程边界统一报告 TIMEOUT，本轮未改该映射。

## 离线与编译

- 新 A 编译通过：Flash 228620/229376 B（余 756 B），RAM 128808/131008 B（余 2200 B）。不是新运行期任务栈验收。
- 原 A `Tightening240rpmCandidate` 和 B `TighteningCommonModeCandidate` 重编译通过，BIN 保持逐字节一致。
- 告警集合与原 A 相同（既有未使用函数与 RWX linker 告警），未新增告警。
- 真实 C 状态机在 -Os/-O2 下验证：20k 配方/启动 RAM 覆盖、SAVE 拒绝、默认及原候选拒绝 20k、8 秒超时保留、20k 行程边界保留、模拟接触后完整状态流程不变。
- 预处理对比证明控制、保护、状态机和 PWM 关键函数与原 240rpm 候选一致；只有启动配方覆盖新增 max_travel_deg 字段。
- 新 `tools/travel20000_fsm_board.py` 精确锁定新镜像与 B741 基线，默认仅查文件。分开的 drive-OFF stage、人工上电 run、drive-OFF restore；只写非活动 A、完整独立回读，执行前须读回 RAM `240rpm / 20000deg / 8000ms`，否则拒绝 START。
- 脚本仍只发一次原 START、不自动重试、不 SET/SAVE、不强制 CONTACT；无电机/扭矩仿真成功宣称。
- 原配方兼容性、存储兼容性、x2 offline 的 3 项 CTest 通过。
- 最终 46 项定向回归全部通过，覆盖新增候选/脚本、原 240rpm 配置、FSM、共模、CUR_CONFIRM、稳健零点及 closed-loop pipeline；不是整个历史大套件。

镜像：

- 新 A BIN `foc2_app_a/build/Tightening240rpmTravel20000Candidate/foc2.bin`：`585410c17c75142dc07db3a6b6567500a212b167435f108a59b3b4364f2c2325`。
- ELF：`1f415f740be09af66f4c409fb87a0bd2c68e7b779cbd0a67e905077144580b87`。
- 原 240rpm A BIN 仍为 `478715341f0b6e52e58a9a2c5ff818257369f4e0c82fa76a40d7bede0076443d`。
- 原 B 交叉构建 BIN 仍为 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，本轮未覆盖板上 B。

## OFF 暂存完成，尚未激活

用户确认当前 12 V 关闭、MCU 供电、空载固定且接线不变、人在现场可断电后，仅写入非活动 A。

- 收据 `tmp/travel20000-fsm-stage-1792459488632591300.json`。
- 完整 Flash 回读及独立复核通过，B741 启动元数据、B 应用、bootloader、私有配置不变。
- 暂存全 Flash SHA256：`327f99bf2615d5839f5a273ed73f1d4b8730b267b91aaba57d8b5867b3582e77`。
- activation=false，motor_commands=0，SD/MOE/CCER=0、MCU halted。
- 等待人工上电并确认无报警后，才正常提交 A/B 试运行和进行一次状态机观察。此记录不声称新版本已运行或完成验收。

本轮日志：`tmp/travel20000-build-20261020.log`、`tmp/travel20000-regression-20261020.log`、`tmp/travel20000-specific-tests-20261020.log`、`tmp/travel20000-final-regression-20261020.log`。只报告本轮选择的相关测试，不声称整个历史大套件已通过。

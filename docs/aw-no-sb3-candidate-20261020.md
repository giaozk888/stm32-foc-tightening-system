# AW0：关闭 SB3 的单变量对照候选（2026-10-20）

按本轮请求，在 AW1 上单独编译去掉 SB3 的快速转矩制动上限及其积分跟踪事务。不是关闭所有制动，也不是关闭超速保护。

## 唯一控制变化

- 独立 A preset：`Tightening240rpmAwNoSb3Candidate`，继承 `Tightening240rpmSpeedAntiWindupCandidate`。
- 新开关 `FOC_SPEED_SB3_DISABLE_CANDIDATE` 默认 OFF，要求完整 AW1/intent/100-40 保护候选；B 无此选项。
- `FOC_EncoderSpeedUpdate` 不再调用 `SpeedBrakeTrack_Apply`，因此不再依据连续两次瞬时速度给出额外电流制动上限，也不执行该分支的积分回算。
- 原 SB3 构建依赖标志保持，用于不改动已有配置契约；其快速控制调用已编译消失，不是只改标识。其无输出作用的 reset 路径未另外改写。
- 原速度 PI 的正常正/负输出、AW1 积分接纳、SB2 卸载和上升速率、参考斜坡保留。
- 300 rpm 独立故障停机、硬过流、编码器/时序保护、CUR_CONFIRM、100/40/25/3、PWM pipeline 和 FSM 不变。
- 240 rpm、速度 Iq 上限 ±0.50 A、电压 1.6 V、20000°、8 秒 rundown、12 秒 lease 均不改。不接入 S-curve。
- `MOTOR TEST PROFILE` 使用等长 `SPEED_CTRL=AW0`，避免旧 AW1/SB3 测试脚本错认新镜像。

## 构建身份与验证

新 A 编译通过：Flash 228492/229376 B（余 884 B），RAM 128800/131008 B。最终无新增 warning 类型，既存 unused/RWX 警告仍在。

BIN SHA256：`d3fa11b83686b2b31c551088fdcf2d0a9872fbfd0fb50a52190075a31ecf291a`。

ELF SHA256：`2fb591882b2ab668802129dd716d66c68b7349dc4d8e47bd899ac1db463bfd90`。

预处理后的完整外环仅少原 SB3 Apply 块；AW helper、SB2、FOC 数学、保护、状态机等冻结函数相同。ADC timing 与 IRQ 对象逐字节一致。参数宏只新增关闭 SB3 的特性开关。

真实应用 PI 提交代码的 Os/O2 测试证明：同样两次瞬时超速输入下，旧 AW1 仍执行 SB3 制动，新 AW0 不再有该额外上限；AW 的输出/积分限幅仍有效，POSITION 旧行为不变。此离线对照不是电机稳定性仿真，不保证实际不会超速。

49 项定向回归通过（约 36.8 秒），含新单变量 4 项、板测脚本 8 项和既有 AW/100-40/CUR_CONFIRM/零点/pipeline/FSM 回归。日志：`tmp/aw-no-sb3-regression-20261020.log`。

## 单次空载上板准备

脚本 `tools/aw_no_sb3_fsm_board.py` 固定本镜像及原 B756 全 Flash 基线，默认只读文件。断电时仅写非活动 A、独立回读，保留 B/bootloader/私有配置。上电后正常健康确认、校准、时序与 AW0/100-40 profile 预检通过才发一次 START，不清故障、不 SET/SAVE、不强制 CONTACT、不自动重试。

运行观察完整空载 rundown，受原 8 秒时间和 20000° 行程限制，主机最终 11.95 秒停止窗口及 300 ms 反馈丢失停机仍保留。原 300 rpm 独立超速可随时抢先停止。结束锁定输出并停住 MCU，待人工确认关闭 12 V 后恢复原 B 启动选择。

不以峰值变高单独判稳定，需比较稳态误差、周期性掉速、电流、deadline 与实际 CCR margin。若触发独立保护，不放宽阈值或自动再试。

本轮用户确认 12 V 关闭、MCU供电、空载固定后，仅完成暂存与独立回读，收据 `tmp/aw-no-sb3-fsm-stage-1792467574342869800.json`，PASS。原 B756、bootloader、私有配置和启动元数据未变，输出关闭、MCU停住，尚未激活或 START。

后续一次人工供电实测已完成，见 [AW0 实测对照](aw-no-sb3-fsm-board-20261020.md)。同窗口平均 236.99 rpm、deadline/CCR late=0，无保护故障；已断 12 V 并恢复原 B760。单次结果不等于长期稳定认证。

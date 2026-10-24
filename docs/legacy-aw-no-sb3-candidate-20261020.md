# L00：撤销新增 AW1，SB3 保持关闭的对照（2026-10-20）

用户请求“去掉 speed PI anti-windup 做对照”，本轮先明确并获确认：只撤销本次新增 AW1 边界积分接纳，恢复历史速度 PI 分支，保留原有条件积分和 ±0.35 A 积分夹紧。不是关闭全部 anti-windup，更不是关闭保护。

## 配置

- 新 A preset `Tightening240rpmLegacyAwNoSb3Candidate`，继承 AW0，`FOC_SPEED_PI_ANTI_WINDUP=OFF`、`FOC_SPEED_LEGACY_AW_COMPARE=ON`。
- `FOC_SPEED_SB3_DISABLE_CANDIDATE` 继续 ON；原 SB3 快速制动分支仍不执行。
- `MOTOR TEST PROFILE` 标记 `SPEED_CTRL=L00`，不可与 AW0 混用；脚本同时检查编译命令没有新 AW1 宏。
- 宏依赖只允许完整 100/40 protected intent 配置下的单独 A 对照，B 不增加选项。
- 240 rpm、Iq ±0.50 A、速度 PI Kp/Ki、SB2 积分卸载/上升速率、原速度参考斜坡不变。
- 300 rpm 独立超速、硬过流、CUR_CONFIRM、CURRENT_INVALID、编码器/时序保护、100/40/25/3、电压限幅、PWM pipeline、FSM 和 A/B boot 均不改。
- 20000°、rundown 8 秒、板端 lease 12 秒、主机最终 11.95 秒停止窗口不变。
- 不加 S-curve、摩擦补偿或前馈。

## 精确控制差异

原 AW0 在 SPEED 中以 `SpeedPiAntiWindup_Apply` 部分接纳到饱和边界，再从已提交积分计算电流。本 L00 仅去掉该选择，完全回到历史分支：以 P+I_candidate 限幅得到 Iq，仅当未饱和、退饱和或原 bleed 时提交积分。

因此两版在未饱和时可能完全一致，在首次跨越饱和边界、以及积分提交时可能不同。不能预设本次会有明显速度变化。SB3 两版都关闭，使它不成为混杂变量。

## 编译和离线证明

新 A Flash=228140/229376 B、RAM=128800/131008 B。BIN SHA256 `a17b269968b0e58bd7df9f2741ffe7552da5e971d5f9aa8a4f319439798d7324`；ELF SHA256 `7bf89abef6fa17b60fa9db94d4cd0150b120e5ff52f2f51fdd1aafcc14e330e6`。

专项测试执行真实预处理后的速度 PI 提交代码（Os/O2），确认部分饱和边界上的 AW0/L00 差异、正常区间/POSITION 一致、历史条件积分和原限幅仍生效。完整外环仅删除新增 AW1 分支，其他 FOC/保护/FSM 冻结函数一致，ADC timing/IRQ 对象逐字节一致。只移除新 AW1/头文件宏并新增显式对照宏，参数宏不变；未新增 warning。AW0/B 镜像哈希保留。

`tools/legacy_aw_no_sb3_fsm_board.py` 固定本新镜像和原 B760 全 Flash 基线，默认仅文件核验。人工确认断电后只写非活动 A、独立回读，上电后正常健康确认/校准/时序预检通过才允许一次 START，故障不重试。结束后锁定输出并停住 MCU，待人工关闭 12 V 后仅恢复原 B 启动选择。

这是离线准备，不把此前 AW0 实测的稳定性或时序数值当成本镜像已测结果。

后续单次人工空载实测已完成，见 [L00 对照记录](legacy-aw-no-sb3-fsm-board-20261020.md)：同窗口平均 236.15 rpm（AW0 为 236.99），FOC max=31.81 µs、deadline/CCR late=0，无保护故障；已断12 V、恢复原B764并停在入口。原有历史条件积分仍保留。

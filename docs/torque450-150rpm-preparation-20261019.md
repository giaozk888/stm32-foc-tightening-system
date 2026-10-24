# 0.45 A / 5 秒：仅诊断超速门槛改为 150 rpm，暂存未激活

2026-10-19，用户补充上次肉眼“转了一下”，并明确要求将速度上限改为 150 再试一次。沿用紧接上轮用户确认的 12 V 关闭状态；本阶段只有编译、测试及非活动 A 暂存，没有带电启动。

## 变更范围

- 新增默认关闭 `FOC_TORQUE450_150RPM`，仅允许与专用 `FOC_TORQUE450_FIVE_SECOND` 同时启用；其他构建仍为原 60 rpm trip。
- 独立 preset `Torque450mA150rpmFiveSecondDiagnostic` 继承 450mA profile，只启用该比较开关。
- `CL_OVERSPEED_RPM` 在该 profile 中为 150；同一原速度判据、双向绝对值和关断路径保留，不提供运行时任意改阈值入口。
- 状态响应明确新增 `RPM_LIMIT=150`，主机同时核对编译定义、BIN/ELF hash、运行时状态，避免拿旧 60rpm 镜像测试。
- 固定 IqRef=+0.45 A、IdRef=0、绕过速度/位置环，最大 lease 5s、每启动一次、不自动升流/重试。
- 150 rpm 是超速保护门槛，**不是速度设定或恒速闭环**；固定电流空载仍可能很快加速至该门槛，保护可以早于 5 秒停止。
- 本轮仅获准改变这一诊断超速阈值；hard-current=4A、CUR_CONFIRM、CURRENT_INVALID、encoder stale、ADC/FOC deadlines、PI、SVPWM、方向、相序、电角零点、PWM pipeline 均未改。
- 正式 B 的镜像未写入/执行；不把实验阈值推广到正式配置。

## 离线验证

A：Flash 222532 B / RAM 130000 B；B：Flash 221508 B / RAM 129984 B，两个候选均构建通过。
编译保留每槽原 12 条 unused 和 RWX 链接 warning，不称为零 warning。

- 新增 6 项通过：真实 owner 的默认60/显式150、5秒lease/STOP/fault race、默认关闭/错误组合拒绝、固定BIN/ELF/基线/波特率、预检失败不启动等。
- 原 450mA 8 项测试保持通过；本轮没有重新跑全仓 discover。
- 提取函数比较控制/保护函数体不变；唯一变化为其引用的 `CL_OVERSPEED_RPM` 常量，其他控制数学/电流限幅与原450版一致。
- 新候选 ADC timing 与 IRQ 对象仍与原450逐字节相同。
- `git diff --check` 通过。

SHA-256：

- A BIN `c78296a6028ca5737ad8fd6159fb1b06214c40d4dc967463257477510d4b9433`
- A ELF `3d5ef30a01a82106dab164167fc6bae19ab19bb7f215123477725dfa86da44cc`
- B BIN `d9c008fa48bbc1126121aec30aa9e7c2fefa8388d726d120a47fb609270d82d4`

## 板端暂存

使用精确 B721 恢复备份作为 baseline，drive-OFF reset/halt 路线，仅写非活动 A。
收据：`tmp/torque450-150-stage-1792408803159146900.json`。
完整回读、独立第二次回读通过；原 B、bootloader、私有配置和 metadata 未变。
CPU 停住，SD=0、MOE/AOE=0、CCER=0；activation=false、motor_commands=0。

下一步需用户开启 12 V / 电源限流0.5A并确认无报警，再按正常 A/B 健康确认、校准与时序预检，通过才执行一次。本阶段不能给出150rpm配置的实际运动结果。

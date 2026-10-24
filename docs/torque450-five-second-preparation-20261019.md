# 固定 +0.45 A / 5 秒：独立候选已暂存，未激活

> 下文记录初次暂存时刻的状态，不代表当前构建或板端状态。后续试运行未发 Iq 命令，发现新增 UART 配置与脚本不匹配，已恢复 B717；修正版只离线重编译。详见 `torque450-uart-preflight-abort-20261019.md`。

用户在 2026-10-19 明确要求把固定 Iq 提至 +0.45 A，并将最初准备的 500 ms 改为单次 5 秒。已经合并确认 12 V 关闭、MCU 供电、电机空载固定、接线未变、现场可立即断电。

这不是完整拧紧或转矩精度验收。此前 +0.35 A/5 s 软件 Iq 均值约 0.334 A，但用户肉眼未见转动；接线对应/磁零点仍未证明。新测试即使转动，也不能独立排除这些问题。

## 候选行为

- `Torque450mAFiveSecondDiagnostic`，默认关闭开关 `FOC_TORQUE450_FIVE_SECOND`。
- 手工唯一入口 `MOTOR TEST TORQUE450 CONFIRM`；仅正向、零额外 offset、每次启动只允许一次，不自动升流/重试。
- IdRef=0，固定 IqRef=+0.45 A，绕过速度/位置环。
- 仅此候选的 `MotorControl_SetIq` 与 outer-IQ apply 两处匹配限幅为 ±0.45 A。正式默认及其他 profile 未扩大。
- 现有独立 5000000 us lease 到期停止；不能把 host 等待时间当作关断保护。
- 保留原 hard-current、CURRENT_INVALID、CUR_CONFIRM、encoder stale、超速、timer-health、one-cycle PWM 与 CCR margin 检查。
- PI、Clarke/Park、SVPWM、相序、electrical zero=10507、encoder direction=-1、pole pairs=10 不变。
- 保留约 1 kHz 全窗口运动摘要、32 帧/200 ms 二进制 trace。解码软件角度/绝对 raw 路程时明确包括编码器抖动，不能冒充独立实轴位移。

## 构建与验证

| Profile | Flash | RAM（可用 131008 B） |
|---|---:|---:|
| A 450mA/5s | 222516 B | 130000 B |
| B 450mA/5s | 221500 B | 129984 B |

A BIN SHA-256：`19606c66da892aa60ab22558fd0dab421fbe92ec0a5830ebb7877b65c0954d6e`。
A ELF SHA-256：`22acdd20bcbe5b8fb724bb8a39a0a8099ceaac26790a9424331941f305b2b0a1`。
B BIN SHA-256：`1a6f5a2fd742af76ba06509b6e506016fa0ba71f14ffa2c677146278a9ad1430`。

编译初期遗漏了 motion 摘要的 profile include 分支，已补齐并重新构建成功；最终每个构建保留既有 12 条 unused 编译警告和 1 条 RWX 链接警告，未消除历史警告，不称为零 warning。

定向测试：新增 7 项通过、既有 350mA 9 项、angle-chain 10 项、torque-chain 5 项通过，共 31 项。未在本轮运行全仓 discover，不能声称全仓全绿。
测试执行真实 C owner/单次 admission/STOP 与 fault race/5s lease/禁止负向和其他入口；提取实际 setter/outer 验证 .45/.9 请求的匹配截断。
预处理函数对比确认，除上述两处显式直接 Iq 限幅外，选定冻结控制/保护函数相同；ADC timing/IRQ 对象与先前 350mA 构建逐字节一致。

## 暂存板端状态

- 沿用恢复后的 B713 全 Flash 基线；仅在 drive-OFF reset/halt 路径写非活动 A。
- 收据：`tmp/torque450-stage-1792406505474903200.json`。
- 完整回读及独立第二次回读均通过，B、bootloader、私有配置和元数据不变。
- SD=0、MOE/AOE=0、CCER=0、MCU 停住；尚未提交试运行或固定 Iq 命令。
- 本轮未覆盖/执行正式 B，不使用 no-reset Flash loader，不强制确认。

下一步仅在用户开启正常 12 V / 限流 0.5 A 并确认无报警后，通过原健康确认、校准和时序预检；通过才执行一次 +0.45 A / 最多 5 秒。失败不重试。当前没有新 0.45 A 实测结果。

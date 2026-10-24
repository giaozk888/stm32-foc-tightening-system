# dq 交叉耦合补偿 OFF / ON 人工空载对照

## 结论

修正版整数回复已在真实板上验证。OFF 与 ON 各完成一次原 START 空载运行，均达到约 240 rpm，均在原 8 s rundown 时限因无接触而结束。不是完整拧紧成功，也没有强制 CONTACT/OK。

补偿 ON 确实参与电压合成，但本次单组结果混合：匀速误差较低，加速误差、起转延迟和 IqRef 峰值反而较高，**不足以认定整体控制改善**。电感仍为未通过正式辨识质量检查的候选值，不据此调整 PI/电角零点/相序/阈值，不升级正式 B。

## 同条件与操作边界

操作者确认 12 V 关闭、MCU 供电、转轴解锁、负载脱开、电机空载固定/有防护，接线不变、12 V/限流 0.5 A、在场可立即断电。各轮按提示上电；OFF 轮另行确认无报警，ON 轮在“若无报警且可立即断电再回复”的请求后回复已开启。

两轮为同一 `DqDecouplingWireCandidate` BIN / ELF：

- BIN 219300 B，SHA `95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`。
- ELF SHA `ed4f4430c57e6b8ba18b81b856a7ac9041a273776da8d9c14b111b9438ef7b45`。
- 240 rpm；速度环 Iq 限幅 ±0.50 A；独立超速 300 rpm；总电压上限 1.60 V；电流 PI 积分限幅 0.75 V。
- 原 20000° 行程、8 s rundown 超时、12 s 最大板端租约及全部原保护。
- 新电流 PI、S-curve、速度 anti-windup、加速度 FF、105 mA 摩擦补偿均保持原配置；SB3 仍按原候选关闭。
- 只在 IDLE/输出关闭时切换 DQ，OFF/ON 均经状态回复证实。两轮之间关闭 12 V、恢复 B；ON 准备仅再次验证同一镜像，`flash_programming=false`。
- 每轮恰好一次 START，无重试、无自动升流、无强制接触。

## 实测对照

| 指标 | DQ OFF | DQ ON | 数据来源/限制 |
|---|---:|---:|---|
| 实际 START 数 | 1 | 1 | 主机命令回执 |
| terminal | RUNDOWN_TIMEOUT | RUNDOWN_TIMEOUT | 无接触空载，原超时未改 |
| CONTACT | 0 | 0 | 无假接触 |
| 末段平均速度 | 238.57 rpm | 237.70 rpm | 最后约 0.35 s 稀疏 STATUS，7/6 点 |
| 1 kHz 速度统计最大超调 | 6.368 rpm | 5.666 rpm | 累计 AFF observer，不是外部测速仪 |
| 加速段平均绝对速度误差 | 7.413 rpm | 10.467 rpm | AFF 既有相位统计 |
| 匀速段平均绝对速度误差 | 4.416 rpm | 3.517 rpm | FRC 既有相位统计，约低 20.4% |
| 既有起转延迟指标 | 174 ms | 349 ms | FRC observer，不是外部机械起动测量 |
| IqRef 峰值 | 302 mA | 394 mA | 未超过原 500 mA 命令限幅 |
| 测得 Iq 绝对峰值 | 1269 mA | 1293 mA | 既有 1 kHz observer；不是平均或稳态电流，未据此放宽判别器 |
| 速度积分器峰值 | 70 mA | 111 mA | 既有统计 |
| 速度环 Iq 饱和累计 | 0 ms | 0 ms | 既有统计 |
| FOC wall max | 32.5882 µs | 32.8765 µs | 启动/预检/运行/停止累计，不是只截取运行期 |
| >50 µs deadline miss | 0 | 0 | 原计数 |
| actual CCR commit | 300118 | 301128 | 原真实提交计数 |
| actual CCR late | 0 | 0 | 非 hypothetical/旧 ADC timing 的 LATE 字段 |
| actual margin 最小值 | 15.1412 µs | 15.1412 µs | 真实提交位置测量 |
| CUR_CONFIRM enter/clear/fault | 138/138/0 | 134/134/0 | 没有改确认判据 |
| 零点 valid/reject | 4000/44 | 4000/47 | 两轮均 PASS |
| 零点 U/V | 1559/1563 | 1560/1563 | 初始零点并非完全相同，不能忽略 |

两轮 `MOTOR TEST FAULT VALID=0 FLAGS=0`、最终 STATUS `FLT=0`。首故障框架另保存了 domain=3 / reason=3 / protection_flags=0，指向 tightening 的 RUNDOWN_TIMEOUT，不是编码器/过流/超速/50 µs 故障。

运行脚本仍将完整流程的 `pass_=false`、退出码 1 和 `FSM terminal RUNDOWN_TIMEOUT` 原样保存，没有为使测试“通过”而修改证据。两次运动和数据采集完成，不等于完成真正带工件拧紧。

## 证明补偿不是只打开一个标志

每轮采到 31 条额外 DQ 查询：16 条 STATUS、15 条 VOLTAGE，运行中相邻查询约 250 ms，状态/电压交替，**不是 20 kHz 连续电流波形**。

- OFF：15 条有效电压帧的 `VD_FF_UV=VQ_FF_UV=0`，最终电压等于 PI 电压。
- ON：15 条有效电压帧均有非零补偿；d 项 -609…-115 µV，q 项 -198…+405 µV。
- ON 的无饱和帧满足 `VD_UV - VD_PI_UV - VD_FF_UV`、q 轴同式的绝对残差均不超过 1 µV，符合各项独立向零截断的量化误差。
- 运行期间 ON/FRAME_ON 均为对应模式，LD_NH=20030、LQ_NH=11180，未发生 query error。

只用这些稀疏 STATUS 点估计 Id，会受采样时刻影响：

| 稀疏 Id 指标 | OFF | ON |
|---|---:|---:|
| 全窗口 mean abs(Id)，各 16 点 | 28.78 mA | 33.27 mA |
| 附加后选 2–8 s 窗口 mean abs(Id)，11/12 点 | 28.34 mA | 17.55 mA |

不能只挑第二行来宣布 Id 整体改善，也不能把不同 seq 的 STATUS/VOLTAGE 强行当作同一帧。完整窗口和启动指标没有一致改善；两轮零点 U 相差 1 count、初始轴角和机械摩擦条件未严格复现，且没有重复统计，不能把所有差异归因于不到 1 mV 的补偿。

## 完整回执与最终状态

OFF：

- 暂存 `tmp/dq-fsm-stage-1792579033344221500.json`
- 运行 `tmp/dq-fsm-run-1792579105569898700.json`
- 关闭 12 V 后恢复 `tmp/dq-fsm-restore-1792579205605833800.json`（B912）

ON：

- 暂存/验证 `tmp/dq-fsm-stage-1792579251311153700.json`
- 运行 `tmp/dq-fsm-run-1792579317512317700.json`
- 最终恢复 `tmp/dq-fsm-restore-1792579402223585900.json`（B916）

最终由操作者关闭 12 V，保持 MCU 供电和接线不变。恢复已确认 B 启动选择、pending/active=0；停在 B 应用入口，没有运行 B 应用。调试器读回 VTOR=0x08040000、DHCSR=0x30003、SD=0、BDTR=0、CCER=0。

B payload、bootloader、配置及槽外数据均未变；只有通过官方流程更新的启动元数据。最终完整 Flash SHA：
`464aae9dd445156eda51ce39ff2d148bfe50759ff4da0d56e28de05c0f3848f9`。

本轮没有修改固件代码或控制参数。后续若再次暂存，显式用上述最终 B916 恢复回执作为 `--baseline-restore`；默认 B908 是保留的信任根，不能跳过全 Flash 对比。

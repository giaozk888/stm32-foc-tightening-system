# A 候选：Rs/Ld/Lq 电流 PI 与旧 PI 离线对照

## 范围

用户指定暂用 Rs=0.78 Ω、Ld=20.03 µH、Lq=11.18 µH。这些数值未通过正式辨识质量检查，特别是 L 依赖未验证的电压/采样对齐假设；本轮不将它们升级为可信电机参数。

只在 A 增加编译期可选电流 PI 增益，不修改正式 B、启动选择或参数存储，不刷板、不启动电机。速度/位置 PI、S-curve、加速度 FF、摩擦补偿、相序、电角零点、CUR_CONFIRM、TWO_SAMPLE、PWM pipeline、IRQ 和保护阈值均未修改。

## 增益

旧源码明确以约 300 Hz 作为初始电流环设计带宽，因此本次沿用 300 Hz，不另行抬高带宽。

```text
wc = 2*pi*300 rad/s
Kp_d = Ld*wc
Kp_q = Lq*wc
Ki_d = Ki_q = Rs*wc
integrator += Ki*error*50us
```

| 增益 | 旧 PI | 新 A 候选 |
|---|---:|---:|
| Kp_d [V/A] | 0.080 | 0.03775566 |
| Kp_q [V/A] | 0.080 | 0.02107381 |
| Ki_d/Ki_q [V/(A·s)] | 188 | 1470.26538 |

Ki 是旧值约 7.82 倍，不是无风险小改动。原 PI 的误差计算、积分先更新、积分限幅 ±0.75 V、矢量电压限幅 1.60 V、饱和后积分跟踪顺序不变；积分跟踪使用对应 d/q 新 Kp。原电流限幅和全部独立保护不变。

`FOC_CURRENT_PI_IDENTIFIED_ENABLE` 默认 0。打开时按公式选择 d/q 增益，关闭时退回原 0.080/188 字面量。带宽可在候选配置中设置为大于 0 且不超过原设计 300 Hz 的值。

## 文件

- `firmware_common/current_pi_identified_candidate.h`：A 可选增益配置，无运行时状态、无持久写入。
- `foc2_app_a/Core/Src/main.c`：电流 PI 的积分、比例和饱和积分跟踪改用 d/q 对应增益。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：A-only 开关、带宽验证、对照构建。
- `tools/current_pi_compare.py`：编译并调用主程序实际 PI 代码块，进行假设 RL 电机离线仿真。
- `tests/test_current_pi_identified_candidate.py`：实际 C PI 增益、更新顺序、原有限幅、正负响应、关闭开关等价及 B 隔离回归。

## 构建

| 构建 | FLASH (B) | RAM (B) | 结果 |
|---|---:|---:|---|
| A `CurrentPiLegacyCompare` | 217420 | 129152 | 通过 |
| A `CurrentPiIdentifiedCandidate` | 217428 | 129160 | 通过 |
| A `CurrentPiIdentifiedComputeOnly` | 228788 | 129088 | 通过 |
| B 隔离目录 `CurrentPiBUnchanged` | 228300 | 128792 | 通过 |

功率硬关闭版本复用原 `OneCyclePwmPipeline` 独立计算夹具，不把闭环电机使能配置与硬关闭夹具强行混合。它不是同一套 tightening 功能覆盖的板测替代品，主要用于功率关闭的计算/时序预检。Flash 仅余 588 B，不宜继续叠加诊断功能。

旧 PI 对照 BIN 与原 `Tightening240rpmFriction105OnCandidate` 字节完全相同：
`3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`。

原已确认 B 文件 `foc2_app_b/build/FrictionBUnchanged/foc2.bin` 未变：
`7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。

B 仅在新构建目录验证可编译，未替换原已确认文件。新旧 A 完整构建同为 13 条已有警告（unused 及 RWX），没有新增警告类别或错误；并非整个工程零警告。

## 离线比较，不是实机比较

报告：`tmp/current-pi-compare.json`。

采用当前假设 Rs/Ld/Lq 构建独立 d/q 锁轴 RL 模型，周期 50 µs，保留一拍 pending；每区间前 25 µs 使用旧电压、后 25 µs 使用上拍 pending。每组 80 ms，在 5 ms 阶跃、45 ms 回零。调用从当前主程序提取并编译的真实 C PI 代码，不另外编写一套 PI 来代替。

这一模型由候选参数构造，天然有利于按相同模型整定的新 PI。它不模拟实际速度环、转矩输出、逆变器死区、电压降、真实采样毛刺或参数辨识正确性；不能据此认定电机会更稳或实机电流响应一定达到下表数值。

0→0.35 A、无噪声、名义 RL 模型：

| 指标 | 旧 PI d/q | 新 PI d/q |
|---|---|---|
| 到 90% 目标电流 | 9.95 / 10.00 ms | 1.10 / 1.10 ms |
| 进入并保持 ±2% | 17.20 / 17.25 ms | 1.85 / 1.85 ms |
| 正向超调 | 0 / 0% | 0 / 0% |
| 电流绝对峰值 | 约 0.350 A | 约 0.350 A |

每组 PI 共 60 个工况（两轴、0.10/+0.35/−0.35 A，R 和 L 各自独立 0.5/1/2 倍，额外 5 mA 正弦测量噪声及每 100 拍一次 hold 的敏感性工况）。噪声与 hold 是显式假设，不是重放真实 discriminator 的等价证明。

参数不匹配敏感性中，新 PI 最大超调约 7.06%，旧 PI 为 0%；因此“更快”有鲁棒性代价。这里只覆盖有限假设组合，不能证明真实硬件闭环稳定。

## 测试和后续人工板测

相关测试日志位于 `tmp/current-pi-candidate-tests.log`、`tmp/current-pi-motor-regression.log`、`tmp/current-pi-speed-regression.log`、`tmp/current-pi-protection-regression.log`。

新增候选测试 5 项、辨识相关 127 项、速度控制相关 81 项、pipeline/CUR_CONFIRM/编码器优先级/trace 相关 33 项，共 **246 项通过**。这不是整个仓库所有测试的全量运行。

人工板测应先使用功率硬关闭构建检查校准、FOC 时间、deadline/CCR late；通过后再在现场固定空载、保留原电源限流和所有保护，用相同初始条件对旧/新 PI 各做单次低电流短测。比较 Id/Iq 误差、过冲、积分/电压饱和、FOC 耗时和故障。保护触发不自动重试；未获得新板测证据前，不替换正式 B，不把理想模型性能当作验收结论。

复现离线比较：

```powershell
python tools/current_pi_compare.py
python -m unittest discover -s tests -p test_current_pi_identified_candidate.py -v
```

候选已接入并完成离线比较，等待人工功率关闭预检及后续受保护板测。

# TWO_SAMPLE 100 / 40 A 候选（2026-10-20）

按本轮请求，仅为现有 240 rpm、±0.50 A、20000° A 候选增加独立构建：
`Tightening240rpmAdc100Return40Candidate`。

## 判定边界

距离仍是 U/V 两通道绝对差的最大值，单位为 ADC 原码计数，不是安培。

| 项目 | 原 A | 新 A 候选 |
| --- | ---: | ---: |
| TRACKING 跳变门槛 | 60 | 100 |
| SUSPECT 回旧参考容差 | 25 | 40 |
| 确认新候选容差 | 25 | 25（不变） |
| 连续 unresolved 故障上限 | 3 | 3（不变） |

TRACKING 时 `d_old <= 100` 使用本对样本；`d_old > 100` 进入 SUSPECT、保持控制更新。
SUSPECT 时 `d_old <= 40` 可接受回归旧参考附近，并清除连续 unresolved 计数。
超过 40 不一定故障，仍走原有候选确认/无法判定分支。

注意：原实现的向外斜坡确认分支也共用 JUMP 宏，因此该分支候选推进步长同步从 `<=60` 变为 `<=100`；其“更靠近候选、离旧参考不缩小”等条件不变。没有另写滤波算法。

## 范围与验证

- 新选项 `FOC_ADC_COUNTS_100_40_CANDIDATE` 默认 OFF，仅 A 有对应 preset。
- 公共头文件默认值仍为 60/25，既有 A/B 配置不变。
- 不改 CUR_CONFIRM、独立原码安全检查、过流阈值、PI、FOC 数学、PWM pipeline 或状态机。
- 正式 fault trace 仍关闭。本轮没有取得上次故障前连续三帧原码，不能声称真实故障回放通过或已解决实机故障。
- 新增离线测试覆盖 100/101、40/41、25/26、向外推进 100/101、U/V 成对处理、连续 3 次 unresolved 仍故障、CUR_CONFIRM 和独立安全路径。
- 比较预处理后的控制/保护函数，只有上述阈值对应的三个使用位置不同。
- 本轮 4 项新增测试、44 项现有定向回归全部通过（共 48 项）；覆盖 fast reject、CUR_CONFIRM、零点样本准入、PWM pipeline、流程状态机及 240 rpm/20000° 配置。不将此表述为全部历史测试均通过。

## 构建

在 `foc2_app_a` 目录运行：

```powershell
cmake --preset Tightening240rpmAdc100Return40Candidate
cmake --build --preset Tightening240rpmAdc100Return40Candidate
```

编译通过：Flash 228620/229376 B，RAM 128808/131008 B。与旧候选比较没有新增 warning 类型；仍有既存 unused-function、RWX linker warning，不宣称零警告。

新 BIN SHA256：`a1e158f50c3809c96d9df39f3c52353a2ed4b50bb02e911a4824437e25da5cdd`。

新 ELF SHA256：`c21525477f426910bdb669c606b5ee8b6a21def970ae470f21bc4a88ec2dea0c`。

未刷板、未复位、未启动电机、未改启动选择；板端仍是上次恢复的原 B744。旧 20000° A 和 B CommonMode 构建的 BIN SHA256 均保持不变。

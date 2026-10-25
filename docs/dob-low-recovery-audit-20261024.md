# 短低速回退事件记录候选

本轮只加证据，不改恢复算法或保护，不连接硬件、不烧录、不启动电机。

## 根因与修改

旧 `dob_low_recovery.reason` 在冷启动重新有效后会归零；`held` 也会清零。
所以此前一次缓存、一次回退结束后，只剩计数，无法定位具体分支。

新增 `DobLowRecoveryAuditCandidate`，继承同一短低速200ms候选，只开启默认关闭的 `FOC_DOB_LOW_AUDIT`。
回退发生、状态被清除之前，保存**首次和最近一次**96字节快照，外加8字节ABI/总事件计数。
使用75点分类器未使用的 `value[75:100]` / `stamp[75:100]` 共200字节尾部；不覆盖有效75点窗口，也不占用good数组。
普通质量重置只清good等活动状态，快照保留；新的采集会话绑定/清空分类器时才清除旧记录。
记录2次以上时首个不变、最近覆盖，总事件数保留，不能假设中间事件也有完整快照。

## 字段与分支

| 类别 | 字段 |
|---|---|
| 时间与原因 | timestamp_us、reason、site、mode |
| 原准入证据 | status、input_valid、filter_updated、decision、quality_reason |
| 确认进度 | quiet_n、quiet_age_us、low_start_us、return_start_us、low_elapsed_us、return_elapsed_us |
| 电流来源 | source_us、published_us、accepted_gap_us |
| 实测量 | omega_rad_s（机械rad/s）、Id/Iq（A）、abs_id_lpf（A） |
| 确认窗口范围 | omega_range_rad_s、drive_range_a |

`site` 区分8个实际出口：输入/质量拒绝、方向反转、低速超过100ms、恢复后再次低于10rpm、投影后饱和、原冷启动已就绪、返回确认超过200ms、会话停止或故障。
输入/质量拒绝还需结合status、filter_updated和准入decision/quality_reason解读，不把所有SOURCE都当成同一种电流异常。
生命周期出口没有新编码器帧，时间戳明确标为最后实际样本，不虚构新的采样时刻。
ABI/事件数作为有效标记，时间戳恰好为0也不会被当成空记录。

## 回归与编译

- 原生C回归覆盖尖峰拒绝发生时保存数据、恢复后保留、分类器质量清空后保留、首/末多事件语义、反转/再次低速分离、长低速/200ms超时、故障生命周期、新会话清空、NaN输入解码、0时间戳、匹配ELF与RAM布局、旧ELF拒绝及物理入口检查。
- 同一140组×7001帧输入，对比记录OFF/ON：**980140帧、全部33项输出逐点完全一致**。实际观测器、滤波、有效性、计数与有界补偿路径均使用原C实现；不是用模拟返回值比较。
- 构建成功：RAM131000/131008字节，与原候选相同；Flash229072/229376字节，剩304字节。未扩大RAM、Flash分区或任务栈。
- 只有回退时构造快照；额外96字节局部记录在任务栈上，常驻RAM不变不等于没有瞬时栈/计算成本。真实发生回退时的栈余量和时序须以后板测核实，本轮未宣称已验证。
- BIN：`foc2_app_a/build/DobLowRecoveryAuditCandidate/foc2.bin`，SHA256 `2f7e873229879f6a114b1ede2cdb542cebbdd4aecb1beec20a6ae37a2550cd37`。
- 原板测镜像 `DobShortLowRecoveryCandidate`、正式B镜像保持原文件，不在本轮重建覆盖。

## 文件

- `firmware_common/dob_low_recovery_audit.h` / `.c`：快照ABI和尾部存储。
- `firmware_common/dob_short_low_recovery.h`：默认关闭的出口记录钩子。
- `foc2_app_a/CMakeLists.txt` / `CMakePresets.json`：独立记录候选。
- `tools/dob_low_audit_decode.py`：停止后的RAM/ELF只读解码，可单独运行。
- `tools/dob_low_audit_board.py`：匹配候选、保存 `.fallback.json`、校验事件数与回退次数闭合；默认只校验文件，没有硬件操作。
- `tests/dob_low_audit_host.c` / `test_dob_low_recovery_audit.py`：实际C实现回归。

```powershell
python -m unittest discover -s tests -p test_dob_low_recovery_audit.py -v
python tools/dob_low_audit_decode.py --ram <停止后的RAM文件> --elf <匹配记录候选ELF> --output <结果JSON>
```

此前实测镜像没有这些记录，不能用新解码器倒推出旧运行的回退原因；解码器会拒绝旧ELF。
下一次人工板测保存新RAM后，才能获得真实的首次/最近回退快照。本轮无新实测数据，未改正式B或板上启动选择。

## 后续人工板测：记录版首次运行

人工确认12V关闭、制动器释放和现场条件后，准备记录
`tmp/dob-low-audit-stage-1792837414925227200.json` PASS：仅写非活动A，两次完整回读通过，原B/boot/配置未变、尚未激活。
人工确认上电无报警后，预检通过，仅发一次240rpm START：
`tmp/dob-low-audit-run-1792837477112207700.json`。

| 指标 | 实际结果 |
|---|---:|
| 观察次数 | 8000 |
| DOB有效 | 6774 / 8000，84.675% |
| 新鲜反馈有效 | 6657 / 8000，83.2125% |
| 补偿峰值 | 22.435mA，未超过25mA补偿限幅 |
| 快速恢复 / 回退 / 缓存帧 | 0 / 0 / 0 |
| 快照总事件数 | 0；首次/最近均为null |
| 分类器重置 | 0 |
| Iq饱和标记 / 电压饱和标记 | 123 / 0帧 |
| 原输入时间/序号等硬失效重置 | 0 |
| DOB专用电流跳点 | 229帧；不等于电机保护故障 |
| FOC最大 / deadline miss / CCR late | 33.253us / 0 / 0 |
| 结束结果 | 原8秒RUNDOWN_TIMEOUT，CONTACT=0，独立保护故障=0 |

全轮133个60ms间隔趋势点及25个事件均完整，记录无环形覆盖丢失。
制动变化主要出现在约5.6～5.9秒，而非计划的3秒附近；这是日志中测得变化时刻，不是具有电气真值的制动开关时间。
5.696015s记录174.6rpm，5.757002s记录109.3rpm，5.817034s记录20.4rpm，5.877973s记录253.5rpm。
20.4rpm点的DOB仍有效，但带SAT标记，因此新鲜补偿按原规则被阻断；估计继续，没有引发分类器完整重置。
上升/下降代理至趋势确认分别43.040/131.055ms，均不是物理制动的绝对响应时延。

缓存、确认和回退计数均为0，因此本次没有触发缓存回退，不存在可解码的首次/最近快照。
60ms稀疏速度点不能证明所有1ms瞬间始终高于10rpm；严格结论是**没有满足并触发缓存进入条件的记录**。
不能把空快照称为记录失效，也不能由此宣称快速恢复成功；本次同样没有实测到回退事件函数的瞬时栈/耗时。
预检报告电机任务栈余量2532字节，仅代表预检时，不是实际回退函数运行后的栈验证。

人工回复确认关闭12V及释放制动器后，仅恢复B启动选择：
`tmp/dob-low-audit-restore-1792837575414166600.json` PASS。
元数据序号1250；B应用、boot、配置保持原内容，B应用未运行、motor_commands=0；
VTOR=0x08040000，SD/MOE/PWM关闭，CPU暂停在B入口。未追加测试。

分析：`tmp/dob-low-audit-board-analysis-20261024.json`。
独立证据文件：`tmp/dob-low-audit-run-1792837477112207700.fallback.json`，event_count=0。

# 恢复原240 rpm运行配置（文件准备，未刷板）

用户要求：运行配置与原来一致，不增加诊断限制。这里的原来明确取
已完成240 rpm空载OFF/ON两轮的 `DqDecouplingWireCandidate`，而不是另一套
Rs/Ld/Lq辨识诊断配置，也不把长期保留的B构建文件当作当前板上B。

## 200 us的来源

200 us事务硬期限来自 `firmware_common/as5047p_timing_policy.h` 默认值。
原240 rpm镜像与本次DQA镜像的编码器端口均未开启
`AS5047P_DMA_TIMING_POLICY_V2` 或 `AS5047P_DMA_TERMINAL_FIX`。
逐项比较main编译定义，本次仅增加DQ_AUDIT及符号诊断开关，未新增期限。

上一轮201 us保护说明此次事务越过了既有期限；不能说是刚新增限制，
也不能只凭201与200的差值断言SPI物理传输坏了。新插桩消耗CPU、可能影响
低优先级编码器服务，但现有证据不足以证明这就是该事务唯一原因。

参数辨识已有独立V2配置：200 us慢告警、400 us硬期限、终态仲裁修复。
它是显式放宽了原事务硬期限的不同候选，不是原240 rpm配置。没有暗中
把400 us代入正常运行，也没有直接删除事务/新鲜度/控制看门狗。

## 本轮改动

新增A构建预设 `DqOriginalRuntime`，继承原运行配方，并显式设置：

```
FOC_DQ_AUDIT_ENABLE=OFF
DECOUPLING_SIGN_TEST=OFF
DECOUPLING_SIGN_MODE=0
AS5047P_DMA_TERMINAL_FIX=OFF
AS5047P_DMA_TIMING_POLICY_V2=OFF
```

原诊断镜像/ELF/运行回执全部保留。没有改编码器/FOC/控制器/保护算法。
这一变更是隔离运行构建与取证构建，避免诊断插桩进入原运行时序；
不是伪称已经完成新增同步日志下的ON/OFF辨识。

| 项目 | 原240 rpm版本 | DQA诊断版 | 本次原运行构建 |
|---|---|---|---|
| 编码器事务硬期限 | 200 us | 200 us | 200 us |
| 采集调度迟到 | 200 us | 200 us | 200 us |
| 编码器周期 | 1000 us | 1000 us | 1000 us |
| 角度样本新鲜度 | 1500 us | 1500 us | 1500 us |
| 控制消费看门狗 | 2500 us | 2500 us | 2500 us |
| DQA每有效ADC帧统计 | 无 | 有 | 无 |
| 反号实验编译开关 | 关闭 | 开启、模式0 | 关闭 |
| 240 rpm / Iq ±0.50 A | 原配置 | 不变 | 不变 |
| 独立超速300 rpm、过流、CUR_CONFIRM/CURRENT_INVALID | 原配置 | 不变 | 不变 |
| S-curve、AW、加速度FF、105mA摩擦补偿 | 原配置 | 不变 | 不变 |
| PWM一拍pipeline、ADC/FOC频率、IRQ优先级 | 原配置 | 不变 | 不变 |

## 构建核验

```
cmake --preset DqOriginalRuntime
cmake --build --preset DqOriginalRuntime -j 8
```

Flash 219300 B，RAM129600 B，与原镜像BIN逐字节一致：
`95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`。
所有翻译单元的宏定义集合与原配置一致，不仅比较main。
没有新增warning/error，原unused/RWX告警保留原样。

测试包含实际编译的200/200/1000/1500/2500时序宏断言、BIN身份、全部翻译单元
定义、无DQA格式字典以及原控制/保护回归，86项全部通过。结果见
`tmp/dq-original-runtime-regression.log`。

## 当前板卡

本轮未连接调试器、刷板、复位或启动电机。仍以已完成的
`tmp/dq-audit-restore-1792583167104102100.json` 为停机/回退证据：
选中原确认B、CPU停在B入口、SD/MOE/CCER关闭。A槽里仍保存上轮诊断A，
不会因为PC上生成了运行BIN就自动变成原运行固件。
若后续要实际使用原运行构建，需要另行按当前基线更新非活动A，先确认供电。
不为追求运行通过而自动放宽200 us或复用失效的旧暂存回执。

## 后续人工暂存记录

用户重新确认12 V关闭、转轴解锁空载固定、接线/限流不变且在场后，已执行：

```
python tools/dq_original_runtime_board.py --stage-off --dq-on --drive-off-unlocked-no-load-fixed
```

回执 `tmp/dq-fsm-stage-1792583486017966500.json`：PASS，两次完整回读一致。
原运行A 219300 B完整校验通过；boot/B/私有配置/启动元数据与B920基线未变。
CPU停住、SD/MOE/CCER关闭；未激活，未发送运动命令。下一次只做同原配置
DQ ON一次空载运行，先提示人工上电、无报警，再经过原校准/健康/时序预检。
本段替代前文“尚未写入A”的文件准备时点状态，不表示已经运行电机。

# 五点全部异常才终止：功率硬关闭诊断对照

## 本次改动范围

用户要求将零点窗口的成簇异常条件从“5 对中至少 2 对异常”改成“5 对全部异常才终止”。已实现独立构建 `ZeroAllRejectedDiagnostic`，只用于功率输出硬关闭的诊断比较；**未修改正式控制准入规则，未刷写、复位或连接板端，未启动电机**。

不能将该对照直接当成带电控制的零点可信度证明：修改后允许 5 对中只有 1 对同时有效的窗口通过。本次测试特意验证了这个边界，不能将“校准完成”误称为反馈已经可靠。

## 精确定义

每组仍是连续 5 对物理输入，先分别计算 U、V 的五点中值。任一通道距离对应中值 **大于 40** 个 ADC 计数，该物理输入对即计为异常；等于 40 不算这项异常。异常累计总数仍只计数，不作为总数配额。

- 0～4 对异常：不因 BURST 这一项终止。
- 5 对全异常：BURST 锁定失败，不使用空的有效范围计算，不发布这一块的零点。
- ADC 非法、块中值相对预期零点偏移、有效范围、块中心跨度、分段漂移、完整 4000 对物理窗口和原有时效检查仍独立保留。因此“只在全部异常时终止”仅适用于这一个 BURST 条件，不代表其他失败检查被删除。

U/V 的中值可能来自不同的物理输入对，因而“5 对全异常”确实可能出现。不能错误地以“每路中值至少等于其中一个原码”为由断言这一联合判定永远不会触发。

编译选项为 `FOC_ZERO_ALL_REJECTED_DIAG`，必须同时使用硬关闭 adaptive 诊断及无累计配额配置；与 latest/original 或 compact 带电控制配置混用时拒绝编译。正常控制原有 `rejected > 1` 保持不变。新查询命令仅在该诊断配置存在：

```text
MOTOR TEST ZERO POLICY
OK ZERO POLICY DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V
```

该实验沿用已有硬关闭 `ProtectedAdaptiveRam` 底层，不是带电 `LatestOriginalStartupEvidence` 的解锁版本。START 准入被拒绝，SetDuty 不得打开 SD/MOE/CCER。正常控制的 4 A 确认保护、独立 guardian 与历史镜像均未替换。

## 离线验证

17 项回归通过，覆盖新增 6 项、原 count-only 7 项、启动记录 4 项。新增生产 C 回放分别在 `-Os`、`-O2` 下运行且结果一致：0～4 对异常边界、联合 U/V 的 5 对全异常、4000 对完整窗口、ADC 越界、预期零点偏移、中心跨度、分段漂移、禁止控制配置混用、实际生产绑定 START 拒绝及输出硬关闭、查询身份、新旧镜像区分。

首次配置拒绝测试误对未包含 robust 头的无功能回放入口做语法检查，未实际触达编译 guard，出现 1 项失败；已改为直接检查生产 `foc_zero_robust.c`，随后完整 17 项通过。并非通过放宽编译 guard 处理。

A/B Release 构建通过，仍有既有未使用函数/变量、Pigweed 未使用变量与 RAM RWX 链接警告。资源及镜像：

| 槽 | BIN | 链接 RAM | SHA-256 |
| --- | ---: | ---: | --- |
| A | 207444 B | 121720 B | 9035539aabd09609914e39c13cb5170d18e709efc2ae1269c71accab55ef51e8 |
| B | 206524 B | 121696 B | c8637412a9952b57045c1a28a98f38c59287f92d8e197018010974091729dd24 |

原 `LatestOriginalStartupEvidence` A/B BIN 哈希均与之前一致，没有覆盖其构建目录。

修改文件：`firmware_common/foc_zero_robust.c/.h`、`protected_closed_loop.inc`，A/B 的 CMake 配置与预设；测试 `tests/test_foc_zero_all_rejected.py` 和硬关闭绑定用例。这里的结果是离线算法与编译验证，不是实机采样质量、50 µs 截止或电机闭环验收。

板端仍是前一轮失败后暂停的 A 试运行现场，confirmed=B、pending=A、attempts=1、generation=551；这是上轮记录，不是本轮重新读取。没有因本轮源码修改而自动激活诊断配置。

## 上板工具准备与离线回归

新增 `tools/zero_all_rejected_board_test.py`，默认仅离线校验固定镜像。上板分为两个独立阶段：12 V 关闭后仅替换失败且未确认的 A，完整回读并保留已确认 B、bootloader、参数和元数据；供电恢复后才允许提交一次正常 A/B 诊断试运行，不发送 START、不强制确认、不自动重试。成功判据包含完整 4000 对零点、硬关闭身份和最终启动元数据确认的精确镜像大小及 CRC。异常路径保留串口记录并关闭连接。

本轮运行板端工具 9 项与算法/绑定 6 项，共 15 项离线测试全部通过；默认运行报告 `OFFLINE PASS`。**尚未执行板端工具的刷写或试运行阶段，也未重新读取板端状态**；目前等待驱动板 12 V 已关闭的实际状态回复。离线通过不代表实机零点、50 µs 耗时或闭环控制通过。

## 后续实机暂存结果

收到用户“关了”后执行暂存阶段，结果 `STAGE PASS`：新 A 镜像写入并完整回读通过；A 槽外全部 Flash 字节、B 槽回退、bootloader、私有数据和启动元数据保持不变。MCU 停在复位后的 bootloader，SD/PWM 输出关闭，尚未激活，电机启动命令数为 0。暂存证据：`safety_backups/protected-closed-loop-20261014/zero-all-rejected-stage-1792063007072068600.json`。

此时仍未取得新诊断版的实机零点数据；下一阶段需恢复驱动板正常供电后，单独提交一次功率硬关闭的诊断试运行。

## 后续一次诊断试运行结果：零点完成，计算时限失败

用户回复“开了”后，仅提交一次正常 A/B 试运行，未发送 START，也未自动重试。证据：`safety_backups/protected-closed-loop-20261014/zero-all-rejected-trial-1792063086911802700.json`。

- 新策略身份确认：`DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V`。
- 稳健零点完成：`STATE=3 REASON=0 N=4000`，8 段，U0=1564、V0=1561；异常输入对计数 39（占 4000 对的 0.975%），robust FLAGS=0。此计数不是筛选后的残留异常数，也不构成带电反馈可靠性证明。并行原码检查仍记录 `RAW_STATE=4 RAW_REASON=2`。
- 整体试运行失败不是 BURST 再触发：状态 FLAGS=256，对应生产代码 `CL_COMPUTE_LATE`。已完成 3809 次 FOC 工作，捕获 1 次耗时达到计时器读数 50 µs；`ProtectedLoop_WorkEnd` 的条件是 `elapsed >= 50U`，因此等于 50 也会锁定。
- 首次晚点帧记录 `US=50 PAIR_US=25 MATH_US=24 WALL_CYC=8352 IRQ_CYC=4869`。1 MHz 计时读数与 DWT 周期不宜混为精确相同的计时区间；不能据此声称物理耗时严格超过 50 µs。累计成本最大值 `CPU_MAX_CYC=3483 PREEMPT_MAX_CYC=4950`、`PAIR_MAX_US=37 MATH_MAX_US=24` 来自各自统计，不能直接相加当作同一帧。诊断版不是最新紧凑带电控制构建，不能据此直接断言正式版本退化。
- 最终 SD=0、MOE=0、CCER=0，CPU 已暂停；应用、bootloader 和私有数据字节未变，只有正常试运行流程更新了启动元数据。confirmed=B、pending=A、attempts=1、generation=553，新 A 未完成健康确认；没有声称已经自动回退或已经确认 A。

结论：本次实机验证了新零点 BURST 规则可以完成这批 4000 对采样，但没有通过完整计算时限验收，更没有完成电机闭环验收。已提示用户关闭驱动板 12 V，后续只分析记录，未再次运行。

## 后续离线优化

新增独立 `ZeroAllRejectedCompact` A/B 预设，接入既有紧凑守护/时钟比较及固定编码器操作路径；原诊断镜像保留，零点规则与 50 µs 时限未变。30 项离线回归与 A/B 编译通过，本轮未上板。具体范围、资源和哈希见 `FOC_ZERO_COMPACT_OPTIMIZATION_20261015.md`；不能把旧板端的耗时记作新版本测量值。

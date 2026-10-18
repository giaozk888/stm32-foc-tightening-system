# CURRENT_INVALID rolling trace：离线修复记录

## 结论与边界

本轮只修改 trace、诊断调用点和离线工具/测试。没有刷板、连接调试器、运行电机或改变启动选择。新的故障窗口尚待人工上板获取，不能用离线测试代替 50 µs 时序验收。

旧采集仅有 seq 28522–28537，真实 CURRENT_INVALID 在 seq 499373。已经丢失的 candidate-before 无法从末态恢复，本次没有为旧故障补造数据，也没有据此修改判别器。

## 原因及修改

旧 `FocCurrentTrace_Protection` 在第一次 CUR_CONFIRM 恢复后设置 `post_remaining=5`；`End` 把恢复帧也算进去，再保存 4 帧便冻结。旧逻辑还会对任意保护故障冻结。这解释了长期运行后的 CURRENT_INVALID 窗口为什么缺失。

现在删除恢复倒计时和早期触发元数据，只在下面两个条件同时成立时冻结：

```
protection.result == FOC_OC_TRIPPED
protection.reason == FOC_FP_CURRENT_INVALID
```

CUR_CONFIRM 仅留下每帧事件：1=进入，2=退出。原有保护模块的累计 enter/clear/fault 统计不变，trace 不再重复维护这些计数。其他保护仍正常生效，只是不冻结本 CURRENT_INVALID 专用窗口。

## 判定前态与锁存顺序

```
FocCurrentTrace_Begin / trace_before
    保存原码、reference-before、candidate-before、state-before、unresolved-before
    保存两组 before operand 对应的整数距离
        ↓
原 FocCurrentValidation_Push（完全未改）
        ↓
记录真实返回值及实际 last_path
        ↓
原 FocFp_Trip(... CURRENT_INVALID ...)
        ↓
更新当前帧 fault 标志及 reason → 保存 fault_seq → DMB → frozen=1
```

before-state 在状态机处理前复制到独立诊断存储。decision 在原判别器返回后补齐，且在真正 latch fault 前记录；不是用被覆盖后的 candidate 倒推 d_candidate。`d_old/d_candidate` 是对应 before operands 的 Chebyshev 距离；tracking 或 DISC_EXEC=0 时，不应把这些诊断距离误认为该分支实际执行了 candidate 比较。

每次重用槽都会重置 `DISC_EXEC=0`、decision=`-2/NOT_EXECUTED`、decision_path=`NONE`、PI/PWM 执行标志。若原码保护先返回，不能沿用前一次 decision。电流 counts 只有 `compare_executed=1` 才有效，未执行时必须显示 NA。

`PWM_PENDING` 读取实际 `cl_pwm_pending.valid`，位置是 IRQ 入口 commit 之后、当前 pair 判别之前。它与 CUR_CONFIRM pending、与本拍是否生成新 PWM 分开记录。没有移动或改写 PWM pipeline。

冻结时先完成 fault 上下文，最后发布 frozen。后续 Begin 立即返回，写指针不再前进。没有 post-fault 延后冻结：满环保留 **15 个故障前 ADC pair + fault frame**，在 20 kHz 下故障前历史覆盖 750 µs；不足 16 帧的启动早期故障只保留实际已经发生的帧。

## 二进制与解码

- 正式 A/B 默认 `FOC_CURRENT_FAULT_TRACE_ENABLE=0`。
- 诊断仍单独开启该开关，trace 源文件单独 `-Os`，保留 sections/GC。
- 新格式 CTR2：magic `0x43545232`，20 B header，72 B/frame，16 帧，总 ring **1172 B**。
- 原有关键帧字段保留，新增 before-state；仅删去不再适用的 recovery countdown/早期 trigger header 字段。
- Python decoder 同时支持 CTR1（52 B/frame、860 B ring）与 CTR2；不把两种布局混用。
- 旧板测脚本仍严格锁定历史 CTR1 镜像，未改其 SHA 或启动流程；新产物在单独目录，不能将旧脚本验收结果当作新镜像结果。

离线构建与测试：

```
python tools/current_fault_trace_offline.py --rolling
python tools/current_fault_trace_offline.py --rolling --expanded-tests
```

默认也使用新目录，避免覆盖历史已锁定的 ELF/BIN/收据。

后续人工上板后，对同一轮已经停止或冻结的 RAM/Flash，用对应 ELF/BIN 解码：

```
python tools/current_fault_trace_report.py --elf <matching.elf> --ram <full-ram.bin> --flash <full-flash.bin> --vtor <actual-slot-vtor>
```

该工具只读取文件，验证 Flash 与 ELF 同名 BIN 一致，不访问硬件、不发送命令。

## 构建结果

Flash 上限 229376 B，RAM 链接区域上限 131008 B；下表是链接占用，不代表运行时栈/堆水位。

| 构建 | Flash B | RAM B | Flash 剩余 B |
|---|---:|---:|---:|
| A 正式 | 228940 | 127944 | 436 |
| B 正式 | 227924 | 127928 | 1452 |
| A CTR2 诊断 | 229364 | 129120 | 12 |
| B CTR2 诊断 | 228348 | 129104 | 1028 |

四种构建均链接成功。正式 A/B 的 BIN 与原 `ClosedLoopIntegration/ProtectedPipelineClosedLoop` 基线逐字节一致；没有新增编译告警。既有 unused-symbol / RWX 链接告警没有在本轮消除。A 诊断镜像 Flash 余量极小，不能再无核算增加代码。

## 回归覆盖及已知测试门禁

专项 56 项通过，含：

1. 100 次 CUR_CONFIRM 进入/恢复仍滚动。
2. 在 host 上再运行超过 500000 拍，调用未修改的状态机产生三次 unresolved 后捕获完整连续窗口。
3. 最后一帧 candidate-before=1900、raw=1200、d_candidate=700；状态机处理后的 candidate=1200，不会混淆前后态。
4. 冻结后反复调用，整个 ring 逐字节不变。
5. DISC_EXEC=0 重用槽不继承 decision。
6. seq 回绕、CURRENT_INVALID 恰好在 seq=0 时仍能冻结。
7. 实际 ADC IRQ/core host 路径覆盖早返回及 CURRENT_INVALID，输出关闭、PI 不执行。
8. `-Os/-O2` 下 TRACE ON/OFF 的完整控制状态及返回值哈希一致。
9. C 直接导出 CTR2 ring，再由 Python 解码，核对顺序、before operands 与故障帧。

相关扩展回归共 **204 项，203 通过，1 失败，0 error**，结果见 `tests/current_invalid_rolling_trace_build/receipt.json`。失败为旧 `test_foc_path_profile.test_protection_and_control_kernels_frozen` 使用插桩前的头文件 SHA，仍期望 `fc66017b...`，而本轮未编辑的 `foc_filtered_protection_candidate.h` 已是 `7db63b99...`。保留该失败，不静默更新 golden hash，也不宣称全部现有测试通过。私有固件备份只读权限门禁在获准读取后已重跑通过，最终 204 项结果不再包含权限 error。

current discriminator、60/25/25 阈值、unresolved limit=3、CUR_CONFIRM、PI、SVPWM、硬过流及 PWM pipeline 均未修改。新的诊断开销仍须在功率关闭条件下重新实测。

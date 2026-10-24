# 编码器时序判据分层候选

本轮按“整理编码器的时序判据”实现独立诊断A候选，未自动板测、刷板、复位或启动。
正式B及其原已恢复B836启动选择未动。不是去掉编码器保护，而是把不同时间契约分开。

## 判据

| 契约 | 原默认/正式构建 | 新独立A候选 | 行为 |
|---|---:|---:|---|
| 事务耗时慢告警 | 无独立统计 | >=200us | 仅对完整成功、合法数据计数，不停机 |
| 事务硬期限 | >=200us | >=400us | 未完成即原物理关断、发布TIMEOUT |
| 周期采集调度迟到 | >=200us | >=200us | SCHEDULE fault，不补发突发采样 |
| 采集周期 | 1000us | 1000us | 不变 |
| RX软件时间戳新鲜度 | age>1500us | age>1500us | 反馈不可用，不能不断复用旧角度 |
| 控制消费看门狗 | >=2500us | >=2500us | 独立CONTROL_STALE fault |
| 消费样本间隔 | >2500us/零间隔非法 | 同左 | 独立interval语义 |
| CS/BSY协议guard | 2us | 2us | 必须实际等够，不回填/跳过 |

单次400us是**诊断候选的事务硬期限放宽**，不是声称所有保护阈值不变。
200us不再在此候选中同时充当“正常事务速度预期”和“绝对硬期限”。
选择依据：已有真实事务203us证据说明200us缺余量；400us为8个20kHz周期，
低于1ms采集周期，且1000+400=1400<1500us保留反馈新鲜度空间。
这只是候选预算，不是经过完整最坏IRQ/BSY时序证明的WCET结论；仍需人工板测。
不可用它掩盖SPI IO/parity/EF故障，或自动不断扩大期限。

## 代码收敛

新增 `firmware_common/as5047p_timing_policy.h`，集中定义所有契约及编译期关系校验。
默认transaction200us，仅独立preset显式编译AS_DMA_TRANSACTION_US400U。
周期必须晚于事务硬期限，period+transaction必须小于freshness，
freshness必须小于control watchdog；不接受随意放大到失去新鲜度空间的配置。

原代码两个schedule-late判断复用了AS_DMA_TRANSACTION_US，若只改该宏会连带放宽调度：
现统一改为独立AS_DMA_SCHEDULE_LATE_US200U，默认行为等价，候选也不放宽。

生产事务deadline、成功终态仲裁、AsDma_Consume和FocEncoder_TimeoutReason
均读取同一transaction配置，避免驱动允许203us但消费者仍按200us拒绝。
age和消费interval仍用各自的1500/2500配置，错误分类不混成transaction timeout。
原“成功后重复TIMEOUT”终态修复保持；真正达到400us仍不能回填399us作为成功。

状态为OK且完整通过协议/guard/校验的203us数据可保留，但增加慢告警；
TIMEOUT/PARITY/IO等故障不会变成慢告警成功。
sample_us仍为原RX-IRQ收到数据的软件时间戳，不宣称是硬件采样孔径；
本轮没有修改角度预测/方向/电角零点。

## 低成本诊断

`AsDmaTiming_Record`：整数compare/add/store，仅在1kHz事务结束成功路径统计：
`slow_count`、`ok_max_us`；不在20kHz路径新增日志/浮点/循环。
前台只读命令 `MOTOR TEST IDENT ENCODER TIME`：

`POLICY=2 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=... OK_MAX_US=...`

此命令不启动事务、不ACK延长控制看门狗、不clear fault。
仅用已有短Lock/Unlock方式拷贝2个统计量，格式化在前台，不在ISR。
saved-fault Python解码从保存engine.deadline-start读取真实200/400策略，
不再把400候选成功余量硬算成200us。原旧会话数据仍按其实际200us解释。

## 修改文件

- `firmware_common/as5047p_timing_policy.h`（新）、`as5047p_dma_engine.h`：集中契约/统计helper。
- `as5047p_dma_stm32.c`、`as5047p_dma_stm32.h`：慢告警统计和只读getter。
- `as5047p_dma_deferred.inc`：schedule lateness独立常量。
- `motor_identification_binding.inc`：前台策略/统计命令。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：仅新诊断A opt-in。
- `tools/encoder_saved_fault_report.py`：按保存deadline识别预算。
- `tests/test_encoder_timing_policy.py`（新）；3个既有静态测试改读集中policy header，
  原默认阈值断言本身未放宽。

未修改FOC/PI/SVPWM、current discriminator、CUR_CONFIRM、PWM pipeline、
电流保护、IRQ priority、速度/位置/拧紧逻辑、CAN/Pigweed/IAP/A-B流程。

## 验证

新增4项真实C/绑定/候选一致性回归在-Os/-O2、-Wall/-Wextra/-Werror下通过：

1. consumer/reason/helper：199/200/203/399可成功、400拒绝，慢计数与成功最大耗时；
   parity不转成超时，新鲜度1500边界/重复旧数据1501失败，消费interval2501失败，计数回绕。
2. 实际engine/deferred：板测HOLD due201在203处理可正常完成并告警；
   真正未完成400us时top half仍物理关断；旧完成终态不重复timeout；
   schedule迟到199可开始、200仍SCHEDULE fault，未连带放宽至400。
3. 实际辨识command绑定：完整只读POLICY2日志字段。
4. FOC/PWM等冻结函数对比和历史A/B BIN哈希不变。

其他测试：motor-ident相关53项、编码器终态/真实故障解码/新policy共9项、
默认A/B CTest6项、既有默认超时/FOC-first契约8项，总计76项所选测试通过。
不声称全仓所有测试或实机时序已通过。

日志：`tmp/encoder-timing-policy-tests.log`、`encoder-timing-policy-motor-regression.log`、
`encoder-timing-policy-encoder-regression.log`、`encoder-timing-policy-host-tests.log`、
`encoder-timing-policy-default-contract-tests.log`（均在tmp/）。

## 构建和后续边界

preset `MotorParameterIdentificationEncoderTimingDiagnostic`，编译通过。
Flash215060/229376B、RAM130912/131008B，链接余量96B。
原堆/任务栈预留未缩；链接余量不等于任务栈剩余，后续板测必须继续原栈/时序预检。
相比终态修复候选增加296B Flash/48B RAM，已有unused/RWX warning集合无新增类别。
本轮不重建/覆盖正式B，既有B镜像哈希验证未变。

BIN SHA256 `09ac2082aec995fd6be5e826a887aba2513521319cf13783119157c460fda661`。
ELF SHA256 `0fff84c68c506b25b9ec0ca956ede8cb5cfe52ff38d54274065bad7859e881ad`。
motor_ident ABI1740B仍不变，但driver策略/内存布局已变，旧精确runner应拒绝新镜像。
后续人工上板需新pins、B836基线和显式ENCODER TIME策略验证，不复用旧stage收据。
本轮没有设备操作、烧录、复位或注入电流。

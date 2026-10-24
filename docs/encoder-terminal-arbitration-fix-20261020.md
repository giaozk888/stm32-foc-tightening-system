# 编码器成功/超时收尾竞态修复候选

基于已保存事务成功199us/截止200us/再次失败202us的证据及离线复现，
本轮只修复完成收尾与截止事件的仲裁。未刷板、复位、启动或改变B832启动选择。

## 范围

新增独立A preset `MotorParameterIdentificationEncoderTerminalDiagnostic`，
继承RsRejectOnlyDiagnostic，开启 `AS5047P_DMA_TERMINAL_FIX`。
仅允许exclusive identification + compact FOC-first；默认OFF。
原A候选BIN/ELF和正式B字节保持，正常B不启用新hooks。

修改文件：

- `firmware_common/as5047p_dma_engine.c`：可选终态认领/开始准入hooks，默认预处理移除。
- `firmware_common/as5047p_dma_stm32.c`：候选固定port绑定。
- `firmware_common/as5047p_dma_deferred.inc`：认领状态、TIM2截止检查、sticky-stop仲裁。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：独立候选配置。
- `tests/test_encoder_terminal_fix.py`：实际engine/deferred联合边界回归。

## 终态线性化

成功路径在Complete进行StopWord/CS/deadline清理前：

1. 读取实时TIM2计数，不能沿用较早的Guard(now)冒充完成时刻。
2. 若已达到原deadline（200us），调用原物理DeferOff并转换为TIMEOUT；
   已存在的urgent IO/control/timeout同样优先，不发布成功。
3. 若尚未到期且无urgent，使用一个对齐volatile32位状态认领本事务终态，
   以DMB发布；TIM2以后不再对已认领的这一事务触发transaction timeout。
4. 发布后再次检查urgent：若TIM2在检查/认领之间抢占，sticky停机事件获胜，
   只发布失败。绝不重新打开SD/MOE，也不清除已锁存fault。

因此成功199us认领后即使清理跨过200us，也不再产生同事务的第二个TIMEOUT；
但若数据验证/实时认领已到200us或更晚，仍立刻物理关闭，不回填199us。

优先级契约保持：ADC2 > encoder event3 > deferred4。
TIM2先抢占时urgent先发布；bottom half认领后再遇到截止事件，TIM2才忽略该旧截止。
没有新增PRIMASK/BASEPRI/global mask、RTOS API、循环/等待、printf或动态分配。

control watchdog检查位于transaction deadline之前且不受terminal_claimed影响，
真实DMA/IO错误同样优先；不是把所有urgent过滤掉。
新事务开始时清除旧成功认领；有sticky urgent时拒绝新事务，不自动恢复。

## 未改

- Transaction200us、guard2us、周期1000us、sample-age1500us、control-watchdog2500us。
- NVIC：ADC2、TIM2/RX/TX3、TIM6 deferred4及现有TIM7配置。
- FOC/current PI/speed PI/变换/SVPWM、one-cycle pending/entry commit、当前判别器/
  CUR_CONFIRM/CURRENT_INVALID/硬过流/编码器保护/其他阈值。
- 本轮Rs100us/400ms、reject-only策略和gap预算。

## 验证

新增2项测试（生产engine/deferred，generic ops与fixed callbacks各在-Os/-O2编译执行）：

- 199us完成，清理处200us TIM2抢占：只成功一次，无多余fault或物理OFF。
- TIM2在认领前获胜：立即OFF，只失败一次，不发布成功、不恢复输出。
- 认领后截止中断：无第二终态。
- 实时时钟200us、旧调用参数199us：拒绝成功，原deadline不延长。
- control stale/IO错误仍关断；重复deferred service不重复发布失败。
- 下一事务重新接受自己的截止保护；sticky fault后不能隐式开启下一事务。
- 跨32位微秒计数回绕，199/200边界保持。
- 原完整deferred fixture含35/50us模拟FOC黑窗、所有50相位及其他既有协议测试仍通过。

另有：原saved-race2项（开关OFF仍能复现，原证据可解码）、
原A/B协议/事务host CTest6项、全部motor-ident相关50项通过。
共60项所选测试通过，不声称全仓测试或实机WCET。

日志：`tmp/encoder-terminal-fix-tests.log`、`tmp/encoder-terminal-legacy-race-tests.log`、
`tmp/encoder-terminal-existing-host-tests.log`、`tmp/encoder-terminal-motor-ident-regression.log`。

## 构建

新A编译通过：Flash214764/229376B、RAM130864/131008B，链接剩余144B。
较上个候选多136B Flash/128B RAM（含新增RAM段代码），没有缩减堆/任务栈预留。
RAM余量较小，下一次板测仍需核验实际任务栈与时序；不能把链接余量视作可用任务栈。
已有unused/RWX warning集合与前候选一致，无新增类别。
未重新构建正式B，验证其原BIN哈希未变。

BIN SHA256 `2e0661646b6bedc372c7d7f4209e4dc4f5279f23a1082f0d9992c680b11c7b2f`。
ELF SHA256 `6a55c7148828a5eb613dcb26dfa969b24eed9d7ec99091b5cb021c47bd1d261a`。
旧精确pinned上板runner不得接受此镜像；之后人工板测需新pins和当前B832基线，
不复用旧stage收据，不自动注入/重试。

## 尚未解决/不能声称

此修复消除“成功终态收尾时被旧截止再次判失败”的竞态。
它不会把真正耗时超过200us的编码器事务变成成功。
上次事务为何已耗199us仍缺逐阶段板端证据，优先级和200us阈值未改，
因此新镜像仍可能因真实事务超时或其他原保护退出。需人工板测验证。

# 编码器停止原因：同一事务成功后再次超时发布

本轮用户请求“查看原因”。只读取已保存RAM/ELF/收据，静态分析现有驱动，
并在host模拟时序；未访问串口/调试器、刷板/复位、注入电流或修改生产固件。
板端保持上一轮恢复B832、输出OFF/CPU halt；不作新的硬件状态宣称。

## 数据可信边界

原始收据 `tmp/motor-ident-rs50-run-1792501108997244100.json`。
只读解码器 `tools/encoder_saved_fault_report.py` 校验同会话ELF、RAM SHA256及精确ABI：
first_fault104B、publication60B、engine88B，ARM short enum诊断字段1B。
解码输出 `tmp/encoder-saved-fault-analysis.json`。

## 同一事务的精确证据

| 事件 | TIM2 us | 相对起点 |
|---|---:|---:|
| engine.started_us | 8030577 | 0 |
| 最后RX top half记时/word_rx_us | 8030732 | 155 |
| guard_us | 8030774 | 197 |
| 成功样本completed_us | 8030776 | 199 |
| deadline_us | 8030777 | 200 |
| 超时样本completed_us/快照now | 8030779 | 202 |

Publication保留的两份完整样本：

- 成功bank：status0、sequence6538、sample_us8030732、completed_us8030776、
  elapsed199、raw2346、response0x892a。
- 紧邻失败bank：status2(TIMEOUT)、sequence6539、相同sample_us8030732、
  completed_us8030779、elapsed202、相同response0x892a。

引擎attempts6538、successes6538、failures1：没有新启动事务，却多了一个失败终态。
first_fault valid1/status2/phase0(IDLE)/frame1，IPSR70=TIM6_DAC deferred service。
快照时DMA RX/TX CNDTR均0，CCR均0，SPI_SR2（TXE，无BSY/OVR/MODF/FRE），
dma_isr0。计数timeouts1、dma_errors0、schedule_misses0、control_stale0。
defer_urgent2、defer_fault_serviced1、defer_fault_flags_valid0。

据此可确定：该事务已有成功终态，随后被deferred urgent TIMEOUT再次发布为失败。
不是“SPI一直没收到数据”的简单情形，也不是Rs累计电流拒绝/FOC50us超时。
不能由停止后清理过的寄存器宣称原始中断标志从未出现任何异常；
核心证据是同会话双bank、相同起点/RX时间和attempt/success/failure关系。

## 软件缺陷路径

`as5047p_dma_deferred.inc`：

1. priority3 TIM2 top half在200us截止到达且engine仍非IDLE、CC1仍使能时，
   `DeferOff(AS_DMA_TIMEOUT)`物理关闭SD/MOE并置defer_urgent。
2. priority4 TIM6成功收尾可以在此时被TIM2抢占。
3. bottom half下一次入口只要defer_urgent非0且未服务，就无条件`AsDma_Fail`，
   没有再次核对该事务是否已成功终结。

`as5047p_dma_engine.c::Complete`：

1. 成功路径使用调用时传入的now，先StopWord/CS/deadline callbacks。
2. 然后才state=IDLE、sample.status=OK、successes++、sequence++并通过Finish发布。
3. 在callbacks执行期间，engine仍显示活动且deadline可能还使能；
   higher-priority TIM2可把截止事件标为urgent。
4. 成功收尾随后继续并发布OK；下一次TIM6又按旧urgent对已IDLE的同事务调用Fail。

保存的“成功199us→失败202us/phaseIDLE”与上述完成收尾/截止竞态吻合。
实际中断PC、TIM2入口时间和每个guard延迟没有保存，不能声称已证明抢占发生在哪条机器指令。

## 离线复现（生产代码未改）

新增 `tests/test_encoder_saved_completion_race.py`：

1. 校验真实保存样本的双终态证据。
2. 重用原完整deferred测试夹具，并执行原有测试；以实际引擎和实际deferred.inc，
   在成功Complete的StopWord回调中模拟TIM2于200us抢占，
   复现同一attempt成功199us、下一次服务失败202us、故障phaseIDLE。

在-Os/-O2、-Wall/-Wextra/-Werror/-pedantic下通过，共2项诊断测试。
日志 `tmp/encoder-saved-completion-race-tests.log`。
这是可行交错的证明，不是实机WCET或中断指令轨迹。

## 另一个未精确定位的问题：200us预算余量不足

成功解析此事务已经耗到199us，只余1us。DMA最后RX top记时155us、guard197us，
说明数据已收到后软件协议推进/收尾仍有可观延迟，但没有每阶段完整快照。
ADC priority2高于编码器event3/deferred4，多个2us guard阶段在FOC负载下被延迟是合理嫌疑；
不能仅凭这次数据断言所有延迟都由ADC造成，或建议盲目提高编码器IRQ优先级。

## 后续修复建议（本轮未实施）

应修正同一事务完成/超时的单一终态仲裁和截止边界，而不是简单增大200us或删除编码器保护。
要求：真正未完成事务到期仍立即物理关闭；已完成事务不能被旧截止事件再次发布失败；
不可在真实保护已关断后擅自重启/重新使能输出；保留epoch、deadline和新事务隔离。
随后另测编码器整次事务在FOC负载下的最差耗时与guard排队，解决1us余量问题。
本轮仅定位，未改变任何控制算法、IRQ优先级、保护阈值或正式B。

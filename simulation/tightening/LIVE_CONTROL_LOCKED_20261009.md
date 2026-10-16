# 当前实机控制入口：启动被诊断固件拒绝

用户要求直接尝试控制后，先做只读 SWD/UART 核验，确认当前 A 槽确实是既有
硬锁定 ADC 诊断固件。运行代码回读与固定 SHA-256 完全一致：
`fb98a49edeec94b696d616e990f822f1a8c10dccfd12f0308510e1747cda52ac`。
FW 元数据为 CURRENT=A、CONFIRMED=A、PENDING=-、GEN=365。

随后仅对已核验的锁定固件提交 **一次 START 接口拒绝测试**，返回：

```text
7803 ERR 103 ZERO_DIAGNOSTIC_COMMAND_ONLY
```

这只证明命令到达解析器且诊断白名单拒绝运动，不是 107 rpm 测速成功。
该诊断编译分支没有正常电机控制任务；PowerStage_Enable/PWM_SetDuty 硬关闭或无操作。
没有 SET、SAVE、清故障、解除锁定、复位、刷写或实际电机动作。

前后 ZERO STATUS 均为 PROFILE=LOCKED_DIAGNOSTIC、LOCK=1、MOTOR_READY=0，
SD=MOE=CCER=CEN=FOC=0。STATUS 为 MODE=IDLE、BUSY=0、START_REQ=0、IqRef=0mA。

一次性主机检查最后使用 fields() 查询混合大小写 IqRef 字段时出现 KeyError；
不是板端故障。之后仅重新读取 FW/ZERO/STATUS，并直接解析原始 IqRef 文本完成
后置核验，没有再次发送 START。当前状态与 GEN=365 均不变。

代码/原始缓冲只读证据：
`safety_backups/adc-dma-raw-live-20261009/readback-1791547035745463300.json`，
4096 对原码仍与此前 UART 导出完全一致、CRC=4913ACF7。该历史捕获仍报告
zero_qualified=false、motor_qualified=false，不能把传输一致性当作采样合格。

真实带电运动需要正常控制固件、已核对接线和现场状态，以及实际采样/启动资格；
当前诊断接口拒绝动作不能通过清锁存或放宽保护来规避。此次停止在受控拒绝结果。

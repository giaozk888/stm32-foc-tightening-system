# Ld/Lq 电压生效—ADC采样对齐核验（只读离线）

## 结论

采集数据存在，并不是电流读不到或六次都触发运行时故障。原解码器先在
`latch_evidence.verified=false` 处停止，因此仅报告TIMING_UNQUALIFIED；
此前只用这条错误解释全部原因不够完整。

本次对精确镜像、各段Flash/RAM哈希、寄存器配置、实际控制顺序、芯片文档和
离线模型残差进一步核查：

1. 数字时序可以从现有代码和同镜像证据建立明确的**推导模型**，不是完全未知。
2. 当前精简profiling没有保存逐次CCR提交CNT/DIR/DWT及详细geometry，无法把
   推导冒充物理aperture/相电压实测。
3. 更重要的是，按推导对齐进行理想模型检验，4段连续数据的最小电流预测残差
   仍超过原5mA门限。另2段有缺样且丢失中间电压命令。不能仅改verified字段出数。

没有刷写、复位、连接硬件、改变控制/保护/阈值或写入参数；B保持上次恢复状态。

## 证据与数字时序

精确A BIN `13b237a70625218bfddb8924b13022a95410b1313f14547238036de2f9e5c786`。
ELF `08f4fe731598162155fd34cb4432a208d5e6cd5a40dabde2c68185c152b06ea0`。
批次 `tmp/motor-ident-l-repeat-batch-1792559788606362800.json`。
六段二进制RAM与JSON帧逐字段比对一致。

|项目|当前值/依据|
|---|---|
|TIM1|170 MHz、PSC=0、ARR=4249、center-aligned1、RCR=0|
|ADC触发|CH4 PWM2、CCR4=4184，TRGO2=OC4REF，上升沿|
|ADC1/2|双注入同步、42.5 MHz异步内核路径、12.5 cycles采样|
|采集时快照|各段ARR=4249、CCR4=4184、CR1=49(0x31)、RCR=0、JSQR=672(0x2a0)|
|preload|实际commit函数逐次校验OC1PE/OC2PE/OC3PE；写的是预装载值|
|实际提交|ADC IRQ入口、计数向下，验证余量足够后才写CCR1/2/3|
|采样帧Vdq|该电流帧FOC刚生成的电压命令，并非采样时已施加的电压|
|时间戳|`cl_frame.source_us`属于软件帧owner，不是物理sample/hold边沿|

RCR=0在TOP和BOTTOM都有UEV，不能笼统说“只在BOTTOM更新”。但当前入口提交
强制DIR向下，即已经过TOP，当前这组三个store的下一个自然UEV才是BOTTOM。
若没有这条DIR/余量准入，仅凭RCR=0就指定BOTTOM是不充分的。

令U(k)为第k帧新计算的电压命令，I(k)为本帧采样电流：

```
上数CCR4触发ADC(k) → 接近TOP完成采样 → TOP更新(此前的preload)
    → ADC IRQ(k)向下数时提交U(k-1) → FOC(k)生成pending U(k)
    → BOTTOM加载U(k-1) → 下一次接近TOP采到I(k+1)
```

因此从I(k)到I(k+1)的区间，前一部分使用U(k-2)，BOTTOM后使用U(k-1)。
不能用同一行的U(k)直接解释I(k)，也不能把闭环电流上升时间直接当电机L/R。
这里U仍是PWM平均电压命令，不是仪器测得的实际相电压。

## 半周期位置：推导，不冒充测量

依据本工程定时器模型2*ARR=8498 ticks，约49.988us；触发点距TOP65 ticks，
约0.382us。DS12288表66给出CKMODE=00下注入触发采样启动延迟的范围；
连同12.5周期采样，以sample/hold结束作为取样点建模，可得：

- trigger到sample/hold结束：约56–64 timer ticks，即0.329–0.376us；
- sample/hold结束到TOP：约1–9 ticks，即0.006–0.053us；
- sample/hold结束到后续BOTTOM：约4250–4258 ticks，即25.000–25.047us；
- 对应区间分数约0.500118–0.501059，而不是离线合成例子的0.3。

这些值来自静态配置、datasheet边界及timer模型，不是示波器实测。
有限采样孔径、模拟前端延迟、PWM开关/死区、功率管压降与命令电压之间的差异
尚不能从这些日志直接量出。没有把该推导写入原capture的verified字段。

## 为什么剩余数据仍不能给可信电感

`FOC_HEAVY_PROFILE_ENABLE=0`精简分支在三次CCR store后更新commit次数和最小余量，
没有更新旧详细结构中的writes、entry/write_begin/write_end/worst或geometry。
所以这些字段全0表示**未采集详细记录**，不是“没有写CCR”或“实际CNT=0”。
原actual late=0和12.459us最小余量仍有效，但它们只能证明软件提交未晚，
不能单独证明每帧的模拟电压与物理电流取样精确同步。

对4个连续窗口，在Rs=0.78Ω假设下，复用原RL两段电压指数解的数学形式，
仅做离线假设模型残差检验：command lag=2，fraction分别取0.5和上述边界。
**没有伪造latch_evidence、没有输出电感数值。**

|窗口|最小单步电流预测RMS mA|原允许RMS mA|结果|
|---|---:|---:|---|
|Ld/1|16.58|5.00|超过，最优点触及搜索边界|
|Lq/2|27.63|5.00|超过，最优点触及搜索边界|
|Ld/3|21.03|5.00|超过，最优点触及搜索边界|
|Lq/3|33.65|5.00|超过，最优点触及搜索边界|

上述fraction范围内结论不变。Ld/2有5个seq不连续间隔、Lq/1有1个；部分帧的
pending source也不再是seq-1。被拒绝帧仍可能生成新的控制命令，单凭留下的32帧
无法恢复缺失区间的完整电压序列，不能插值补齐后当作实测。

连续窗口的最大相邻轴电流变化分别约50.29、85.76、70.91、101.99mA，
与50mA测试阶跃同量级或更大。这支持“当前动态数据与简化RL模型不匹配/噪声较大”，
不单凭此归因为某个硬件损坏或相序错误，也不排除时间常数低于现有20kHz分辨率。
Rs本身仍是临时有效电阻假设，死区/实际电压模型误差也会影响电感估计。

## 下一步需要补的证据

先补诊断记录的对齐链：applied/pending command source seq、sample seq与时钟几何，
step前后一个连续窗口的原始电流及有效CCR命令；只保留低成本整数记录，
不改PWM调度/UDIS/RCR/ADC频率。必要时用CH4或安全低压数字标记核对触发/加载相位。
在此之前不能把“采集DONE”升级为“参数通过”，也不应无目的重复同样六段实验。

源与文件：`tools/motor_ident_alignment_audit.py`默认仅输出JSON，不访问设备。
结果 `tmp/motor-ident-l-alignment-audit.json`；新增3项离线测试包含已知解析RL、
缺样不插值以及实际Flash/RAM哈希检查。控制代码和原始证据未改。

官方依据：

- [RM0440：TIM1更新事件、CCR preload和PWM模式](https://www.st.com/resource/en/reference_manual/dm00355726.pdf)
- [DS12288：STM32G474 ADC特性表66](https://www.st.com/resource/en/datasheet/stm32g474pc.pdf)

# 电流采样尖峰与 FOC 时延：公开资料检索及项目建议

检索日期：2026-10-16。范围：STM32G474、20 kHz FOC、低边 IU/IV 电流反馈。此次只检索资料和回读本地代码／记录，没有修改固件、复位、刷写或启动设备。

## 先说结论

公开资料中有成熟方法，也有直接相关论文。对本项目最有价值的顺序是：消除不必要的计算和中断抢占 → 明确 PWM 的实际更新边界 → 在有效低边窗口内选择采样时刻 → 根据模拟波形优化前端。更复杂的筛选或观测器应在这些基础工作之后评估。

需要分清三种时间：模拟信号从开关扰动恢复的时间、算法实际占用 CPU 的时间、采样到 PWM 真正生效的总延迟。三者不能混为一谈。保护链也不能靠反馈滤波代替。

## 现有项目证据

来源：[候选版上板记录](FOC_RC_PROTECTED_CANDIDATE_20261016.md) 和 [采样窗口对照](FOC_RC_SAMPLING_CANDIDATE_20261015.md)。

- 最新单次试运行的筛选零点通过，首次停机是 `CL_COMPUTE_LATE`，不是筛选零点失败。
- 同一失败帧：`WALL_CYC=8287`，在 170 MHz 下约 48.75 µs；其中被现有插桩计入的中断抢占 `IRQ_CYC=3868`，约 22.75 µs，剩余约 26.00 µs。保护的微秒计时为 50 µs，其测量边界与 DWT 不完全一致。
- 这不是“整个 FOC 数学计算花了 50 µs”。现有抢占统计也不等于已逐个定位所有中断成本，不能把 22.75 µs 全归因给编码器。
- 当前延后触发方案在 50% 参考占空比的定时器模型下，低边开通到触发约 11.61 µs，触发到下一计数底部约 25.38 µs。后者还需要扣除 ADC 转换、进入中断和 CCR 提交等成本。
- 低于 50 µs 的周期截止与赶上指定 PWM 更新边界是不同要求。实际影子寄存器装载事件仍未充分测量，粗粒度底部告警不等于已测得每次物理提交失败。
- `firmware_common/protected_closed_loop.inc` 的 `ProtectedLoop_SetDuty()` 在检查 `CL_RUNNING` 前调用窗口规划器。在 READY 的功率关闭计算场景，规划结果可能被直接丢弃。这是值得优先测量和优化的路径；跳过它不能证明 RUNNING 路径也已满足截止时间。

## 尖峰：已有工程方法及适用边界

### 1. 低边有效窗口内、避开开关边沿采样

低边分流电阻不能在任意 PWM 相位都准确反映绕组电流。应留足死区、驱动传播、放大器恢复及 ADC 采样保持时间；在有效窗口内选点，而非无限后移采样。

TI 的 [TIDA-00778 参考设计](https://www.ti.com/tool/TIDA-00778) 涵盖一／二／三分流电阻方案，其双／三分流方案给出小于 1.5 µs 的建立时间。说明快速前端能减少等待，但这是该参考设计的性能，不是现有 Genbotter 驱动板的实测值。[设计指南](https://www.ti.com/lit/ug/tiducy7/tiducy7.pdf) 还说明三分流方案可按窗口选择两相采样，并建议 Kelvin 取样及合理的输入／输出滤波器位置。

项目建议：在现有双 ADC 同步采样基础上记录“异常点相对最近 PWM 边沿的时间”，再做保持其他变量不变的相位对照。先寻找最早可用的稳定窗口，不直接把 10 µs 预算缩成其他数值。

### 2. 地参考、回流和模拟输入驱动能力

TI 的 [低边电流检测布局说明 SSZT805](https://www.ti.com/document-viewer/lit/html/SSZT805/GUID-5F278960-BA94-4362-9099-87ABC753A4D6) 解释了共享导体压降如何产生偏移，以及 Kelvin 连接的作用。直流导通不意味着高频下两点等电位。

ST 的 [AN2834：优化 ADC 精度](https://www.st.com/resource/en/application_note/an2834-how-to-optimize-the-adc-accuracy-in-the-stm32-mcus-stmicroelectronics.pdf) 讨论了参考供电、数字串扰、源阻抗及 ADC 采样保持电容带来的误差。不能为提高速度一味缩短 ADC 采样保持时间，也不能一概靠增大外接电容解决。

项目判断：此前短地线改善接地输入读数，与参考地／回流问题相符，但不能据此证明所有电流尖峰都由公共地造成。拔六根控制线同时改变回流、接口负载和耦合路径，也不能单独证明是某一种 EMI。

### 3. 优化模拟前端，而非盲目加大电容

若实际前端确为项目记录引用的名义 100 Ω 与 100 nF，单个理想 RC 的时间常数为 10 µs。对孤立阶跃，约 3τ 后仍有 5% 初始偏差，约 4.6τ 才到 1%。这只是模型解释，不是对实际周期低边电流信号误差的计算。

因此，较大电容可能降低高频噪声，同时延长建立时间、增加控制相位滞后。元件更换须结合实际运放稳定性、输出驱动、噪声和 ADC 输入条件评估，不在这里指定新的 R/C 接法。

TI 的 [SBOA160：具有 PWM 抑制的在线电流测量](https://www.ti.com/document-viewer/lit/html/SBOA160) 说明共模阶跃如何在放大器输出形成毛刺，以及专用 PWM 抑制电路如何减少扰动。这主要针对在线相电流检测；不能把 INA240 等在线方案直接当成现有低边输出的无条件替换件。

### 4. 数字筛选与模型补偿

四点趋势筛选可修补符合判据的短暂异常，但存在样本年龄，并可能把真实变化和噪声混淆。预测器／观测器可减少等待未来样本的需要，却引入电机参数、模型和失配风险。不能声称“零延迟消除任意尖峰”。

对本项目：暂不继续堆叠重滤波；先对现有算法分段计时，再比较相位感知的有效性判断和有界预测。任何新算法都要以已有故障窗口和真实电流阶跃做离线对照，保留样本质量信息及独立保护。

## 缩短时间：本项目优先级

| 优先级 | 方向 | 具体工作 | 不能据此推断 |
| --- | --- | --- | --- |
| 1 | 减少状态不需要的工作 | 非 RUNNING 路径提前返回；运行提交前保留 STOP／关断竞争复核 | READY 快了不代表运行提交也快了 |
| 1 | 定位并压缩抢占 | 分别测 TIM7、编码器定时器、DMA 等入口与最坏耗时；非关键处理延后，评估采样与编码器相位错开 | 不能靠降低独立关断优先级或全程关中断换成绩 |
| 2 | 精简关键路径 | 规划器、筛选、PI、SVPWM、提交各自计时；移走日志格式化、重复转换和不必要诊断统计，保留必要检查 | 不预先承诺能节省若干微秒 |
| 2 | 数学加速对照 | 比较现有快速三角函数与 CORDIC 的完整调用，包括类型转换、精度及共享访问 | 官方相对 sinf/cosf 的倍数不是现有算法的加速倍数 |
| 2 | 热代码布局 | 根据反汇编／链接映射选择仍在 Flash 的热点迁入合适 RAM，确认启动复制和调用链 | 不把整个程序移 RAM；当前静态余量仅约 5.9 KB |
| 3 | 采样／更新协同设计 | 核实 TIM1 预装载生效事件，安排能按时完成的采样及更新相位 | 不直接关闭预装载或异步强写 PWM 来消除告警 |
| 后续 | 延迟补偿／观测器 | 明确采样时刻、滤波样本年龄、角度时间戳、PWM 生效时间后再建模 | 补偿不能消除随机超时或错误输入 |

ST [AN5325](https://www.st.com/resource/en/application_note/an5325-getting-started-with-the-cordic-accelerator-using-stm32cube-stmicroelectronics.pdf) 的 NUCLEO-G474RE、170 MHz、特定 IAR 配置基准：浮点输入输出转换在内的 CORDIC 正余弦为 79 cycles，标准 `sinf`＋`cosf` 为 416 cycles。约 0.46 µs 对 2.45 µs；这是特定基准，不是本项目收益预测。本项目已经调用 `FocFast_SinCos()`，必须与它比较，不能重复计算优化收益。

ST [AN4296：CCM SRAM 使用](https://www.st.com/resource/en/application_note/an4296-use-stm32f3stm32g4-ccm-sram-with-iar-embedded-workbench-keil-mdkarm-stmicroelectronics-stm32cubeide-and-other-gnubased-toolchains-stmicroelectronics.pdf) 及 [电机控制生态文档](https://www.st.com/content/st_com/en/ecosystems/stm32-motor-control-ecosystem.html) 提供关键代码 RAM 布局的依据；本次 AN4296 完整 PDF 打开失败，仅核对到了官方索引摘录，不据此报告具体提速数字。DMA 缓冲地址可达性需按具体芯片及地址映射核查。

## 直接相关的研究

以下按题目／DOI 去重，按本项目相关性排序。未做系统综述或引用量排名，不报告未核验引用次数。

| 文献 | 研究内容与本项目关系 | 核验程度 |
| --- | --- | --- |
| Xin Cheng 等，2024，*Sensors* 24(5):1538，**Analysis and Compensation of Phase Current Measuring Error Caused by Sensing Resistor in PMSM Application**，DOI [10.3390/s24051538](https://doi.org/10.3390/s24051538) | 分析分流电阻寄生电感／电容造成的采样误差及转矩波动，提出 PI 型观测补偿。支持“误差不一定是随机 ADC 噪声”的研究方向，不证明本板根因 | 已交叉核对出版页与 PubMed 索引摘要；全文页访问受限，未做全文复现实验审计 |
| **Virtual Viable Sampling Timing via CPWM-DPWM Switching for Current Measurement Errors Calibration in PMSM Drive**，*IEEE Transactions on Industrial Electronics*，2023-12-14 在线发表，DOI [10.1109/TIE.2023.3335319](https://doi.org/10.1109/TIE.2023.3335319) | 利用调制方式切换获得适合电流误差校准的采样条件。说明“采样窗口与 PWM 联合设计”确有专门研究，不是仅更换滤波器 | 已核对 IEEE 题目、DOI、在线日期与摘要摘录；未获得完整正文，不声称能直接移植 |
| M. Hu、W. Liu、S. Niu、X. Yuan、K. T. Chau，2026，*IEEE Transactions on Transportation Electrification* 12(1):641–651，**Digital Current Control for Permanent Magnet Synchronous Machine Drives With Fractional-Step Computation Delay**，DOI [10.1109/TTE.2025.3619989](https://doi.org/10.1109/TTE.2025.3619989) | 对非整周期计算延迟建模，结合电压双更新改善动态性能；强调计算及调制延迟共同影响电流环，不是把截止阈值扩大 | 已核对作者机构[存档元数据](https://ira.lib.polyu.edu.hk/handle/10397/116302)并读取[接收稿](https://ira.lib.polyu.edu.hk/bitstream/10397/116302/1/Hu_Digital_Current_Control.pdf)相关内容 |

## 建议执行顺序与验收口径

1. 在离线候选中优化状态分支和热路径，保持保护语义不变；通过竞态与数值回归。
2. 功率关闭时分别测纯 CPU、逐类抢占、整个 ADC ISR，以及从 ADC 触发到实际 PWM 更新的时间。统计最大值与超期次数，不只平均值。
3. 在不改变接线／供电等其他变量的条件下，做采样相位对照，统计异常率、偏差及相对边沿位置。数字记录只能定位相关性；模拟尖峰幅度与建立时间仍需合适的示波器测量。
4. 只有掌握模拟建立与更新边界后，才决定是否需要修改模拟前端、改变采样拓扑或引入延迟补偿。

结论：优先减少“干扰、无效等待、不必要工作和抢占”，而非继续拉长滤波窗口或删除超时保护。搜索结果给出了可实施路线，但没有证明现有硬件已经适合带电闭环。

## 检索可用性说明

专用学术 MCP 数据库工具未接入；按文献检索技能尝试 OpenAlex 备用脚本时，本机网络访问被阻止。随后通过可用网页检索查询厂商原站、出版方和作者机构仓储。部分 PDF／出版页完整打开失败，已在上文标明；未使用论坛转载的数字作为本项目性能证据。

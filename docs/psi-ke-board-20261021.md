# ψf/Ke 辨识板测记录

## 非活动 A 暂存完成，尚未激活

用户确认12 V关闭、MCU供电，转轴解锁、负载脱开且电机空载固定并有防护，
U/V/W、IU→PA0、IV→PA1、PC6→CTRL_SD接线不变，电源12 V/限流0.5 A，
操作者可全程在现场立即断电后，才执行暂存。

- A：`PsiKeIdentificationDiagnostic`，215860 B。
- BIN SHA256：`a260cc660b1c6bedaf8bc098c31e53505fd1c7fdd11595a9a1b95d985d186859`。
- 预板测14项回归通过：`tmp/psi-preboard-tests.log`。
- 暂存回执：`tmp/psi-ke-stage-1792588273598896700.json`，PASS。
- 两次完整独立回读通过，A payload与固定镜像一致；B/boot/private/启动元数据未变。
- 完整Flash SHA256：`81a01d824e65159739c3e147f2314838b8cd8f6580c59a4fa57630aa6a128aa3`。
- 启动选择仍B932、pending=none；activation=false、motor_commands=0。
- MCU已停住，SD=0、BDTR=0、CCER=0；未启动电机。

等待人工开启12 V、限流0.5 A并确认无报警后，才执行受监督100/200 rpm固定批次。
300/400 rpm跳过；BEMF前馈OFF、控制参数及独立保护不变；保护触发不重试。

## 一次批次采集完成

用户确认“开了，无”，结合其整组现场监督确认后执行一次固定批次。
batch：`tmp/psi-ke-run-1792588363118117500.json`，complete/PASS（表示采集完成，不表示参数已资格化）。
原健康试运行/自动确认正常，确认A935。每点均只发送一次显式PSI RUN，未发正常START。
100点质量失败后保存完整关断证据，再按原计划复位同一确认A、重新校准/预检执行200点；
未重试失败点、未提高任何限幅或保护阈值。300/400按计划SKIPPED，没有发送运动命令。

| 项目 | 100 rpm点 | 200 rpm点 |
|---|---:|---:|
| 单点回执后缀 | `-100.json` | `-200.json` |
| 零点valid/reject/total | 4000/45/4045 | 4000/39/4040 |
| 零点U/V | 1560/1563 | 1560/1563 |
| 固定窗口有效/拒绝观察 | 未建立窗口 | 40/2（共42） |
| 窗口平均机械速度 rpm | 无有效窗口 | 197.3255 |
| mean Id A | — | +0.00585984 |
| mean Iq A | — | +0.13237336 |
| mean Vd命令 V | — | -0.01716777 |
| mean Vq命令 V | — | +0.33369112 |
| mean Rs*Iq V | — | +0.10325122 |
| mean omega_e*Ld*Id V | — | +0.00002376 |
| mean bemf_est V | — | +0.23041613 |
| mean omega_e electrical rad/s | — | +206.63876 |
| mean ψf Wb | — | 0.0011176220 |
| ψf样本SD Wb | — | 0.0005227939 |
| 单点Ke相峰值 V/(机械rad/s) | — | 0.0111762201 |
| ψf变异系数（SD/均值） | — | 46.78% |
| MCU窗口质量判定 | QUALITY_FAILED | PASS |
| FOC wall max us | 32.3882 | 32.8353 |
| deadline miss / actual CCR late | 0 / 0 | 0 / 0 |
| actual最小margin us | 15.1412 | 15.1412 |
| CUR_CONFIRM enter/clear/fault | 101/101/0 | 113/113/0 |
| 编码器/电流/计时独立保护 | 无 | 无 |

两个完整Flash/SRAM文件的SHA复核通过；每点原B/boot/private保持不变，结束均SD=0、MOE/AOE=0、CCER=0、CPU halted。
200点固定窗口42帧R/I/E/S均完整；其中40帧参与统计，2帧被准入排除，不伪造或补零。
其窗口完成时已满足2秒；观察时间与source时间分别保存，不按串口相邻行混合。

### 为什么100点没有数值

电机并非未运动：编码器净位移约2720.79°，约7.56圈（包含减速阶段，不是独立机械计圈）。
该点共101个20 Hz观察：14个仍处参考变化阶段，37个实测速率超过100 rpm的±5 rpm稳态带，
50个瞬时满足准入；但最多只有连续4个合格观察，未满足连续500 ms，因此窗口没有开启。
这属于辨识稳态质量不满足，不是电流/编码器保护停机。
最终RAM中未累积means的0只是初始化值，**不能报告为100 rpm实测ψf=0或转速=0**。

### 目前不能给多点最终标定

batch.analysis.candidate=null，reason=`NEED_TWO_DISTINCT_VALID_SPEED_POINTS`；只有200点合格。
上表的ψf/Ke只是单点模型估计，不能冒充带offset的多点拟合结果，也没有输出虚假R²。
更重要的是ψf的样本波动约47%，不是一个可直接投入前馈的稳定标定值。
该标准差是样本离散度，不是测量不确定度或均值置信区间。
Vq仍是PWM命令电压，Rs=0.78 Ω/Ld=20.03 µH仍是用户指定假设；
本批不能确认物理永磁磁链准确性。没有采用厂家Rs重新混算，也没有修改PI。
不自动写入BEMF、KVS或正式B，不追加240 rpm等未授权点、不重试100点。

用户确认12 V关闭后，仅通过原bootloader流程恢复原B启动选择。
恢复回执：`tmp/psi-ke-restore-1792588592105201500.json`，complete/PASS。
确认B936，pending=none，B长度227964、CRC=627317606，B/boot/private及A应用保持不变。
输出关闭、CPU停在B入口，b_application_not_run=true、motor_commands=0。
本批到此结束，不追加测试、不自动采用单点估计。

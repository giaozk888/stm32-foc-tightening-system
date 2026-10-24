# 新参数电流PI：现有完整状态机的空载实测

## 范围与结果

根据人工要求，跳过50 mA单点电流对照，改用已接入新PI的完整FSM候选。用户在12 V关闭时确认解除锁轴、负载脱开、电机空载固定并保留防护，之后确认12 V/限流0.5 A、无报警且可立即断电。

只发送一次原START；没有自动重试、强制CONTACT、提高限幅或保护阈值。目标240 rpm、Iq限幅±0.50 A、行程20000°、RUNDOWN超时8000 ms、板端总lease12000 ms均保留。

**电机建立了持续转动并跟踪约240 rpm。空载未发生接触，约8秒后按原FSM规则进入RUNDOWN_TIMEOUT并停机。不能报告完整带工件拧紧成功，CONTACT/TIGHTEN/HOLD/DONE未由本次空载验证。**

## 镜像与收据

- A：`CurrentPiIdentifiedCandidate`，217428 B。
- BIN SHA：`aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e`。
- ELF SHA：`d015db4a488cefb4d17af5d59631731163c22a54d14aa41baef91708f19c3b77`。
- 暂存：`tmp/current-pi-fsm-stage-1792566598300280700.json`，双完整回读通过；B/boot/private/metadata未改。
- 运行：`tmp/current-pi-fsm-run-1792566696767741900.json`，预检通过、START一次、观测完整、输出关断及RAM/Flash快照保存。
- 恢复：`tmp/current-pi-fsm-restore-1792566834677593400.json`，成功恢复B888、pending=0，停在B入口，B应用未运行；SD/BDTR/CCER=0。

原运行收据pass=false和退出码1是因为它明确不是成功拧紧：终态RUNDOWN_TIMEOUT。该失败标记保留，不改成OK。

## 本次运行观察

- 143个运行中STATUS观察，编码器净观测位移约10378.72°，约28.83圈；稀疏记录不是机械实物计圈的独立校验。
- 记录中首次到216 rpm约在START后1.265 s，首次到240 rpm约1.784 s；有S-curve，因此不是电流环阶跃响应时间。
- 最后7个运行中STATUS平均239.23 rpm；运行中STATUS速度最高244.8 rpm，此值不是全采样率峰值。
- 2秒后STATUS样本平均237.46 rpm，平均绝对误差3.65 rpm。
- MCU统计起转延迟165.01 ms、加速段MAE9.17 rpm、匀速段MAE3.53 rpm、IqRef峰值0.35012 A、速度积分器峰值0.06623 A。
- MCU软件Iq反馈峰值1.26296 A，不是外部仪器确认的相电流。该值不能用IqRef限幅±0.50 A来掩盖，也不能在未分析窗口时断言是物理过流或纯采样尖峰。

同次精确ELF重解码的停机RAM：

| 指标 | 结果 |
|---|---:|
| FOC wall max | 31.6176 µs |
| deadline miss | 0 |
| actual CCR commit | 298899 |
| actual CCR late | 0 |
| actual minimum margin | 15.1412 µs |
| CUR_CONFIRM enter / clear / fault | 126 / 126 / 0 |
| unresolved最大连续 | 1 |

首次快照valid=1、domain=3（PROCESS）、fault_reason=3（RUNDOWN_TIMEOUT）；不是“完全没有任何失败记录”。快照protection_flags=0、encoder_errors=0、current_unresolved_consecutive=0、deadline miss=0；UART状态FLT=0。此次没有电流、编码器或FOC deadline/late保护停机，停止原因是原流程等待接触超时。

## 与历史旧PI参考对照

旧数据：`tmp/friction-fsm-run-1792494625353182000.json`，BIN与旧PI对照构建字节相同，SHA `3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899`。

两者完整RAM配方相同，均为240 rpm、0.105 A摩擦补偿ON、加速度FF ON、同样S-curve、旧速度PI与同样保护。离线工具核对镜像/ELF/Flash、重解码RAM的FF/摩擦统计与故障快照，输出 `tmp/current-pi-fsm-historical-comparison.json`。

| 指标 | 历史旧电流PI | 本次新电流PI |
|---|---:|---:|
| 起转延迟 [ms] | 182.04 | 165.01 |
| 最大速度误差 [rpm] | 81.78 | 67.61 |
| 加速段MAE [rpm] | 14.21 | 9.17 |
| 匀速段MAE [rpm] | 3.74 | 3.53 |
| 低速段MAE [rpm] | 8.28 | 10.22 |
| 速度超调 [rpm] | 6.01 | 6.15 |
| IqRef峰值 [A] | 0.42665 | 0.35012 |
| 软件Iq反馈峰值 [A] | 1.26692 | 1.26296 |
| 速度积分器峰值 [A] | 0.05719 | 0.06623 |
| 尾段稀疏速度平均 [rpm] | 239.97 | 239.23 |
| FOC max [µs] | 31.5765 | 31.6176 |
| deadline miss / CCR late | 0 / 0 | 0 / 0 |
| 终态 | RUNDOWN_TIMEOUT | RUNDOWN_TIMEOUT |

参考上加速段误差降低约35.5%、匀速段约5.6%、IqRef峰值约17.9%，但低速段误差、速度积分器峰值和超调并未改善。两次不是同批随机重复A/B，不能排除温度/摩擦/噪声/初始转角变化，不宣称上述差异全部来自PI。

本次证实候选能在这次空载工况运行，没有证明Rs/Ld/Lq辨识值准确，也没有提供电流环动态带宽的独立测量，不能用速度跟踪改善回填电感质量检查。

## 文件与后续

- `tools/current_pi_fsm_board.py`：独立受监督单次FSM板测，默认只核验文件，保留原START门禁、STOP/关断和原B恢复流程。
- `tools/current_pi_fsm_compare.py`：仅离线历史对照及精确RAM重解码。
- 对应脚本测试3项、比较测试1项通过；固件本轮无新增修改。

现场已关闭12 V，B启动选择已恢复，无追加测试。新参数仍只在A候选，未替换正式B。

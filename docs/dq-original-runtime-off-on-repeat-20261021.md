# 原运行镜像 DQ ON/OFF 第二组空载对照

两轮使用相同219300 B镜像：
`95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e`。
没有DQA ISR统计，没有刷入四种反号候选；OFF轮只核验同镜像、没有重刷。
240 rpm、Iq ±0.50 A、原PI/SCurve/加速度FF/105mA摩擦补偿与全部原保护保持。
两轮零点均1560/1563，不覆盖校准结果，但初始转子角/温度/机械阻力未严格复现。

| 指标 | 本组 ON | 本组 OFF |
|---|---:|---:|
| 一次START、原RUNDOWN运行 | 8秒 | 8秒 |
| 空载自然末态 | RUNDOWN_TIMEOUT | RUNDOWN_TIMEOUT |
| CONTACT / 独立保护 | 0 / 无 | 0 / 无 |
| 原稳定运动延迟指标 | 325 ms | 376 ms |
| 加速平均绝对误差 | 10.797 rpm | 12.186 rpm |
| 匀速平均绝对误差 | 3.867 rpm | 3.293 rpm |
| 末约0.35s STATUS平均速度 | 238.933 rpm | 238.043 rpm |
| IqRef绝对峰值 | 401 mA | 426 mA |
| 测得Iq绝对峰值（非平均） | 1192 mA | 1099 mA |
| 速度积分器峰值 | 112 mA | 123 mA |
| 既有速度统计超调 | 6.458 rpm | 6.270 rpm |
| FOC wall最大 | 33.3471 us | 32.5882 us |
| deadline miss / actual CCR late | 0 / 0 | 0 / 0 |
| actual CCR最小margin | 15.1471 us | 15.1412 us |
| CUR_CONFIRM enter/clear/fault | 142/142/0 | 150/150/0 |

启动延迟指command方向上filtered speed达到2rpm并连续50ms达标的窗口起点，
不是首次肉眼转动/编码器变化时刻。两轮不是扭矩/真实带工件拧紧验收。
脚本原样保存pass_=false/退出码1和RUNDOWN_TIMEOUT，未把超时改成OK。

## 与第一组的关系

旧第一组OFF/ON启动指标174/349 ms，加速误差7.413/10.467 rpm，
匀速误差4.416/3.517 rpm。
本组ON比OFF启动早51 ms、加速误差低1.389 rpm；OFF匀速误差低0.574 rpm。
原“开解耦必定使起转变慢、加速更差”的方向没有稳定复现，不能据旧单组定因。
同为OFF两轮174→376 ms的差异也超过本组ON/OFF间51 ms，提示重复性/初始条件
是不可忽略的混杂因素；这不是证明两模式完全等效或解耦一定有效。
本组不支持直接反号、调PI/放宽限幅来掩盖问题。

原运行镜像没有新增DQA全帧统计，因此启动首500ms同步电压、真实CCR反事实影响
仍未被这两轮测量，不能把离线量化计算写成实测因果。

## 回执及停机

- ON运行 `tmp/dq-fsm-run-1792583552935164100.json`
- ON恢复B924 `tmp/dq-fsm-restore-1792583654913763900.json`
- OFF同镜像核验 `tmp/dq-fsm-stage-1792583957339793400.json`，flash_programming=false
- OFF运行 `tmp/dq-fsm-run-1792584042069431100.json`

OFF独立保护回执VALID=0/FLAGS=0、最终FLT=0。first_fault domain3/reason3仅为
原状态机RUNDOWN_TIMEOUT，没有编码器超时或CURRENT_INVALID。
输出关闭、MCU halted，完整Flash/SRAM已保存，boot/B/private应用字节未变。
等待人工关闭12V后，仅恢复B启动选择，不再自动运行或重试。

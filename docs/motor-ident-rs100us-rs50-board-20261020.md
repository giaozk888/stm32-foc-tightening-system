# Rs100us候选：50mA单次板测

用户分别确认OFF/MCU供电/台架锁轴/外壳固定防护/原接线/12V限流0.5A，
授权仅非活动A；完整回读后再确认ON无报警且现场可立即断电。
仅执行一次RS50，最多400ms；不START、不自动重试、不升档、不进入L测试。

## 镜像和脚本

- preset `MotorParameterIdentificationRs100usDiagnostic`；BIN214596B，ABI1740B。
- BIN SHA256 `3f38586c511f688da8b66862d9a27ea8dce11b9c4b869f7bdc526a53bc1bae3e`。
- ELF SHA256 `3c62c253b0dc4c7dd796889db9d4d274ec77d6c7b1c93b85a058f913286cef47`。
- 独立 `tools/motor_ident_rs100_board.py`，精确B824基线/新镜像/ABI，
  在注入前查询并校验RS100/L55策略，停止后再次确认；显式100us快照解码。
- 原timing/gap helper新增可选解码上限参数，默认55不变；旧镜像pins不改。
- 新增3项无设备脚本测试通过；全部motor-ident相关43项通过。
- stage `tmp/motor-ident-rs50-stage-1792500462041048100.json` PASS，
  B/boot/private/metadata保持、完整独立回读通过，未立即激活。
- run `tmp/motor-ident-rs50-run-1792500507238711300.json`。

## 实测结果

校准和时序预检通过，明确ACK，只注入一次IdRef50mA/IqRef0。
预检和停止后策略均为 `RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55`。

- 终态STATUS4、REASON3=MID_CURRENT；N0。
- start_us=7982293，last_us=8018247，last_seq=157999，约35.954ms退出。
- REJECT17、GOOD701、MAX_RUN1：累计第17对触发原保留的最多16对预算，
  不是连续3对退出，也不是原硬过流4A故障。
- RS_GAPS2、SKIPPED2、MAX_GAP1：两次被判别器hold解释的单帧缺口已成功接纳。
- timing failure.valid0、context_valid0，没有本次MID_TIMING退出。

因此本次首次实机观察到新gap接纳分支工作，并运行越过此前初始57us退出阶段；
但没有保存每一正常间隔的max，不能声称本次确实出现并接纳了57us。
只可确认本轮没有时序准入失败，真实失败是累计current reject预算。

### 首次被排除的电流样本（不是终止的第17对）

| 字段 | 值 |
|---|---:|
| 相对开始 | 5711us |
| seq / pending_before | 157394 / 157393 |
| raw U / V | 1578 / 1593 |
| IdRef / IqRef | +0.050 / 0A |
| Id / Iq | -0.078956 / -0.302255A |
| previous Vd / Vq | +0.028955 / +0.009547V |

sample admission用`abs(Id)>0.20A || abs(Iq)>0.20A`排除估计样本，
此首次样本是|Iq|超0.20A。first_reject只保存首帧，不能据此推断另外16对幅值/方向。
Vdq为本帧PI前的上一计算命令，不能解释为物理相电压。

### 运行保护与时序

| 项目 | 值 |
|---|---:|
| FOC max | 35.5824us |
| deadline miss | 0 |
| actual CCR commits | 133948 |
| actual CCR late | 0 |
| actual min margin | 16.6412us |
| CUR_CONFIRM enter/clear/fault | 46/46/0 |
| 原fault/ADC fault/FOC fault | 0/0/0 |

未达到200ms稳态记录窗口，N0，不能计算Rs或进行L辨识，更未更新PI。
本轮未改变current预算或其他阈值以继续尝试。先STOP/ANALOG SAFE再读数据并halt。

## 收尾

用户确认12V关闭后，只恢复原B启动选择，保留B/boot/private和A候选字节，
不执行B应用、不再注入电流。恢复收据
`tmp/motor-ident-rs50-restore-1792500618687820400.json` PASS：
confirmed B828、pending0，SD/BDTR/CCER均0，MCU停在原B入口。

后续若要定位为何小Id命令下dq测量仍有孤立大偏离，应抓取更多被拒绝样本及相邻原码，
不能把增加时间容忍度等同于电流质量通过，也不能未经请求自动放大拒绝预算。

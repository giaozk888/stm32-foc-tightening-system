# Rs稳态与Ld/Lq瞬态的采样连续性分工

本轮只增加独立诊断A preset `MotorParameterIdentificationRsGapDiagnostic`，
继承已板测的TimingDiagnostic；开关 `FOC_IDENT_RS_GAP_ADMISSION_ENABLE` 默认OFF。
正式B、旧镜像、板端B820启动选择均未改，未访问设备/刷板/启动。

## 规则

| 模式 | 已确认hold导致的有效帧缺口 | 其他不连续 | 估计器处理 |
|---|---|---|---|
| Rs | 有界接纳恢复帧，不造丢失样本 | MID_TIMING退出 | 200ms后已有稳态抽取，仅实际accepted数据 |
| Ld/Lq | 仍MID_TIMING退出 | 仍MID_TIMING退出 | 32对连续瞬态；不插值，不拼接 |

Rs仅在以下全部成立时继续：

- seq差为2或3，对应中间缺1或2对；
- `current_hold_total - last_hold_count == seq差 - 1`，每个缺口都有判别器hold解释；
- 软件时间差在 `[45*seq差, 55*seq差] us`，不接受不合理时基；
- 累计跳过不超过16对，每个缺口不超过2对。

单拍seq+1仍要求45–55us。上述只是辨识accepted-frame质量准入，
不是放宽原ADC watchdog、硬过流、CUR_CONFIRM、CURRENT_INVALID或判别器。
16对为400ms/20kHz最多8000对中的0.2%新诊断预算，不是对控制保护阈值的修改；
该预算未板测资格化，后续不可声称已足够或直接继续放大。

原样本电流异常预算（累计16、连续3退出）、0.20V、2rpm、400ms/104ms、
独立任务限时、原保护和故障链保持。无时间延长、无自动重试、无自动升档。
出现gap时也先经过原参考检查，恢复帧的电流超包络仍记current reject并排除参数统计。
不会为缺帧填电流或运行额外PI；原PI/pipeline调用顺序未改。

持续拒绝或其他保护仍可能终止新候选，不能把“区分采样规则”理解为保证本次辨识通过。

## 数据和诊断

新增只读 `MOTOR TEST IDENT RS GAPS`，仅终态且非RUNNING可读：
`RS_GAPS / SKIPPED / MAX_GAP / BUDGET=16 / RUN_LIMIT=2`。
原first timing failure及UART/RAM上下文保持。
在Reference前读取本次hold差，成功后更新last_hold_count，hold期间不刷新参考owner计数。

新增16B：`rs_hold_delta / rs_gap_events / rs_skipped_pairs / rs_max_skipped`。
motor_ident ABI=1740B，前1724B不变，旧精确1724B runner和decoder应拒绝此新镜像，
以后人工请求板测需独立固定新BIN/ELF/ABI/当前B820基线，不复用旧stage收据。

Python现有参数报告解码新增gap统计，并拒绝超预算/不一致统计；
Ld/Lq的32帧、seq逐拍、45–55us、pending源序号、独立PWM latch证明要求全部保留。
输出仍是candidate，不自动改PI/NVM；少于三个独立Rs电流点仍拒绝Rs拟合。

## 验证

新增4项回归：

1. 实际C：同板测157402→157404、100us、hold+1，Rs继续；所有mode/seq/dt/hold组合，
   未解释缺口、预算第17对、连续缺3对拒绝，原400ms时限/电压/电流排除保持。
2. 实际binding：在决策前传hold差，决策后更新基准，终态只读统计正确。
3. Host：Rs gap预算检查，L缺口仍拒绝，异常metadata拒绝。
4. 控制函数冻结：FOC/编码器计算/STOP/PWM entry/stage和原冻结函数不变，旧A/B BIN哈希不变。

C测试在-Os/-O2、-Wall/-Wextra/-Werror下通过。
完整motor-ident相关测试：33项通过，日志 `tmp/motor-ident-rs-gap-all-tests.log`。

候选构建通过：Flash214452/229376B、RAM130736/131008B（链接余量272B，
原堆/任务栈预留未减）；比Timing候选多296B Flash/16B RAM。
已有unused/RWX warning集合不变，没有新增类别。

BIN SHA256 `9f0bf902af96699fde1d817b486588a228b71e830a291ffb49cf5f015f220676`。
ELF SHA256 `5f1fb840e744ed20a6935183902d902405e7266498384ef7a667b28e741e3e2a`。

修改：`firmware_common/motor_identification.h`、`motor_identification_binding.inc`、
`foc2_app_a/CMakeLists.txt`、`CMakePresets.json`、`tools/motor_identification_report.py`；
新增`tests/test_motor_ident_rs_gap.py`。

尚未板测新候选时序/任务栈/参数质量；本轮无设备操作。

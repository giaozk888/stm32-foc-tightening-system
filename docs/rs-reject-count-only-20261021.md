# Rs连续拒绝退出取消：独立诊断A候选

用户授权取消辨识中“连续3对dq样本超出准入范围就退出”的条件。
本轮只实现Rs诊断，未刷板、未复位、未注入、未修改正式B或当前B844启动选择。

## 语义

新增默认OFF开关`FOC_IDENT_RS_REJECT_COUNT_ONLY`，仅允许独立辨识、
启用current reject且已关闭Rs累计reject退出时使用。
新preset `MotorParameterIdentificationRsRejectCountDiagnostic`，
继承`MotorParameterIdentificationRsGapCountDiagnostic`。

`MotorIdent_Reference`：

- Rs中abs(Id)>0.20A或abs(Iq)>0.20A仍标记sample_rejected。
- reject总数、当前连续次数、历史最大连续次数仍记录，但不再因数量退出Rs。
- rejected sample仍不进入`MotorIdent_Record`的rows/后续Rs拟合。
- 一个有效sample仍将当前连续次数清零。
- 原ABI的连续计数为uint8_t，本候选采用255饱和而不回绕：
  255表示“至少255”，不是255对退出；32位reject总数继续累加。
- 不改变实际电流PI反馈或数学，不补造/替换控制样本。

停止后前台日志`MOTOR TEST IDENT REJECT`显式输出：

`REJECT_MAX=0 RUN_LIMIT=0 TOTAL_STOP=0 RUN_STOP=0 RUN_SAT=255`

在同候选的Ld/Lq中仍为REJECT_MAX16/RUN_LIMIT3/TOTAL_STOP1/RUN_STOP1，
实际第三对坏样本仍退出；旧preset默认行为不变。

## 保留的边界

- Rs固定400ms截止，结束电流参考归零；不为收齐样本延长注入。
- 原速度、有限值、电压和控制链故障退出仍独立有效。
- 原硬过流、driver fault、CUR_CONFIRM、CURRENT_INVALID、编码器保护、
  FOC50us、CCR pipeline、IRQ优先级均不改。
- Rs hold-gap仅限单次两拍且与hold计数/时间差吻合；不明间断仍退出。
- 电流样本±0.20A**估算准入**范围不改；没有扩大正式电流限幅。
- Ld/Lq连续性和退出不改，未开放自动下一档/自动重试。

即使运行到400ms，若rows不足32或质量不满足，主机仍判不合格，
不会因MID_DONE就给出Rs，也不会写回PI/NVM。

主机`motor_identification_report.guard`只在显式RUN_STOP0、RUN_LIMIT0、
TOTAL_STOP0、REJECT_MAX0、RUN_SAT255的Rs数据中接受max_run>=3，
不静默放宽旧会话。仍要求同会话保护/timing无故障证据、完整32行稳态窗口、
原噪声/跟踪/交叉轴/静止/电流/电压约束和至少3独立点的Rs拟合。
8000仅为400ms/50us下reject+good统计物理一致性上界，不是固件新增退出额度。

## 测试/构建

新增5项`tests/test_motor_ident_rs_reject_count.py`，真实C在-Os/-O2与
-Wall/-Wextra/-Werror下验证：

1. 用本次末态序号/时间上下文回放三对超准入的**合成**样本，不再退出。
   原记录没有最后三对幅值，测试不冒称重现了实测原码。
2. 300对连续reject不回绕，饱和255；有效恢复清零，Ld/Lq仍第三对退出。
3. 固定400ms结束；全坏sample无rows、主机拒绝；合格rows中没有被拒绝样本；
   速度/非有限/电压退出仍有效。
4. 真实command绑定的显式Rs/L策略；主机不接受缺行、坏样本、旧策略或缺保护证明。
5. 预处理展开比对相关FOC/PI/速度环/保护/PWM冻结函数及原A/B镜像哈希。

motor-ident相关69项通过，编码器时序策略4项通过，合计73项所选离线测试通过。
日志`tmp/rs-reject-count-tests.log`、`rs-reject-count-regression.log`、
`rs-reject-count-encoder-tests.log`。
不是全仓测试，也不是新候选板端50us时序已验收。

新A编译通过：Flash215132/229376B，RAM130912/131008B。
较前候选Flash增加56B，RAM不增加；链接余量96B，原堆/任务栈预留未缩。
已有unused/RWX warning集合无新增项。

- BIN SHA256 `19021c8c5e784fe4325c9fb8bb81177bc2e6189e150fd5832fc3a9337c8db4af`。
- ELF SHA256 `437dcaf5db263010313eb4b600bf60fb03d1350d804eb48655e1f140b26f6b46`。
- motor_ident ABI1740B，原统计/窗口字段未删。
- 原A候选和正式B BIN未覆盖，B哈希保持
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。

修改文件：`firmware_common/motor_identification.h`、
`firmware_common/motor_identification_binding.inc`、`foc2_app_a/CMakeLists.txt`、
`foc2_app_a/CMakePresets.json`、`tools/motor_identification_report.py`、新增测试/本文档。

后续人工板测必须为新镜像/B844建立精确runner及显式RUN_STOP0解码。
旧runner正确地拒绝新镜像或新策略，不应绕过pins/解码检查直接使用。

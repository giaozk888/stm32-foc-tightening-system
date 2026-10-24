# Rs可解释间断累计改为统计：独立A候选

用户授权只修Rs样本准入，未授权本轮自动刷板或重复注入。
本轮没有设备连接、复位、启动、Flash/NVM写入或B启动选择变更。

## 本次修改

新增默认OFF的`FOC_IDENT_RS_GAP_COUNT_ONLY`，仅允许独立辨识A且已启用
`FOC_IDENT_RS_GAP_ADMISSION_ENABLE`时开启。
新preset：`MotorParameterIdentificationRsGapCountDiagnostic`，继承已有编码器
时序分层候选，不改变其200us慢统计/400us事务硬期限及其他契约。
旧preset和B不自动开启，不覆盖此前精确固定镜像。

`MotorIdent_RsExplainedGap`保留所有局部判断：

- 只能是Rs；Ld/Lq不能采用该间断准入。
- seq差2或3，即单次最多跳过2对。
- hold增量必须严格等于seq差减1。
- 软件时间差必须在`45 * delta_seq .. 55 * delta_seq`us内。

只对这个明确通过解释的Rs gap取消累计16对退出条件。
`rs_gap_events`、`rs_skipped_pairs`、`rs_max_skipped`继续累加。
不是把坏样本替换成假值，也没有向PI注入补造电流。

`MotorIdent_Command`的停止后只读输出增加显式策略：

`OK MID RS_GAPS=... SKIPPED=... MAX_GAP=... BUDGET=0 RUN_LIMIT=2 TOTAL_STOP=0`

TOTAL_STOP/BUDGET=0仅表示此累计gap统计不单独终止Rs。
Ld/Lq在同构建查询时仍显示BUDGET16/TOTAL_STOP1，且实际L逻辑仍严格拒绝gap。
旧构建原输出和16对行为保持不变。

## 未放宽部分

- Rs固定400000us截止；仍只收200ms起的32行，每行间隔至少6250us。
- 不合适电流样本不进入rows；连续3对坏电流仍退出。
- 非有限值、速度、电压、独立硬过流/driver fault/编码器故障等退出路径不变。
- current discriminator、CUR_CONFIRM、CURRENT_INVALID、PI、FOC数学、
  一拍PWM pipeline、CCR时序、IRQ优先级不变。
- Rs软件dt100us、L55us和L104ms等原时序要求不变。
- 满400ms但样本不足不算合格辨识；主机仍拒绝不足的采集。

`motor_identification_report.guard`只对显式BUDGET0/TOTAL_STOP0接受该新Rs策略，
仍要求同会话无故障、deadline miss0、CCR late0的证据、完整32行、
200000<=row.us<400000、相邻记录至少6250us以及既有电流/速度/电压/静止条件。
原噪声、稳态、跟踪、交叉轴和至少三个独立电流点的Rs拟合要求不变。
主机8000计数上界仅是400ms/50us的物理一致性检查，不是新的设备退出配额。
旧16对策略不会被静默升级，L数据也不能借用Rs放宽。

## 回归

新增`tests/test_motor_ident_rs_gap_count.py`五项，真实C在-Os/-O2和
-Wall/-Wextra/-Werror下运行：

1. 回放本次真实161597->161599、100us、hold增1、skipped16的失败点：
   新候选进入17且继续ACTIVE，不再错误退出；仍拒绝错误hold、过长gap/dt、L gap。
2. 400ms模拟中超过16次hold和电流reject仍可收齐32行；
   被hold/拒绝的sample不进入rows，固定截止和连续3对/运动/非有限/电压退出仍有效。
3. 真实command绑定显式输出Rs count-only与L原策略。
4. 主机接受足量新策略数据；拒绝旧策略超额、L模式、缺行、错误时间窗、
   坏噪声、缺保护证据和错误计数。
5. 展开新旧candidate预处理结果比对FOC/速度环/保护/PWM相关冻结函数；
   历史A/B镜像哈希不变。

全部motor-ident相关61项通过；编码器时序策略4项通过，合计65项所选测试通过。
不声称全仓所有测试或实机已经通过。
日志：`tmp/rs-gap-count-tests.log`、`rs-gap-count-regression.log`、
`rs-gap-count-encoder-regression.log`。

## 构建

新A编译链接通过：Flash215076/229376B，RAM130912/131008B。
相对旧候选Flash增加16B，RAM不增加；链接余量仍96B，任务栈预留未缩。
保留已有unused和RWX warnings，与前候选build日志的warning文本集合比较无新增项。

- BIN SHA256：`68f066ad4fad8df0737271f0b0eec3937266f05ebea253de83f78eea8b212c06`。
- ELF SHA256：`c085819200ad4c7bd345e68b5d0483ed344fccb9cd7674d268dc18f1e9fb3c57`。
- B原BIN SHA256仍为
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`，未重建覆盖B。
- motor_ident ABI仍1740B，统计字段/窗口未缩。

修改文件：`firmware_common/motor_identification.h`、
`firmware_common/motor_identification_binding.inc`、`foc2_app_a/CMakeLists.txt`、
`foc2_app_a/CMakePresets.json`、`tools/motor_identification_report.py`及新增测试/本文档。

后续若人工要求板测，需为新BIN/ELF和当前恢复B840建立新的精确runner pins，
显式核验RS_GAPS BUDGET0/TOTAL_STOP0，不能复用旧16次策略的精确runner或stage。
只做一次Rs50/最多400ms；完整有效采集也不等于单点即可资格化Rs，更不能自动进入Ld/Lq。

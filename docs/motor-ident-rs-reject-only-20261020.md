# Rs样本拒绝：累计数仅统计，不再第17对退出

按用户针对累计拒绝的要求，新独立候选
`MotorParameterIdentificationRsRejectOnlyDiagnostic` 继承Rs100us候选，
开启 `FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT`；默认OFF，旧镜像保持原规则。

## 行为

- 仅Rs：超过0.20A的dq样本继续标记sample_rejected，累计计数递增，但不再因累计>16停止。
- 被拒绝样本不进入参数rows/估计，不替换为假电流，不改变原PI输入/运算。
- **连续3对异常仍退出**；正常样本仅清连续计数，累计数保持。
- 400ms总时限不延长，无自动重试/升档；未取得完整有效窗口，仍不输出有效Rs。
- Ld/Lq累计16/连续3的原诊断限制及连续瞬态要求不变。
- 原电流判别器、CUR_CONFIRM、CURRENT_INVALID、硬过流、驱动故障、ADC/编码器/时序保护、
  原PI/FOC/SVPWM、IRQ、PWM pipeline全部不改。
- 原Rs100us、下限45us和有hold证据缺口预算（累计16/连续最多缺2对）不改。
  **“累计电流样本拒绝”与“判别器hold缺口”是两个不同统计。**

## 诊断和离线估计

新候选终态查询 `MOTOR TEST IDENT REJECT`：Rs输出
`REJECT_MAX=0 RUN_LIMIT=3 TOTAL_STOP=0`，0表示无累计退出而不是允许0个拒绝。
Ld/Lq输出REJECT_MAX16/TOTAL_STOP1，旧preset输出格式不变。
累计REJECT、GOOD、MAX_RUN、首次拒绝原码/dq上下文仍保存，ABI1740B不变。

Python报告只对显式Rs策略TOTAL_STOP0、REJECT_MAX0允许累计>16，
仍要求完整32帧accepted window、GOOD>=32、MAX_RUN<3、同会话保护/时序证明、
稳态/噪声/交叉轴/运动质量及至少3个独立电流点等原拟合质量检查。
旧策略累计>16仍拒绝，L数据不能借用Rs策略。
这不承诺数据一定够用，不对严重失真数据输出参数，也不自动写PI/NVM。

## 修改

- `firmware_common/motor_identification.h`：累计退出条件只对新Rs候选取消。
- `firmware_common/motor_identification_binding.inc`：显式终态策略日志。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：诊断独立开关/preset。
- `tools/motor_identification_report.py`：显式新策略与有效窗口校验。
- `tests/test_motor_ident_rs_reject_only.py`：4项新增回归。

## 验证

4项新测试通过：真实C在-Os/-O2下累计17继续/连续3停止/L旧累计限制、
大量孤立异常下400ms到期且只记录accepted数据、速度/电压/NaN退出不变；
实际binding日志/计数、Host新旧策略和数据不足拒绝、控制函数冻结和旧A/B哈希。
全部motor-ident相关47项通过：`tmp/motor-ident-rs-reject-only-all-tests.log`。

候选构建通过：Flash214628/229376B、RAM130736/131008B（余量272B）。
相比Rs100候选增加32B Flash，RAM无增加，原堆/任务栈预留未减。
已有unused/RWX warning集合不变，无新增类别。

BIN SHA256 `c0be6a0d65a1aefa52e30b4b036005ab8787ea96be5f4f720b723f61f820d9d4`。
ELF SHA256 `c83291d4f565294e30da369a374ceba48bce9c36e04876deae82751331139857`。
虽然ABI未变，策略已变，旧精确runner必须拒绝此镜像；人工上板时要固定新pins/
当前B828基线并显式解析TOTAL_STOP0，不复用旧stage收据。

本轮未访问设备、刷板、复位或注入电流，正式B和已恢复B828启动选择不变。
本轮没有重新编译正式B，保留其既有文件并验证哈希未变；只新建诊断A构建。

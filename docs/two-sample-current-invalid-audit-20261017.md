# TWO_SAMPLE CURRENT_INVALID：离线证据审计

## 当前结论与边界

本轮没有修改任何 firmware、判别器条件、阈值或 unresolved limit。
没有连接设备、刷板、复位、启动电机或改变当前 B 启动选择。
**尚不能定位这次 CURRENT_INVALID 的物理/状态机根因，也不能宣称已完成修复。**

原因不是解码器没找到故障，而是保存的 16 帧不是故障窗口：

- trace 覆盖 seq **28522..28537**，trigger_seq=28531；
- freeze_reason=2：首次 CUR_CONFIRM 恢复后再四帧，按旧策略冻结；
- trace fault_seq=0；实际 CURRENT_INVALID 在 seq **499373**；
- ring 每帧 52 B，没有 reference/candidate、d_old/d_candidate、判别器累计计数；
- 现有 `pending_before` 是 **CUR_CONFIRM pending**，不是 PWM pending。不能混用。

已使用原 Python decoder 对同一停止状态完整 SRAM/Flash 解码，核对精确 BIN/ELF 哈希。
ARM 编译的独立 layout object 验证 sizeof(FocFeedbackSafety)=300、validation offset=248、
sizeof(FocCurrentValidation)=48、reference/candidate offset=36/40、state/last_path=44/45。
不是用 Windows 主机指针布局猜 ARM SRAM。

## 真实故障末态

| 字段 | 保存值 |
|---|---|
| fault reason / timeout reason | 11 CURRENT_INVALID / 0 |
| reference U/V | 1514 / 1545 |
| 最终 raw U/V | 1563 / 1561 |
| candidate U/V（Push **之后**） | 1563 / 1561 |
| d_old | max(49,16)=49 |
| d_candidate（Push **之前**） | **未捕获，不能计算** |
| state / last_path | SUSPECT / UNRESOLVED |
| unresolved total / consecutive / max | 61 / 3 / 3 |
| confirmed spike / transition / recovered | 3347 / 162 / 34 |

累计数满足 3544 = 3347 + 162 + 34 + 1（最后一个未恢复 suspect），
与正常关闭候选及最后锁存故障一致；这不是逐帧原码的替代证据。

unresolved 分支会执行 `candidate=next`，因此最终 candidate 和最终 raw 相同。
**不能用这个已覆盖的 candidate 算出 d_candidate=0，再倒推“判别器明明该接受”。**

下面不是完整实测逐帧表：仅序号、连续计数和未接受期间 reference 不变可由
末态及当前单 owner 代码推导；缺失的原码/前态必须保留 NA。

| seq | raw U/V | old_reference U/V | candidate_before | d_old | d_candidate | unresolved | fault |
|---:|---|---|---|---:|---|---:|---:|
| 499371（推导） | NA | 1514/1545（推导） | NA | NA | NA | 1（推导） | 0（推导） |
| 499372（推导） | NA | 1514/1545（推导） | NA | NA | NA | 2（推导） | 0（推导） |
| 499373 | 1563/1561 | 1514/1545 | NA | 49 | NA | 3 | 1 |

三帧的 DISC_EXEC=1、PI 未正常执行可由本故障路径推导，但没有对应逐帧记录；
CUR_CONFIRM 逐帧状态及 PWM pending 未保留，不能从较早 trace 移植过来。

## 真正保存下来的早期恢复窗口

以下均来自原 ring；它可以回放，但**不能替代最终 CURRENT_INVALID 回归**。
所有帧 DISC_EXEC=1、fault=0。PI 列仅对应现有 trace 的“已进入 PI”标记，
不是新的实测 PI 耗时。PWM pending 未记录，均为 NA。

| seq | IU raw | IV raw | discriminator result | CUR_CONFIRM cycles/good | PI marker |
|---:|---:|---:|---|---|---|
|28522|1566|1563|USE|off 0/0|entered|
|28523|1560|1557|USE|off 0/0|entered|
|28524|1564|1562|USE|off 0/0|entered|
|28525|1558|1557|USE|off 0/0|entered|
|28526|1564|1563|USE|off 0/0|entered|
|28527|1560|1561|USE|off 0/0|entered|
|28528|1565|1563|USE|off 0/0|entered|
|28529|1563|1563|USE|off 0/0|entered|
|28530|1561|1563|USE|off 0/0|entered|
|28531|1897|1829|HOLD|on 0/0|not entered|
|28532|1563|1561|USE|on 1/1|entered|
|28533|1562|1560|USE|off 0/0, recovery|entered|
|28534|1554|1554|USE|off 0/0|entered|
|28535|1568|1556|USE|off 0/0|entered|
|28536|1556|1556|USE|off 0/0|entered|
|28537|1562|1560|USE|off 0/0, freeze|entered|

上述帧 reference/candidate 前态和累计 spike/transition/unresolved 没有直接记录。
回放从已接受的第一帧建立参考，之后的返回值与实际记录一致；不把未记录的
绝对累计计数或初始 candidate 当实测补入表格。

## 状态机审查

- TRACKING：distance=max(abs(U-refU),abs(V-refV)) <=60 直接接受，更新整个 pair；
  否则保存 candidate、进入 SUSPECT。reference 不被可疑值覆盖。
- SUSPECT：返回 reference 距离 <=25 时接受；没有先前 unresolved 则计 spike，
  否则计 recovered。候选距离、方向条件成立则计 transition 并接受/rebase。
- 所有 SUSPECT 成功出口都会 state=TRACKING、unresolved_consecutive=0。
- unresolved 会推进合法的 candidate，reference 保持最后接纳 pair，计数达到 3 锁存 fault。
- 正常 TRACKING 的计数没有独立清零语句，但可达路径进入 TRACKING 时计数已经是 0：
  Begin 清零；另外唯一进入 TRACKING 的成功出口明确清零。未发现跨状态残留。
- 同一稳定合法样本即使首次 unresolved，下一帧 candidate distance=0（若恰为旧参考，
  返回旧参考分支先接受），因此不会无限 reference lockout。新增回归覆盖了该性质。
- 一通道异常会拖住整个 pair，这是现有原子 U/V 判别策略，不等于已经证实本次属于 D。
- 原保护提前 return 不会凭空增加 unresolved。当前 reason=11 来自判别器实际返回 -1；
  早期硬件/原码保护故障有其他 reason。未发现本例由提前 return 状态不同步的证据。

值得注意但**尚未证明是本次根因**：TRACKING 的允许距离是 60，而 SUSPECT
返回 reference 的容差是 25。因此最终 d_old=49 在 TRACKING 会被接纳，在 SUSPECT
仍需候选连贯性证据。把返回门槛从 25 改到 60 即改变判据，不能以“不改宏值”为名放宽。
本轮没有这样改，也没有清空 fault、自动 rebase、吞掉异常。

结论：目前 A/B/C/D/E/F **未定**；不能把“证据不足”归成 F 的“其他明确原因”。
静态审查和回归未复现永久锁死/计数残留，但不能据此排除未捕获的真实故障序列问题。

## 新增文件及验证

- `tools/two_sample_fault_audit.py`：只读已保存捕获，原 decoder 解码，
  独立 ARM layout 校验，明确区分 missing / inferred / measured。
- `tests/foc_two_sample_layout.c`：仅生成离线 ARM 布局，不链接进 firmware。
- `tests/foc_two_sample_state_audit_host.c`：原 core 的恢复、清零、candidate 推进、
  持续不连贯仍 fault、真实早期恢复窗口回放；输入性质测试明确标为 synthetic。
- `tests/test_two_sample_state_audit.py`：4 项测试通过；C 用 -Os/-O2、
  -Wall/-Wextra/-Werror 编译执行；回放固定数组逐项核对原收据 16 帧。

A/B 正式版与 A/B diagnostic 均重新链接通过，四个 BIN/ELF 身份不变；
原 54 项套件通过，无新增源代码/构建 warning/error。增量构建没重新打印历史
RWX/unused warning，不代表历史 warning 已被修复。
扩展执行现有控制/保护/ADC/PWM/编码器相关 **32 个离线模块，201 项测试**：
200 通过、1 失败、0 error。该运行加载的是新增测试添加第四项前的 3 项版本；
之后新增测试模块单独重新执行 **4/4 通过**，两者重叠，不简单相加冒充总数。
没有声称执行了工程中全部历史测试文件。

唯一失败：`test_foc_path_profile.PathProfileTests.test_protection_and_control_kernels_frozen`。
旧测试将 `foc_filtered_protection_candidate.h` 固定为
`fc66017b5d78ccc385e29cb57934b5513ac58f18d228eea3f9078625aeba1e3a`，
当前含前轮 trace wrapper 的文件为
`7db63b997d3b6ba36d77afc71926ee378d8ee636322103fa3a6c211868dbd7cb`。
本轮没有编辑该文件，未改 expected hash 绕过检查；该扩展套件仍应报告 FAIL。
这不等于新增算法回归，也不能由此宣称所有旧门禁全部通过。

## 必要下一步（本轮未执行）

需要一个仅诊断的、持续滚动到 CURRENT_INVALID 再冻结的窗口，保存每拍
reference_before、candidate_before/after、原码、d_old/d_candidate、状态及计数、
DISC_EXEC、PI 标记和真正 PWM pending。先证明逐帧原因，再决定是否最小修复。
保留首次 CUR_CONFIRM 恢复就永久冻结的当前策略，无法捕获几十秒后的最终 fault。

不能用本轮结果输出“根因已定位并完成离线修复”。
当前状态：证据审计及离线回归完成；真实故障窗口缺失，尚未完成根因修复。

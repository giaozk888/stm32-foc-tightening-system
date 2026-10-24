# Rs软件取时间隔上限：55us改100us

用户要求放宽本次辨识软件间隔上限，按前文Rs/Ld/Lq分工仅对Rs生效。
新增独立preset `MotorParameterIdentificationRs100usDiagnostic`，继承RsGap候选，
设置 `FOC_IDENT_RS_SOFT_DT_MAX_US=100`；旧preset默认55，不覆盖旧BIN/ELF。

## 精确语义

- Rs且seq连续+1：软件dt须在45–100us（包含100），101退出。
- Ld/Lq且seq连续+1：仍45–55us。
- Rs发生seq缺口：仍需判别器hold解释每个缺帧，最多连续缺2对/累计16对，
  dt仍须45*delta_seq至55*delta_seq；未将该范围扩大为100*delta_seq。
- 时间失败快照bit2用本模式实际上限生成，避免日志仍按旧55us错误分类。
- 新只读命令 `MOTOR TEST IDENT TIME POLICY` 显式输出
  `RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55`。
- Python `motor_ident_timing_report.decode(..., max_dt_us=100)` 显式按镜像策略校验。
  默认仍55，不根据失败dt猜测或自动放宽。Ld/Lq必须继续55。

本次只改变Rs辨识采样质量准入，不改变物理ADC频率、FOC50us deadline、
ADC freshness/watchdog、400ms/104ms时限、电流reject预算、电压/速度退出、
current discriminator、CUR_CONFIRM、CURRENT_INVALID、PI、pipeline、IRQ或硬过流。
这不能证明ADC硬件采样间隔57us，也不是让FOC执行超过50us。

## 文件

- `firmware_common/motor_identification.h`：可配置Rs-only dt上限和快照标志。
- `firmware_common/motor_identification_binding.inc`：只读policy查询。
- `foc2_app_a/CMakeLists.txt`、`CMakePresets.json`：独立诊断preset，限55/100且仅辨识构建可覆盖。
- `tools/motor_ident_timing_report.py`：显式解析上限，旧调用保持55。
- `tests/test_motor_ident_rs100us.py`：4项新增回归。

## 验证

实际C在-Os/-O2下-Wall/-Wextra/-Werror通过：44/45/55/57/99/100/101边界，
RS与LD/LQ分开，原真实seq157480→157481软件dt57us可继续，
未知seq缺口仍拒绝、已解释缺口原范围不变、400ms限时不变。
实际binding、policy UART、显式decoder、控制函数冻结、旧镜像哈希全部通过。
全部motor-ident相关40项测试通过：`tmp/motor-ident-rs100-all-tests.log`。

候选编译通过：Flash214596/229376B、RAM130736/131008B，RAM链接余量272B。
比上一版多144B Flash，RAM无增加；原堆/栈预留未减。
已有unused/RWX warning集合不变，无新增类别。

BIN SHA256 `3f38586c511f688da8b66862d9a27ea8dce11b9c4b869f7bdc526a53bc1bae3e`。
ELF SHA256 `3c62c253b0dc4c7dd796889db9d4d274ec77d6c7b1c93b85a058f913286cef47`。
诊断ABI仍1740B，但语义/pins改变，旧精确板测runner必须拒绝新镜像。
后续人工板测需要独立新BIN/ELF、B824基线和显式100us解码策略，不复用旧stage收据。

未刷板、未复位、未注入电流，原B824启动选择和B应用字节未动。
尚未板测新镜像时序/校准/参数质量。

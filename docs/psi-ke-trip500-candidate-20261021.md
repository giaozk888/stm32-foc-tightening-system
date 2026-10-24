# PSI candidate A：500 rpm 超速阈值（仅离线）

按人工要求，新增独立预设 `PsiKe500rpmTripDiagnostic`，继承原
`PsiKeIdentificationDiagnostic`，仅开启默认 OFF 的 `FOC_PSI_IDENT_TRIP500`。

## 改动范围

- `firmware_common/foc_rundown240_candidate.h`：独立保护阈值及文本改为500 rpm，
  仅在专用PSI诊断开关开启时生效，错误组合编译失败。
- `foc2_app_a/Core/Src/main.c`：速度环超速判断同步采用相同500 rpm常量，
  启动日志不再错误打印300 rpm。
- `firmware_common/protected_closed_loop.h`：说明两条保护共用阈值；保护判断本身不变。
- A的CMake和preset：新增受限、默认关闭的选项及独立构建。
- `tests/test_psi_ke_trip500.py`：编译边界、非法配置、预处理函数一致性、默认镜像保留。

原判断仍为 `abs(speed) > threshold`，因此正负方向均超过500 rpm才触发，
没有删除保护或改动判据。电流上限±0.50 A、过流、CUR_CONFIRM、CURRENT_INVALID、
FOC/PWM pipeline、编码器保护、IRQ、PI/前馈、时间及行程限制均不变。
正式B文件和板上B均未改动。

**本轮只改超速阈值。速度命令API仍为250 rpm，300/400 rpm仍会SKIP。**
旧 `tools/psi_ke_board.py` 继续锁定原300 rpm镜像，不接受本新镜像。
没有为了让脚本通过而重写其身份校验、保护profile或回退收据。
后续300/400 rpm测试仍需单独适配命令范围、批次和新镜像身份核验；
500 rpm软件阈值本身不代表已证明电机及传动机构的机械额定允许转速。

## 离线验证

- 新500 rpm预设及原300 rpm PSI预设均编译通过。
- 两者Flash215860 B、静态RAM129408 B；各13条既有警告完全同类，没有新增警告/错误。
- PSI原有14项加新增4项，共18项相关离线测试通过；没有声称重跑全仓库测试。
- 新BIN SHA256：`f164a52d064842bb251fbbc1df399cb077392c76461b81b6208601a2ed8dacc0`。
- 原PSI BIN重新构建仍为：
  `a260cc660b1c6bedaf8bc098c31e53505fd1c7fdd11595a9a1b95d985d186859`，逐字节不变。
- 既有B保留构建文件SHA仍为：
  `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`；
  该本地文件不是板端B936镜像，不作为新的板端身份声明。
- 日志：`tmp/psi-trip500-build.log`、`tmp/psi-trip500-baseline-build.log`、
  `tmp/psi-trip500-all-tests.log`。

本轮没有连接板端、刷写、复位、修改启动选择或发送电机启动命令。

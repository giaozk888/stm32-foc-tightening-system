# 240 rpm / ±0.50 A 完整状态机观察准备

后续已完成实机观察：约 3.47 秒达到原 3000° 行程边界，现有代码报告 RUNDOWN_TIMEOUT；没有 CONTACT 或 OK，未两秒提前停止。用户断 12 V 后已恢复原 B741 并停在入口。详见[实测记录](rundown240-fsm-board-20261020.md)。下文保留准备阶段记录。

本轮不改固件控制代码。当前配置已经接入 `TighteningIntentCandidate` 的原 UART START → PRECHECK → RUNDOWN_START → RUNDOWN；10 月 19 日真实日志已记录 RUNDOWN_ARMED=1，之后是主机两秒 STOP，不是没调用状态机。

本轮补充 240 rpm 真实 C FSM 的完整离线回归，并准备不施加两秒观察截断的单次状态机脚本。电机仍空载，不强制 CONTACT、拧紧或 OK；自然的 NO_ROTATION / TRAVEL / TIMEOUT 等结果仍如实保留，保护或异常不重试。原行程、rundown 8 秒超时、12 秒板端 lease、主机 11.95 秒最后停止窗口均不放宽。

## 配置与边界

- RUNDOWN：240 rpm、速度 PI 动态输出，Iq 上限 ±0.50 A，300 rpm 超速停机边界。
- CONTACT：仍要求建立真实运动及原持续低速/负载条件，不用主机注入。
- TIGHTEN/HOLD：保留原配方 0.08/0.10/0.12/0.15/0.15 A，直接 IQ 上限 ±0.20 A。不能把“速度环上限 0.50 A”理解成所有拧紧阶段都改为固定 0.50 A。
- 不改 PI 参数、电角零点、相序、采样、CUR_CONFIRM、CURRENT_INVALID、硬过流、IRQ 或 PWM pipeline。
- 不保存扩展配方，不改 B；原 A BIN SHA256 仍为 `478715341f0b6e52e58a9a2c5ff818257369f4e0c82fa76a40d7bede0076443d`。

## 离线验证

`tests/rundown240_candidate_host.cpp` 新增完整模拟输入回归，-Os/-O2 均运行真实 C 状态机：

`IDLE → PRECHECK → RUNDOWN_START → RUNDOWN → CONTACT_CONFIRM → TIGHTEN（4 阶段）→ HOLD → DONE`。

测试只在主机模拟速度下降和负载输入，不代表电机/扭矩仿真，不向设备发送虚拟接触。确认 .50 A SPEED intent、原四个 IQ 阶段、.20 A direct ceiling、armed/contact/completed/no-fault 条件与 DONE 关闭输出均成立。

新 `tools/rundown240_fsm_board.py` 使用 B737 精确全 Flash 基线，不覆盖旧两秒测试脚本。默认仅检查文件；`--inspect-off` 只读比较当前 Flash 和独立回读，无刷写/复位；`--execute-powered` 才经原 A/B 试运行与健康确认后发一次原 START；退出或故障均 STOP/ANALOG SAFE、停住并抓取同镜像 RAM/Flash，等待断 12 V 再恢复 B。空载 CONTACT 会停止审查，不能把空载结果标成实际拧紧成功。

相关 25 项定向离线测试通过（candidate 6、原 intent FSM 7、原两秒脚本 6、新状态机脚本 6）。A 编译 `ninja: no work to do`，镜像哈希没变。未重跑整个历史大套件。

## 本轮 OFF 核验

用户已确认 12 V 关闭、MCU 供电、空载固定、接线不变且人在现场。

第一次核验发现 CPU 不再处于上次 halted 状态，脚本立即拒绝，未复位、未激活、未发送 START。清理关闭输出并 halt，随后完整只读对比：全 Flash 仍逐字节等于保存的 B737 基线，A/B/配置/元数据均没改。没有把异常当作已通过。

已确认 CPU 停住且 Flash 一致后，重新只读核验成功：

- 收据 `tmp/rundown240-fsm-inspect-1792458607469550400.json`。
- `flash_programming=false`、`activation=false`、`motor_commands=0`。
- 全 Flash + 独立回读通过，仍 B737；SD/MOE/CCER=0、MCU halted。
- SHA256 `96cf86c7edc1574931e9a4636ca4aeaca7e21dc305bfb9716070bcb584cf8aaf`。

本轮截至此记录尚未上电试运行、未启动电机，等待人工上电且无报警后再进行状态机观察。

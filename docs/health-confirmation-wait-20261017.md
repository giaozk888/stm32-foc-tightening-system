# 自动健康确认复位：板测脚本等待修复

## 修复范围

仅改主机 Python 脚本及离线回归测试。未改固件、控制算法、保护阈值、A/B 流程、镜像哈希、历史收据和基线绑定；本轮没有连接设备、刷写、复位或发送 START。

原问题：`FW STATUS` 返回后，应用可能正好提交健康确认并自动复位。紧随的 `MOTOR TEST STATUS` 无 ACK，旧脚本直接进入 finally 收尾，导致正常确认重启被当成验收失败。

## 新等待策略

- `preempt_commit_board_test.wait_confirmation()` 从原 trial 中等价提取，历史默认策略不变。只有 `encoder_health_board_test.configure()` 接入新等待器，复用原单次激活与 finally 关断、停机、完整 Flash 比较和 RAM 所有权检查。
- 新 `health_confirmation_wait.wait_health_confirmation()` 只发送带新请求编号的 `FW STATUS`、`MOTOR TEST STATUS`。两者在启动阶段短时无 ACK 均可继续等待；不会重发激活、RESET、确认、清故障或 START。Console 原有请求编号匹配保留，迟到 ACK 不会匹配下一次新请求。
- 总启动等待仍为一次绝对 60 秒期限。每条查询最多 0.6 秒并受剩余预算约束；复位/超时不重新计时。持续失联最终失败，而非无限等待。
- 确认成功要求：A 应用、confirmed A、pending none、attempts 0、active 0，状态 READY、ZERO=3、SD/MOE/CCER/FLAGS/FAULT 均 0；随后重新读取 FW，要求仍是同一 confirmed generation。启动日志本身不算确认成功证据。
- STATE=4 保留原故障采集路径；回退 B、实际故障、输出未锁定、非超时串口/协议错误仍立即失败。故障采集若丢 ACK，不会被新等待器吞掉或触发重试。
- 确认完成后才进入原 30 秒观测。新超时容忍只覆盖启动确认阶段，运行期采样超时仍失败；所有失败均走原 finally 收尾。

收据新增 `health_wait`：总耗时、FW/状态查询超时次数、generation 重检次数、是否确认及确认代号。`read_timeout_count` 仅证明曾缺 ACK，不单独证明一定发生了复位。

## 离线验证

新增模拟测试覆盖确认复位丢 ACK、初始静默、校准等待、跨 generation 响应、绝对超时、回退/故障/非超时错误、日志不能冒充确认、运行期超时不被忽略，以及启动/运行失败时单次激活与 finally 收尾。全部模拟设备和 Flash 读取，不访问物理设备或私有捕获。

最终结果：新增 17 项、相关已有 34 项，共 51 项通过；5 个改动 Python 文件的 `py_compile` 通过。测试均以独立模块进程运行，避免历史 runner 的进程内配置重绑定互相污染。

当前 health / encoder / deadline / pipeline / preempt / fast-profile / CUR_CONFIRM 脚本回归一并运行；另行扩大检查时，历史 `current_impulse` 一项及 `timeout_diagnostics` 两项因共用旧构建目录的镜像与历史 size/hash 固定值不匹配而失败：当前 `FastCurrentRejectComputeOnly/foc2.bin` 为 227492 字节，前两者分别固定 225068、227476 字节。未放宽镜像校验，也未为了让历史测试通过而替换镜像或收据。

此修复只通过离线模拟，尚未上板重验；不代表 FOC 50 µs、实际 CCR margin 或闭环电机验收已通过。当前 runner 仍保留历史 B607 基线钉住；下一次上板前须按现有流程核对最新恢复收据，不能跳过全 Flash 基线检查。

## 后续上板结果（同日）

以上为修复完成时的离线状态。后续经用户明确授权，基线绑定到已核验的 B611 并完成一次功率硬关闭重验：启动等待容忍 24 次只读无 ACK，正常确认 A614 后观察 31.85 秒；FOC max=31.25 µs、deadline miss=0、实际 CCR late=0、最小 margin=15.05 µs。关闭 12 V 后已恢复 B615 并停在入口，不启动电机。完整结果及限制见 [上板重验报告](foc-encoder-health-wait-retest-20261017.md)。

# 0.45 A 请求未执行：UART 波特率配置不匹配

2026-10-19，用户开启 12 V 并确认无报警后，按原 A/B 流程试运行 A；没有发送任何电机启动/Iq 命令。

## 已保存证据

- 收据：`tmp/torque450-run-1792406596722123400.json`。
- START attempts=0，UART 启动捕获为空，FW STATUS 93 次只读等待均无 ACK，60 秒绝对期限到期。
- 不能称为“0.45 A 带不动”或板端健康故障：停止后的 metadata 已是正常确认 A716，pending=0，attempts=0。
- first_fault.valid=0；FOC max=28.618 us、deadline miss=0、actual CCR late=0、actual min margin=16.653 us。
- CUR_CONFIRM=344 enter / 344 clear / 0 fault。
- STOP UART 同样无 ACK，因此由调试器执行关断与停机；SD=0、MOE/AOE=0、CCER=0、CPU halted，应用/私有区字节未改变。

## 确认原因与责任

新增候选的 `UART_LOG_BAUD` 被错误地设为 2000000，而复用的 `open_port()` 明确使用 115200。原 350mA 和 Hand 构建实际 cache 也是 115200，不是 2M。此前“与原波特率一致”的假设错误。
该配置错误由本轮新增 preset 引入。不是电机、反馈极性或接线已被本次证据判定有故障；本次根本没有进入带电电流测试。

## 恢复

用户确认 12 V 关闭后，仅恢复 B 启动选择并在 B 应用入口前停住。
收据：`tmp/torque450-restore-1792406710960391000.json`。
恢复后 confirmed=B717，pending=0，attempts=0，SD/MOE/CCER=0；B 应用未执行。
bootloader、A/B 应用和私有区字节保持不变，只按原流程更新启动选择元数据。

## 离线修正，未重新刷板

- A/B 450mA 专用 preset 的波特率改回原来的 115200，其他 Iq/5s 配置保持不变。
- 450mA 验收脚本提供局部 `HOST_BAUD=115200`，显式打开 COM5，不再依赖跨层导入的串口默认值。
- 在任何设备访问前读取该构建的 compile command，固件 UART 波特率必须唯一且等于 HOST_BAUD；缺少或重复定义同样拒绝。
- 离线测试新增 baud mismatch 拒绝与实际 Serial 参数断言。
- 修正版 450mA 定向测试 8/8 通过；默认脚本离线自检通过，`git diff --check` 通过。未重新跑全仓 discover，不宣称全部既有测试全绿。
- 脚本基线更新为已保存的 B717 精确全 Flash；不接受早期 B713 的暂存收据激活新镜像。
- 不改 PI、相序、电角零点、保护或 PWM timing；不自动重新刷写、复位、发送电流命令或重试。

修正版 A：Flash=222516 B，RAM=130000 B；B：Flash=221492 B，RAM=129984 B。
最终构建均成功，保留既有 12 条 unused + RWX 链接警告，非零警告构建。

修正版 SHA-256：

- A BIN：`d96586bd785023ab066b4ac5814978eb35659f383ef9e5bc433d4edc59cc483f`
- A ELF：`1079285d4f50029c6d2f64da1a10c683cd4da5de2317fc3994a6a1aeabeb763a`
- B BIN：`25c8af2bbe8d1f75a2bde562f36b0d180d48285cb7120212283c0fad45ea06bb`

本地构建目录已重编译，不能用修正版 ELF 再解码旧 2M 捕获；旧收据包含当时匹配旧 ELF 解码的快照、旧 BIN/ELF hash 和完整 Flash/RAM 文件，不能把它标记为修正版证据。

状态：固件通信配置修正版仅离线就绪。板上 A 仍是旧 2M 候选，当前选择 B717 且停住；0.45 A 实际机械响应仍未取得。

## 用户请求“重试”后的修正版暂存

用户后续明确请求重试，沿用其最后确认的 12 V 关闭状态，只写入非活动 A 的 115200 修正版。
暂存收据：`tmp/torque450-stage-1792408109407683400.json`。
完整回读与独立第二次回读通过；B717、bootloader、私有配置及启动元数据不变。
SD/MOE/AOE/CCER=0、MCU 停住，尚未复位激活或发送 Iq 命令；等待用户正常供电后预检。
上段“仅离线就绪/板上 A 仍为旧 2M”是此前结束时刻的历史状态，此次暂存后已被修正版替换。

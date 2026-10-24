# 固定 +0.35 A / 5 秒诊断准备与主机日志中止

## 范围

按用户请求准备独立 `Torque350mAFiveSecondDiagnostic` A/B 候选：
IdRef=0、固定正向 IqRef=0.35 A、绕过速度/位置环、单次最多 5 秒。
只有精确本地命令 `MOTOR TEST TORQUE350 CONFIRM` 可以一次性启动；没有连续升流、反向或任意电流入口。

仅此候选把直接 Iq 限幅显式设为 0.35 A，编译断言和真实 setter/outer 测试确认没有被原 0.20 A 截断。
正式默认仍为 0.20 A；速度 PI、电流 PI、相序、电角零点、采样判据、保护阈值及一拍 PWM pipeline 均未修改。
复用独立 5 秒 lease 与 STOP/故障关断。32 帧每 200 ms 的记录之外，还保留 1 kHz 任务级的完整运动统计，防止只凭净位移判断持续转动。

## 构建与离线测试

| 构建 | Flash | RAM | BIN SHA-256 |
|---|---:|---:|---|
| A | 222516 B | 130000 B | `64c80001e563e86842022579925c2a3ed0831f83e1b82ca11c5c9da9640d8520` |
| B | 221492 B | 129984 B | `3ce43fc34eed53a179ef290581552625b3fe1b2239f62e46d9bc26baa9c3c1a0` |

A ELF SHA-256：`eb7ac9c2d00ff8fab7dd83c124843efe80fbc1a05642c72c9a0cff79b0af40ff`。
相关回归 99 项通过（新 350mA 8、speed500 7、torque-chain 44、breakaway 40）。
存在原基线已有 unused / RWX 警告；未声称全仓全绿。

## 本次没有执行 +0.35 A 脉冲

- OFF 暂存收据：`tmp/torque350-stage-1792391754106997900.json`。
- 运行中止收据：`tmp/torque350-run-1792400032648956600.json`。
- A 通过正常 A/B 健康确认并复位，确认 generation=704。
- 随后主机 `os.replace(receipt.json.partial, receipt.json)` 出现 Windows `WinError 5`。
- 错误发生在运动命令之前：`start_attempts=0`，没有 START 或 TORQUE350 CONFIRM。
- 主机进入清理，通过 SWD 关闭输出、停住 MCU，保存同次 Flash/RAM。
- 同次板端故障 valid=0；FOC wall max=28.34706 us，deadline=0，CCR late=0，min margin=16.72353 us；CUR_CONFIRM 4 enter / 4 clear / 0 fault。
- 这些只是启动/功率关闭计算证据，不能当作 0.35 A 的电机响应或持续转动结果。

用户确认关闭 12 V 后，仅恢复原 B 启动选择：
`tmp/torque350-restore-1792400094213341300.json`。
恢复后 generation=705、confirmed=B、pending=0、attempts=0；B 应用入口前停住，SD/MOE/AOE/CCER 关闭；应用、bootloader 和私有配置未改。
最终 Flash SHA-256：`87e6522e07dc2dc178ae57222018c747015e2f7f51840bd4998d1fdcfc4ca370`。

## 主机保存修复

`tools/sb1_speed_acceptance.py::checkpoint` 保留写入、flush、fsync、原子替换的顺序。
对 Windows PermissionError 的 winerror=5/32/33，只重试**同一个已 fsync 的文件替换操作**，最多 6 次，总等待不超过 150 ms。
Windows 读取者未允许 FILE_SHARE_DELETE 可能短时阻止替换，但当前证据不能确定究竟哪个进程持有文件；不把主机故障归因于电机、ADC 或保护。
永久权限错误仍抛出并阻止下一步，旧收据与 partial 证据保留；不会重发 UART、刷写、复位或运动命令。

脚本日志/停止测试 14 项及 350mA 诊断测试 8 项通过。
本轮未自动重试电机；+0.35 A / 5 秒实际机械响应仍待下一次人工启动验证。

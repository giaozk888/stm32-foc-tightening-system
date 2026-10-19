# 新 A 启动与功率关闭计算验证：通过

本轮用户请求“验证”。按事先说明，只验证启动、零点、FOC 计算、保护和停止状态，不运行自动升流。用户已按“开启 12 V／限流 0.5 A、无报警后回复”的提示回复“开了”。没有再次刷写，也没有发送 START、Iq 或任何档位命令。

## 镜像和启动

- 使用此前恢复、完整回读及独立复核通过的 A 镜像：228972 B，BIN SHA256 `6f45621b2c76b1b7e66a36cb0041cd2fa58ab985d2cb7614ccf8e25756f8fd95`。
- 正常 bootloader mailbox 提交 B→A 试运行，未直接改 Flash metadata 或强制确认。
- 日志观察到 5 秒连续健康窗口通过、正常确认请求及自动复位；随后 CURRENT=A、CONFIRMED=A、pending 无、attempts=0、generation=696。
- 正常等待共 19.83 秒，期间 23 次仅启动阶段 FW STATUS 缺 ACK，由既有有界确认等待逻辑处理；没有重发试运行或运动命令。
- 这次正常确认使**启动选择变为 A696**。原 B 固件字节及 CRC 保留，没有恢复为 B 启动选择。

## 实测

| 项目 | 同次结果 |
|---|---:|
| 零点有效样本 | 4000 对 |
| reject / total | 37 / 4040 |
| 最长连续 reject | 1 |
| zero U/V | 1560 / 1563 |
| 零点 result / fault flags | PASS / 0 |
| 最终 SRAM FOC wall max | 27.18235 µs |
| >50 µs deadline miss | 0 |
| actual CCR commits | 147450 |
| actual CCR late | 0 |
| actual margin min | 16.64118 µs |
| CUR_CONFIRM enter / clear / fault | 71 / 71 / 0 |
| CUR_CONFIRM max cycles / elapsed | 2 / 101 µs |
| 首故障 snapshot valid | 0（无首故障锁存，不把未锁存的零字段当故障读数） |

MonitorTask 在最终抓取前的报告为 wall max=27.141 µs；上表使用同次最终 SRAM max=27.18235 µs，没有混淆两个采集时刻。

`BREAKAWAY STATUS` 实际显示 LIMIT_MA=200、ID_MA=0、LEASE_US=5000000、PERIOD_US=200000、TAG=42574135。Iq 选档为 0，USED=0、ACTIVE=0，session STATE=READY、USED=0、QUEUED=0、SD=0、MOE=0、CCER=0。保护报告 RAW_CONFIRM_4、TRIP_MA=4000、STATE/REASON/FLAGS=0。

## 停止和边界

只读预检完成后发送 STOP、ANALOG SAFE，随后使用既有输出关闭/停住流程保存完整 Flash 和 SRAM。最终 VTOR=`0x08008000`、DHCSR=`0x30003`、SD=0、CCER=0；BDTR 保留配置位但 MOE/AOE 位均为 0，不能误写成整个 BDTR=0。

bootloader、完整 B 槽、私有配置逐字节与 B693 基线一致，B CRC 再算通过。仅启动 metadata 按正常 A/B 健康确认流程更新为 A696。

完整 Flash SHA256：`df7c649c600ea750dfa8bc5e2b2384dcd7f5eef2b36503e5113741f815547f35`。文件可能含私有配置，仅本地保存。

本轮**仅功率输出关闭计算验证通过**。没有 ±Iq、5 秒持续运动、全程 motion aggregate 或 minimum breakaway 电流实测；新增全程运动统计仅在 RUNNING 下执行，其带电负载工况尚未验证。不能用本结果宣称电机已能稳定单向旋转。

收据：`tmp/breakaway5-verify-1792388031737461800.json`，同名 `-flash.bin` / `-ram.bin` 保存最终数据。

工具新增 `--verify-compute <successful-stage-receipt>`，使用只允许 BREAKAWAY STATUS 的 VerifyConsole；不暴露 Iq/START。后续自动批测可读取本次成功停住的验证收据：要求完整 Flash、A BIN、B/boot/private、已确认 A metadata 全部匹配，再复位 A 开始第一档；不重放旧 B→A 试运行请求。

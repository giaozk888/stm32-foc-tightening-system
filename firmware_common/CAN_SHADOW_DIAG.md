# CAN 诊断请求/回执（不执行电机动作）

这是一条独立于候选电机控制协议 `0x200/0x280` 的诊断链路。正常固件默认
`CAN_SHADOW_DIAG=OFF`，原有 HMI 仍只读；只有显式构建为 `ON` 的 A/B
固件才在 FDCAN1 上接收**唯一**标准 ID `0x220`，并从 `0x2A0` 返回结果。
其他数据帧和全部远程帧仍拒收。代码没有调用电机模式、PWM、驱动使能、
模拟安全锁存或急停执行函数；任何肯定回执都只表示诊断状态机的结果。

500 kbit/s 经典 CAN、标准 11 位 ID、DLC=8，小端序：

| ID | 字节布局 |
| --- | --- |
| `0x220` 请求 | `[version=1, opcode, seq:u16, test_value:u16, 0xA5, 0x5A]` |
| `0x2A0` 回执 | `[version=1, opcode, seq:u16, decision, reserved=0, 0x5A, 0xA5]` |

`opcode` 1 是 PROBE（`test_value=0`），2 是 CHECK_VALUE（仅验证
`1..1000` 的**测试数值**，不是配方/速度/电流/扭矩），3 是 STOP_TEST
（`test_value=0`）。PROBE 打开 500 ms 的纯内存测试窗口；CHECK_VALUE
须在窗口内且序号紧随 PROBE（16 位允许回绕）。超时、越界、重复序号
均被拒绝。STOP_TEST 可重复调用，只清除该内存窗口、回执
`STOP_OBSERVED_NO_ACTION`，**不是真实急停，不能依赖它停机**。

`decision` 值：1 PROBE_READY；2 VALUE_OK_NO_ACTION；3
STOP_OBSERVED_NO_ACTION；4 REJECT_RANGE；5 REJECT_SEQUENCE；6
REJECT_TIMEOUT；7 REJECT_NO_PROBE；8 REJECT_OPCODE；9 REJECT_VALUE。
坏版本、DLC、扩展/远程/FD 帧及错误魔数静默丢弃并记入 `BAD`。
串口 `CAN SHADOW` 行提供接收、坏帧、回执、超时、停止测试与范围拒绝计数。
一次只处理一条请求，回执在下一监控周期尝试发送；高频诊断可造成
原只读遥测暂时跳帧，不得用于实时控制。

离线测试：

```sh
cmake -S tests/can_shadow_diag_host -B tests/can_shadow_diag_host/build -G Ninja
cmake --build tests/can_shadow_diag_host/build
ctest --test-dir tests/can_shadow_diag_host/build --output-on-failure
```

在鲁班猫上对**已明确启用诊断的固件**做小流量回环验收时，可运行
`python3 tools/can_shadow_probe.py --interface can0`。它只发送 `0x220`，
核验 PROBE、范围边界、超时和 STOP_TEST 的 `0x2A0` 回执；不会发送
`0x200` 或任何电机启动指令。未上板或无回执时脚本以失败退出。

真正开放控制之前，仍需独立硬件急停、可靠的失联停机、配方和功率级
可信回读、命令鉴权/会话、受控负载验收；本诊断不是其中任何一项的替代品。

## 2026-09-29 上板结果

从已确认 A 槽启动，将 `CAN_SHADOW_DIAG=ON` 的 B 镜像（152376 B，
CRC32 `E0AE932A`）暂存到非活动 B 槽；ST-LINK HOTPLUG 回读 SHA-256
`DFACA8A11413595EF8FCF2F0EE645411CDECC13CDF8DDF57E74D377FE507715D`
与构建文件一致。升级前原 B 槽及启动元数据备份在
`safety_backups/2026-09-29-can-shadow/`。提交后 B 自动确认，
`CURRENT=B CONFIRMED=B PENDING=-`；重新施加并复查
`ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0`，运行模式 `IDLE`、故障 0。

鲁班猫运行 `tools/can_shadow_probe.py` 八条请求均收到预期 `0x2A0`
回执：边界 1000 被接受，1001 被拒绝，超过 500 ms 被判超时，
两次 STOP_TEST 仅回“已观察到，无动作”。STM32 串口记录
`RX=8 REPLY=8 DROP=0 TIMEOUT=1 STOP_TEST=2 RANGE=1`，
`CAN HEALTH INIT=1 FAIL=0 RECOVER=0 BO=0` 且发送完成计数增长。
鲁班猫 HMI/CAN 服务仍 active，`can0` 当前 ERROR-ACTIVE，10 秒内
bus-off 累计值维持 3182 不变；但历史累计数值很高，**不是可靠控制
链路验收**。测试回执每条会暂时占用一个发送 FIFO 元素，原 10 Hz
遥测曾记录 8 次 `FULL`，因此诊断流量必须保持很低。

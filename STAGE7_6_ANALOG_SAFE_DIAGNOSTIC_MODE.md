---
title: Stage 7.6 - 模拟电压诊断安全状态（仅编译，未上板）
tags:
  - STM32G474
  - PD6010B
  - FOC
  - 安全诊断
status: B-confirmed-hardware-smoke-passed
date: 2026-09-25
---

# Stage 7.6：模拟电压诊断安全状态

> [!note] 2026-09-25 板上验证更新
> 新 B 镜像已在 12 V 下经 IAP、trial 和自动确认。`ANALOG SAFE` 命令实测 MCU 读回 `SD=0 MOE=0 FOC=0`，停 PWM 后 ADC2 规则组采样继续更新。尚未用万用表直接测 PD6010B 的 CTRL_SD 引脚，也未做升压测试；仍不可将 MCU 读回当成功率级物理隔离的完整证明。详见 [[STAGE7_8_ANALOG_SAFE_HARDWARE_SMOKE]]。

## 动机

现有 `MODE=IDLE` 不等于功率级断电：正常日志仍有 `EN=1`、20 kHz FOC，启动时 `CTRL_SD=HIGH`。因此仅靠 IDLE 不足以在改变母线电压时隔离桥臂。此前 14 V 测试期间出现 `R=1` 软件 2 A 电流跳闸，但现有证据不能区分真实电流和采样瞬态。Stage 7.5 已为后续版本准备首次过流快照；本阶段增加独立的、单向锁存的电压诊断停机状态。

## 新命令与行为

两槽均加入 Protocol V2 命令 `ANALOG SAFE` 和只读 `ANALOG SAFE STATUS`。进入前须：当前已确认而非 trial、紧固流程不忙且无待处理 START、模式 IDLE、编码器有效且速度有限并小于 2 rpm。若不满足则返回错误，**不进行调压**。

成功进入后按安全顺序执行：

1. `CTRL_SD` 拉低，禁止功率驱动；
2. `foc_enable=0`，锁存 `analog_safe_latched=1`；
3. 电机命令置 IDLE，停止全部 TIM1 PWM 通道，并强制清除高级定时器 `MOE`；
4. 读回 `CTRL_SD` 和 `MOE`，只有两者均为 0 才返回成功。

锁存后，普通 `START` 被拒绝；`PowerStage_Enable()` 和 `PWM_StartAll()` 增加二次拦截；1 kHz 控制任务持续保持 `CTRL_SD=LOW`、`MOE=0`，并跳过因为主动停止 TIM1 而必然出现的 ADC/FOC 计数停滞故障判定。其他已经锁存的故障不会被清除，原 2 A 跳闸阈值不变。只有 MCU 复位才退出该状态，因此**升压状态下绝不能复位/重新上电**：重启仍会走原有使能桥臂的启动流程。

已在 B 槽验证的命令形式：

```text
2000 ANALOG SAFE STATUS
2001 ANALOG SAFE
2002 ANALOG SAFE STATUS
2003 ANALOG VOLT
```

进入后 `SELFTEST` 的 `FOC` 停止以及周期日志的 `FOC/s=0 EN=0` 属于预期；不要把它当作正常电机可用状态。PC4/PC5 的 ADC2 规则组采样在停 TIM1 后能否继续正常工作，**仍需要未来单独上板验证**；若 `ANALOG VOLT VALID=0`，不要调压。命令中的 `SD/MOE` 是 MCU 侧读回值，不能替代驱动板实物输出验证。

## 离线验证

`foc2_app_a`、`foc2_app_b` 分别 `cmake --build build/Debug --clean-first`，均成功链接并生成 ELF/HEX/BIN。最终内存用量：

| 槽 | Flash | Flash 使用率 | RAM |
|---|---:|---:|---:|
| A | 222,300 B / 224 KiB | 96.92% | 64,928 B / 131,008 B |
| B | 221,980 B / 224 KiB | 96.78% | 64,912 B / 131,008 B |

代码变更限于两个 APP 的 `Core/Src/main.c`；Bootloader、Flash 布局、A/B 地址、元数据、mailbox 均未修改。编译成功**不是**安全功能的实测证明，也不能推定此前跳闸的根因已经消除。

## 下一次硬件验证的前提

只有用户重新决定开始测试时，先在 12 V 下核对接线、刷写/确认固件及其回退能力，再单独检查 `ANALOG SAFE` 的 MCU 引脚和驱动板实际输出，最后验证停 PWM 后 `ANALOG VOLT` 仍有效。未通过这些检查，不应重新进行 14 V 测试。

相关记录：[[STAGE7_5_OVERCURRENT_FAULT_SNAPSHOT]]、[[STAGE7_4_ANALOG_FIXED_SUPPLY_STABILITY]]。

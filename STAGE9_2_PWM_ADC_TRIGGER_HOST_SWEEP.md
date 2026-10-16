---
title: Stage 9.2 - PWM 与 ADC 固定触发点离线角度扫描
tags:
  - STM32G474
  - TIM1
  - ADC
  - FOC
  - 主机测试
date: 2026-09-25
status: offline-sweep-pass-hardware-not-tested
---

# Stage 9.2：PWM 与 ADC 固定触发点离线角度扫描

## 目的

承接 [[STAGE9_1_PWM_ADC_STATIC_TIMING_AUDIT]]，把“当前低压 FOC 调制时，三相 PWM 边沿是否接近固定 ADC CH4 触发点”的手算结论变成可重复的离线检查。测试从 A/B `main.c` 读取实际 ARR、CCR4、母线常数、电压限制和死区设置；不修改固件、不复位 MCU、不改变 `ANALOG SAFE`，也不让电机运行。

## 方法与命令

脚本 [tim1_pwm_adc_timing.py](tests/tim1_pwm_adc_timing.py) 核查 A/B 关键配置一致，并复现源码中的逆 Park 后三相合成、min/max 共模居中、占空比 2%–98% 夹限及 `CCR=int(duty×(ARR+1))`。在 0.8 V 最大向量幅值下按 0.1° 步进扫描 3600 个电角度，找离固定 CH4=3500 最近的三相 CCR。另以 1 µs 为**离线筛查阈值**，仅防止未来改参数后明显靠近；该阈值不是芯片或驱动板规定的模拟建立时间。

```powershell
python .\tests\tim1_pwm_adc_timing.py
```

本次运行结果：

```text
A/B matched: ARR=4249 CCR4=3500 VBUS=12V limit=0.8V
PWM=20004.707Hz; DTG=85 -> nominal 500.0ns
3600-angle sweep: max phase CCR=2370; closest CH4 gap=1130 ticks = 6.647us
Offline 1us screening margin: >170 ticks: PASS (not analog settling proof)
WARNING: generic duty 82.35% maps near CCR4; 95% duty is NOT validated
```

## 解释

当前**正常 FOC 电压限制路径**的计算值与 9.1 手算约 6.64 µs 相符。它只说明由这组源码常数推导出的上数方向数字比较点没有碰到 CH4=3500；不包含功率管开关、驱动传播延迟、ADC 采样孔径、真实相电流建立时间或异常路径。脚本未仿真 MCU 定时器寄存器的所有边界行为，不能代替波形测量。

通用 `PWM_SetDuty()` 可接受最高 98%，而 `CCR4/(ARR+1)=82.35%`。因此未来若提高 `FOC_VOLTAGE_LIMIT_V` 或通过其他路径给出高占空比，**固定采样点可以与某相比较点重合**；原图中“最大占空比 95% 的采样可靠性”目前完全没有验证。当前 `FOC_DC_BUS_V=12.0f` 是控制计算常数，不是实时使用第七章的 VBUS ADC 读数；第七章模拟尖峰未解决，不应把其读数直接接入控制或保护。

## 后续门槛

下一步若做真正的六路 PWM 与 CH4/ADC 触发数字波形，需要先在电源关闭状态下断开并分别绝缘电机 U/V/W；由于 SAFE 会停 TIM1，退出 SAFE 的复位须另行核对 PD6010B 实际供电、零点校准需求以及探头连接方式。仅凭 8 路 24 MHz 逻辑分析仪还不能严谨测定约 500 ns 死区或模拟电流噪声；必须明确哪些量它能测、哪些要示波器。当前不执行这项带硬件的验证。

相关：[[STAGE9_1_PWM_ADC_STATIC_TIMING_AUDIT]]、[[第七章_设备自检与保护_Obsidian总结]]、[[第八章_AS5047P_SPI磁编码器_Obsidian总结]]。

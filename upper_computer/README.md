# STM32G474 本机上位机（第一版）

这是运行在 Windows 电脑上的本机网页界面，不需要给 ESP32 配 Wi-Fi。Python 进程通过 NUCLEO 的 ST-Link 虚拟串口与 STM32 通信，浏览器只访问 `127.0.0.1`。

## 启动

在项目根目录 `D:\new project` 运行：

```powershell
python -m pip install "pyserial>=3.5,<4"
python -m upper_computer.server
```

浏览器会打开 `http://127.0.0.1:8765/`。选择 ST-Link 对应的 COM 口（当前机器为 COM5），点击「连接」。确保其他串口终端已关闭，避免占用同一个端口。退出时在运行窗口按 `Ctrl+C`。若不想自动打开浏览器，加 `--no-browser`。

## 已实现

- 每 5 秒读取 `STATUS`、`FW STATUS`、`ROUTER STATUS`、`ROUTER NODES`、`ANALOG VOLT`。
- 展示模式、故障、FOC 频率、位置、Iq、估算母线电压、A/B 固件槽和 ESP32 节点。
- 记录串口日志，并用最近 120 个遥测样本绘制位置和 Iq 趋势；CSV 导出最多保留最近 2000 行。
- 「ESP PING」仅验证 STM32 ↔ ESP32 链路。

当前为**只读诊断版**：没有任意指令输入、拧紧启动、参数写入或固件升级入口。界面显示的 `VBUS` 为 ADC 估算值，不能代替万用表；`VTEMP` 是采样引脚电压，未换算成温度。趋势图来自低频串口遥测，不是示波器。网页仅绑定本机回环地址，但这不是用户认证，不要通过代理暴露到局域网。

## 验证

```powershell
python -m unittest discover -s upper_computer/tests -v
node --check upper_computer/app.js
```

本机联机验收时，COM5 显示 `MODE=IDLE`、`FLT=0`、`CURRENT=B`、`CONFIRMED=B`、ESP 节点 2 在线，`ESP PING` 收到 PONG，CSV 导出返回成功。以上仅证明通信和显示链路，不代表电机功能验收。

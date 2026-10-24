# 辨识候选：取消0.10度相对位移退出

按用户明确要求，只在新的辨识候选中移除运行时
`abs(position-initial_angle)>0.10deg -> MID_MOTION` 这一项。

新 preset `MotorParameterIdentificationNoTravelDiagnostic` 继承已测试的
bounded-current-reject 版，设置 `FOC_IDENT_TRAVEL_EXIT_ENABLE=OFF`，
编译 `MID_TRAVEL_EXIT_ENABLE=0`。旧 preset 默认保留原逻辑，旧镜像/ELF不覆盖。
`MOTOR TEST IDENT GEOMETRY` 增加 `TRAVEL_EXIT=OFF`，可在上板时明确核验。

没有修改：2rpm诊断速度退出、非有限量拒绝、0.20V包络、400ms/104ms限时、
连续3对/累计17对电流异常退出、原硬过流/CUR_CONFIRM/CURRENT_INVALID、
原PI/FOC/SVPWM/PWM pipeline/IRQ/正常tightening和正式B。
位置和电角度仍记录；去掉运行时位移STOP不等于允许把运动数据当作静止RL响应。
Python离线静止质量判定未删除，数据移动过多仍不输出有效电感。

**上一轮 MID_TIMING 的seq/45–55us间隔判定本轮未改。** 因此这个改动不解决
上一轮已经记录的时序退出，也不声称当前辨识可以完成。

修改：`firmware_common/motor_identification.h`、
`firmware_common/motor_identification_binding.inc`、
`foc2_app_a/CMakeLists.txt`、`foc2_app_a/CMakePresets.json`；
新增 `tests/test_motor_ident_no_travel.py`。

构建通过：Flash213580/229376B、RAM130656/131008B（余量352B）。
已有unused/RWX warning仍存在。未实测新镜像时序/任务栈。
新BIN SHA256 `dedb650aa982ab0b565141e02ec311f6891e6d53a4644c476237268a87e9c8c0`。
新ELF SHA256 `3878b129ca61a51e60d3b67c3f15ffb3fc9602be41de29812cc881d28fc5c250`。

6项相关测试通过：2项新测试（实际C开关ON/OFF分别在-Os/-O2验证，仅位移STOP
可关闭；速度/电压/持续电流/时序/时长/NaN保持；控制函数冻结和离线静止判定）、
4项原current-reject回归。日志 `tmp/motor-ident-no-travel-tests.log`、
`tmp/motor-ident-no-travel-reject-regression.log`。

本轮没有串口/调试器访问、烧录或复位，未改变板端原已恢复B812启动选择。
旧精确pinned runner不会接受此新镜像，若之后人工请求上板必须更新独立镜像/
ABI/基线校验，不能复用旧stage收据或只改SHA绕过验证。

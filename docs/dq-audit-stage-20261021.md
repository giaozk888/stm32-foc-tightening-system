# DQA1 A 暂存（未激活）

现场确认：驱动板12 V关闭、MCU供电、空载固定/解锁/接线不变、限流0.5 A、
在场可立即断电；允许仅刷A并必要复位。此阶段没有请求上电或启动电机。

`tools/dq_audit_board.py` 为新镜像提供独立身份核验，沿用原关断/暂存/
正常试运行/恢复B流程；没有盲改旧脚本哈希或修改任何控制参数。
默认仅核验文件，三个硬件入口均要求独立现场条件标志。测试19项通过。

执行：

```
python tools/dq_audit_board.py --stage-off --drive-off-unlocked-no-load-fixed
```

结果：PASS。现场完整Flash先与真实B916基线逐字节比较通过，之后仅写非活动A。
新A为 `DqAuditCurrent`，221100 B：

- BIN SHA256 `82ade68937f2dc0420a48fdaf10d811042447b78101d6bd553227578587e0627`
- ELF SHA256 `8fec71f92f29d6fb499d3f3b8186ec36429a01f460340f800e30061f1fbad0e3`
- 回执 `tmp/dq-audit-stage-1792582916129410300.json`
- 两次完整Flash回读一致，新镜像校验通过；boot、B、配置和启动元数据不变。
- 未提交A试运行/激活；motor_commands=0；CPU停住，SD/MOE/CCER关闭。

本轮计划先做同镜像DQ OFF基线。上电且现场确认无报警后，才允许正常A试运行，
校准和原时序预检通过再执行一次240 rpm原START空载诊断，最多原12 s板端租约；
保留原8 s rundown超时。真正保护或关断核验异常中止，不自动重试/切符号。

后续运行入口（**尚未执行**）：

```
python tools/dq_audit_board.py --execute-powered tmp/dq-audit-stage-1792582916129410300.json --operator-present-drive-on-no-alarm-05a
```

记录最终完整Flash/SRAM和相同ELF，解析DQA1同帧日志及全有效帧统计。
低频日志无法保证覆盖每个瞬态；启动前500 ms峰值以最终SRAM累计为准。
运行结束输出关闭并停住后，提示关闭12 V，再按该运行回执恢复B启动选择。

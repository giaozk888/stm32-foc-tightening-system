# DQA1 OFF 基线提前停止

运行回执：`tmp/dq-audit-run-1792583039056246500.json`。
仅一次 START，DQ OFF 已读回确认，未自动重试或进入 ON。

启动前零点 PASS：4000 valid / 41 reject，零点 U/V=1560/1563。
时序预检 PASS，A 通过原5秒健康窗口由bootloader正常确认，未强制确认。

启动后状态机进入保护停止。最初软件总入口显示保护 reason=3/flags=32，
不能据此命名为过流或 CURRENT_INVALID。完整快照确认：

- flags=32 对应 `CL_BAD_ENCODER`。
- 编码器事务 started_us=8594141，deadline_us=8594341。
- 故障 now_us=8594342，事务 elapsed=201 us，超过原200 us预算1 us。
- RX word timestamp=8594294，完成故障发布晚于事务截止；仅凭这些值不能
  断言SPI物理传输失败或DMA完全未收到数据。要区分服务/发布延迟仍需审查实际路径。
- 引擎7098 attempts / 7097 successes / 1 failure；timeouts=1，DMA errors=0，
  schedule misses=0，control stale=0。
- 最后成功事务elapsed=151 us，裕量49 us。没有同一事务成功/超时双记录证据。
- CURRENT_INVALID不是本次已证实的触发原因；CUR_CONFIRM=55 enter/55 clear/0 fault。

时序：FOC wall max=35.705882 us，deadline miss=0，actual CCR late=0，
actual margin min=13.670588 us。不是50 us FOC超时。

DQ证据：914个RUNNING有效PI帧，约45.7 ms样本量，不足500 ms启动窗口。
本次有效运行期间Vd_dec/Vq_dec=0、dq电压饱和计数=0、configured math错误=0。
没有匀速段，不可用它完成ON/OFF性能结论。

全局near-stationary maxima约10.14/7.05 uV包含START之前默认DQ ON的输出关闭
计算，不能把它写成OFF运行补偿非零。日志有73个完整同帧组，大多为预检；
1个不完整组未当作完整帧，token_decode_errors无记录。
we转换一致性全局max残差约1.3115 rad/s含任务多字段发布不同代际的可能，
本记录不能证明源单位错误，也不更改来源。

已确认最终SD=0、MOE/AOE关闭、CCER=0，MCU halted；完整Flash和SRAM已保存，
boot/B/配置等应用私有区在运行中未变。人工确认12 V关闭后，已仅通过原bootloader
流程恢复B启动选择并停在B入口，未运行B应用，未再启动电机。

恢复回执：`tmp/dq-audit-restore-1792583167104102100.json`，PASS。
恢复前后除正常启动元数据区域外，boot、A/B payload、私有配置逐字节未变；
下一次实验/阈值更改不由本次失败自动授权。

# 正常A固定0.25倍Ka，并准备BEMF对照

用户选择旧0.25倍Ka作为正常运行配置，而非采用未通过辨识质量的2.79e-5。
本轮没有硬件访问、刷写、复位、运行电机或修改板上启动选择；不将软件接入说成正式板已更新。
保留物理B和现有已验证镜像，先以新的正常A候选交付。

## 正常配置

- `TighteningKa025Candidate`继承空间优化的正常A，固定Ka=`0.000046875 A/(rpm/s)`。
- 原S-curve最大200 rpm/s下，iq_acc_ff峰值9.375 mA，占Iq限幅0.50 A的1.875%。
- acceleration FF保持ON，`iq_raw=iq_pi+iq_acc_ff+iq_friction`后统一限幅±0.50 A；原AW不改。
- 不带`FOC_ACCEL_FF_AUDIT`、KAI/完整Ka/64点诊断，不提供GAIN扫描命令。
- 原current/speed PI、S-curve、摩擦0.105 A/2 rpm deadband、PWM pipeline、采样/角度/IRQ/保护均不改。
- 仍240 rpm、300 rpm独立超速、20000°行程、8秒rundown、12秒lease，不自动START。
- 已有空间优化沿用：48槽日志、192 B单条长度不变、token化开启，通用单元测试不编入，必要启动安全自检保留。
- “正常”表示运行真实tightening FSM而非辨识/固定电流诊断；并不表示已通过工业认证或新组合板测。

## 既有BEMF前馈复用

代码已经存在，未重复实现，也未把BEMF与加速度前馈混为一谈：

```text
omega_e = signed_measured_mechanical_rpm * pole_pairs * 2*pi/60  [rad/s]
Vq_bemf = omega_e * psi_f
psi_f = 0.00069732 Wb
Vd_cmd = Vd_PI
Vq_cmd = Vq_PI + Vq_bemf
随后原统一矢量电压限幅/SVPWM；饱和回算保留PI-only项处理
```

ψf沿用用户先前选择的命令电压模型候选，不自动修改Rs/Ld/Lq，不把其当作仪器验证的物理磁链。
240 rpm/10极对时omega_e约251.327 rad/s、Vq_bemf约0.17526 V。
采用实测速而非speed_ref；正反转符号随实测速，零速项为0，不加额外截距补偿。
dq交叉耦合继续OFF，不加入DOB、滤波或新PI。

正常基线`TighteningKa025Candidate`保持BEMF开机OFF。
另编译`TighteningKa025BemfOnCandidate`仅改变开机BEMF初值，不自动开桥或启动。
推荐实测使用**同一OFF默认镜像**，在空闲/输出关闭时用原`MOTOR TEST BEMF ON/OFF`切换。
原接口拒绝运行中/输出开启/未配置ψf时切换，不改保护安全门。
这避免用两个不同ELF进行OFF/ON比较；ON默认构建只提供显式可选候选，不自动部署。

历史BEMF在另一配置/批次曾使加速MAE恶化，不能仅因理论公式正确就宣称收益。
本次要在固定0.25倍Ka条件下重新比较，未在本轮执行。

## 构建结果

|正常A|Flash B|RAM链接 B|Flash余量 B|RAM链接余量 B|
|---|---:|---:|---:|---:|
|TighteningKa025Candidate（BEMF默认OFF）|211584|124024|17792|6984|
|TighteningKa025BemfOnCandidate（默认ON）|211584|124016|17792|6992|

RAM余量不是运行期堆/栈高水位。两版.data均14304 B，.bss分别108184/108176 B；
8 B链接占用差异不作为性能收益或安全证据，未删功能或缩栈。
两个构建均通过，13条既有unused/RWX警告，无新增warning/error。
B `TighteningCommonModeCandidate`构建无待更新项，BIN SHA不变。

OFF BIN SHA256 `4236aa0f7234b43bb12b6254fab0c75b34e59fc7ad8261be808f5a4b9054400a`。
OFF ELF SHA256 `14d6ba34f4a66755d73fb174994f23beb0b3f51e23acb617cbf73b937efcd377`。
ON BIN SHA256 `64a4f8e784868dde5afba69073193b8b5ed16aa99743cff2d2d1bc762dd3b0c8`。
ON ELF SHA256 `0d41c4e98a38538520efb677964ec8ed6569d25ba5abbde55557404280050823`。
稳定B BIN SHA256 `7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366`。
旧Ka279镜像保留，现有B995恢复证据也不重标：`tmp/ka279-repeat-restore-1792660747794505000.json`。

```powershell
# 在 foc2_app_a 中
cmake --preset TighteningKa025Candidate
cmake --build --preset TighteningKa025Candidate -j 6
cmake --preset TighteningKa025BemfOnCandidate
cmake --build --preset TighteningKa025BemfOnCandidate -j 6
```

## 离线验证（96项）

- 新正常配置4项：精确Ka/ψf/开关、无诊断、默认OFF/ON除初值外函数一致、原控制/保护/协议仅Ka常量替换、实时驱动对象逐字节相同、原镜像/B保留、警告集合相同。
- 新板测包装器3项：只复用原受保护START、禁止计划/运行开关不一致、保护不重试、增益读回准确、默认不访问设备/缺确认拒绝。
- 既有BEMF8项：实际电流环插入、正反/零速rad/s、OFF逐位等价、未配置/非有限值拒绝、统一电压限幅、PI-only回算、原开关安全门。
- speed系列81项：原加速FF/摩擦/AW/S-curve与相关板测回归。
- 日志：`tmp/ka025-all-tests.log`、`tmp/ka025-existing-bemf-tests.log`、`tmp/ka025-speed-regression.log`。

## 人工上板步骤（尚未执行）

1. 新鲜确认12V关闭、MCU供电、转轴解锁/空载固定/防护/接线/.5A/人员在场。
2. `tools/ka025_bemf_board.py --prepare-off --drive-off-unlocked-no-load-fixed`，仅非活动A，
   原B995和旧Ka279身份先核验，再安装新身份；完整回读、B/boot/private保持。
3. 人工上电无报警后，使用实际stage回执`--execute-powered ... --operator-present-drive-on-no-alarm-05a`，
   先运行一次BEMF OFF基线，先校准/时序/栈预检，再一次原START。
4. 输出关闭并halt后人工断12V，用该次实际run回执`--restore-b-drive-off ... --drive-off-unlocked-no-load-fixed`恢复原B。
5. 仍同镜像，在新的恢复基线上另准备一次`--bemf-on`计划；再次人工上电确认后执行ON，
   stage和run必须都显式选择`--bemf-on`，不允许主机默默改变计划。
6. 同样收尾恢复B，比较完整加速段MAE、匀速误差、超调、Iq/积分器、饱和及同帧Vq_PI/Vq_ff/Vq_cmd。
   继续核验FOC<50us、deadline=0、CCR late=0/实际margin；独立保护触发停，不重试。
7. 两轮各一次只作初步对照；若需要最终选用BEMF，还需人工授权同镜像重复对比。

板测包装器默认只核验文件，不访问硬件，不烧录ON默认镜像、不自动追加第二轮、不持久化Ka到配方。
原始B启动选择和当前已确认B应用本轮不变；本轮没有任何实际运行。

## 修改文件

`foc2_app_a/CMakePresets.json`、`README.md`、`tools/ka025_bemf_board.py`、
`tests/test_ka025_bemf_candidate.py`、`tests/test_ka025_bemf_board.py`及本文。
无控制算法源码或B配置修改。

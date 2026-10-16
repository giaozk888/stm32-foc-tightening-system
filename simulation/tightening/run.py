"""Generate local JSON/Markdown evidence only; no hardware operation exists."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
import statistics

from model import Assumptions, ROOT, SimRecipe, load_firmware_profile, simulate


CASE_LABELS = {
    "hard_joint": "硬连接", "soft_joint": "软连接", "no_joint": "未接触工件",
    "early_jam": "提前卡死", "stripped_joint": "滑牙模型",
    "sensor_gain_plus_10pct": "扭矩测量增益偏大 10%",
    "kt_minus_20pct": "实际 Kt 偏低 20%",
    "feedback_delay_40ms": "反馈延迟 40 ms",
    "feedback_dropout": "反馈中断", "fault_injection": "外部故障注入",
    "user_stop": "用户停止", "target_0p2Nm_not_authorized": "示例不可达目标 0.2 N·m",
}
MODE_LABELS = {"baseline": "现有流程镜像", "feedback": "虚拟扭矩反馈候选"}


def cases():
    hard = Assumptions()
    soft = replace(hard, stiffness_nm_per_rad=0.010)
    return {
        "hard_joint": (hard, SimRecipe()),
        "soft_joint": (soft, SimRecipe()),
        "no_joint": (replace(hard, has_joint=False), SimRecipe()),
        "early_jam": (replace(hard, seat_deg=10), SimRecipe()),
        "stripped_joint": (replace(soft, strip_at_nm=0.0010), SimRecipe()),
        "sensor_gain_plus_10pct": (replace(soft, torque_gain=1.10), SimRecipe()),
        "kt_minus_20pct": (replace(soft, kt_nm_per_a=0.016), SimRecipe()),
        "feedback_delay_40ms": (replace(hard, feedback_delay_ms=40), SimRecipe()),
        "feedback_dropout": (replace(hard, feedback_dropout_s=0.40), SimRecipe()),
        "fault_injection": (replace(hard, injected_fault_s=0.40), SimRecipe()),
        "user_stop": (replace(hard, stop_s=0.40), SimRecipe()),
        "target_0p2Nm_not_authorized": (soft, replace(SimRecipe(), target_nm=0.20)),
    }


def aggregate(results):
    ok = [r for r in results if r.outcome in ("PROCESS_OK", "MODEL_OK")]
    return {
        "runs": len(results), "reported_complete": len(ok),
        "virtual_truth_pass_count": sum(r.truth_within_demo_band for r in ok),
        "false_complete_count": sum(not r.truth_within_demo_band for r in ok),
        "outcomes": {s: sum(r.outcome == s for r in results) for s in sorted({r.outcome for r in results})},
        "mean_final_nm": statistics.mean(r.final_true_torque_nm for r in results),
        "sample_std_final_nm": statistics.stdev(r.final_true_torque_nm for r in results) if len(results) > 1 else 0.0,
        "worst_absolute_final_error_percent": max(abs(r.final_error_percent) for r in results),
        "worst_peak_overshoot_percent": max(r.peak_overshoot_percent for r in results),
    }


def numerical_checks(profile):
    """Check time-discretization sensitivity, not model-to-hardware accuracy."""
    rows = []
    for joint, stiffness in (("hard", 0.20), ("soft", 0.010)):
        for mode in ("baseline", "feedback"):
            a = Assumptions(stiffness_nm_per_rad=stiffness, torque_noise_nm=0)
            runs = [simulate(profile, a, controller=mode, dt_s=dt, keep_trace=False)
                    for dt in (0.0005, 0.00025, 0.00005)]
            reference = runs[-1].final_true_torque_nm
            relative = max(abs(r.final_true_torque_nm / reference - 1) for r in runs)
            rows.append({
                "joint": joint, "controller": mode,
                "dt_s": [0.0005, 0.00025, 0.00005],
                "final_nm": [r.final_true_torque_nm for r in runs],
                "outcomes": [r.outcome for r in runs],
                "max_relative_difference_percent": relative * 100,
                "check_pass": relative <= 0.01 and len({r.outcome for r in runs}) == 1,
            })
    return rows


def write_report(output, profile, individual, repeats, count, numerical, *,
                 source_recipe_defaults, recipe_overrides):
    numerical_passed = len(numerical) == 4 and all(row["check_pass"] for row in numerical)
    data = {
        "evidence_kind": "OFFLINE_SYNTHETIC_MODEL_ONLY",
        "hardware_access": False, "industrial_accuracy_certified": False,
        "speed_profile": profile.speed_profile,
        "numerical_checks_passed": numerical_passed,
        "source_hashes": profile.hashes,
        "source_recipe_defaults": source_recipe_defaults,
        "effective_recipe": profile.recipe,
        "recipe_overrides": recipe_overrides,
        "source_constants": profile.constants,
        "model": "first-order Iq response + forward-only/self-locking spring joint; no dq/SVPWM, RTOS, clamp-force or thermal emulation",
        "plant_dt_s": 0.0005, "outer_control_period_s": 0.001,
        "application_period_s": 0.010,
        "firmware_foc_period_s_not_emulated": profile.constants["FOC_TS_S"],
        "cases": individual, "repeats": repeats, "numerical_step_checks": numerical,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# 拧紧离线仿真结果", "",
        "> 纯软件、合成模型。没有连接板卡，没有刷写，没有调整现场限幅。不能证明工业精度。", "",
        f"数值步长检查总结果：{'PASS（仅数值检查）' if numerical_passed else 'FAIL 或检查不完整，本次模型结果不得作为通过验收'}。", "",
        "## 本次输入", "",
        f"- 本次显式配置：{profile.speed_profile}；源码默认旋入转速 {source_recipe_defaults['rundown_rpm']} rpm，本次模型目标 {profile.recipe['rundown_rpm']} rpm，上限 {profile.ranges['rundown_rpm'][1]} rpm；不代表板端 Flash 中的当前值。",
        f"- 速度模式电流指令限幅：{profile.constants['MOTOR_SPEED_IQ_LIMIT_A']:.2f} A；直接电流／候选最终阶段：{profile.constants['MOTOR_DIRECT_IQ_LIMIT_A']:.2f} A。",
        "- 假设 Kt=0.020 N·m/A、惯量=2e-5 kg·m²；这些不是你的电机标定结果。",
        "- 示例目标 0.002 N·m、示例误差带 ±5%；不是工业统一要求，也不是现场运行参数。",
        "- 基线是现有应用状态机的行为镜像；不是编译执行实际 MCU 固件。",
        "- 候选方案假设存在虚拟扭矩传感器和已知夹具接触位置：提前减速、扭矩反馈、角度窗口、稳定确认。未移植到固件。",
        "- 简化模型不模拟完整 20 kHz FOC、电气开关、FreeRTOS 并发、温升或夹紧力；积分步长 0.5 ms，外环 1 ms，应用决策 10 ms。", "",
        "## 单次场景", "",
        "PROCESS_OK 仅表示原流程走完；MODEL_OK 仅表示候选看见的虚拟测量合格。",
        "“真值合格”另用隐藏的模型真值检查最终值与全过程峰值，不能当作实机测量。", "",
        "| 场景 | 控制器 | 流程结果 | 最终模型扭矩 / N·m | 峰值过冲 | 真值在示例误差带内 |",
        "|---|---|---|---:|---:|---|",
    ]
    for name, pair in individual.items():
        for mode, result in pair.items():
            lines.append(f"| {CASE_LABELS[name]} | {MODE_LABELS[mode]} | {result['outcome']} | {result['final_true_torque_nm']:.6f} | {result['peak_overshoot_percent']:.1f}% | {'是' if result['truth_within_demo_band'] else '否'} |")
    lines += ["", "## 固定种子重复试验", "", f"每个连接／控制器运行 {count} 次；参数扰动范围在 run.py 中固定，结果可复现。统计包含失败运行，未删除失败样本。", "", "| 连接 | 控制器 | 流程完成 | 真值合格 | 假合格／仅流程完成 | 均值 / N·m | 样本标准差 / N·m | 最差最终误差 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for joint, pair in repeats.items():
        for mode, row in pair.items():
            lines.append(f"| {'硬连接' if joint == 'hard' else '软连接'} | {MODE_LABELS[mode]} | {row['reported_complete']}/{count} | {row['virtual_truth_pass_count']}/{count} | {row['false_complete_count']} | {row['mean_final_nm']:.6f} | {row['sample_std_final_nm']:.6f} | {row['worst_absolute_final_error_percent']:.1f}% |")
    lines += ["", "## 数值步长检查", "", "在关闭测量噪声后，对比 0.5、0.25、0.05 ms 模型积分步长。要求流程结果一致、最终值差异不超过 1%（本工具数值检查阈值，不是工业精度标准）。", "", "0.05 ms 步长也仍然执行简化电流模型，不等于完整 20 kHz FOC。", ""]
    for row in numerical:
        lines.append(f"- {row['joint']}/{row['controller']}：最大相对差异 {row['max_relative_difference_percent']:.3f}%，检查 {'PASS' if row['check_pass'] else 'FAIL'}。")
    lines += ["", "## 怎么理解", "", "- 不能将基线 PROCESS_OK 当作扭矩合格。当前固件的最终阶段主要是电流指令＋持续时间，不是 Nm 验收。", "- 候选比较同时改变了接触前转速和反馈方式，不能把改善全部归功于某一个算法。", "- 传感器增益偏差场景用于说明：内部反馈自认为合格，也可能与模型真值不一致。真实设备必须标定。", "- 0.2 N·m 场景用于检验不可达目标的拒绝，不能为了让它通过而增加现有电流限幅。", "- 故障注入只验证仿真控制器的退出，不能证明实际硬件检测或关断速度。", "- 没有工件要求、独立扭矩标定和负载实测，不计算工业认证或宣称达标。", "", "## 源码指纹", ""]
    lines.extend(f"- `{name}`：`{digest}`" for name, digest in profile.hashes.items())
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "simulation/tightening/results")
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--speed-profile", choices=("baseline", "x2-offline"), default="baseline")
    parser.add_argument("--rundown-rpm", type=int,
                        help="Model-only recipe override within the selected source range")
    args = parser.parse_args()
    if not 2 <= args.repeats <= 1000:
        parser.error("--repeats must be 2..1000")
    # Restrict generated writes to this offline simulation folder.
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "simulation/tightening").resolve()):
        parser.error("Output must stay inside simulation/tightening")
    profile = load_firmware_profile(speed_profile=args.speed_profile)
    source_recipe_defaults = profile.recipe.copy()
    recipe_overrides = {}
    if args.rundown_rpm is not None:
        recipe_overrides["rundown_rpm"] = args.rundown_rpm
        try:
            profile = profile.with_recipe(**recipe_overrides)
        except ValueError as error:
            parser.error(str(error))
    individual = {}
    for name, (a, r) in cases().items():
        individual[name] = {}
        for mode in ("baseline", "feedback"):
            result = simulate(profile, a, r, mode)
            individual[name][mode] = {**result.summary(), "trace": result.trace}
            print(f"{name:32s} {mode:8s} {result.outcome:20s} truth={'PASS' if result.truth_within_demo_band else 'FAIL'}")
    repeats = {}
    for joint, stiffness in (("hard", 0.20), ("soft", 0.010)):
        pairs = {mode: [] for mode in ("baseline", "feedback")}
        for index in range(args.repeats):
            rng = random.Random(20261008 + index)
            a = Assumptions(
                kt_nm_per_a=0.020 * rng.uniform(0.95, 1.05),
                inertia_kg_m2=0.000020 * rng.uniform(0.9, 1.1),
                friction_nm=0.00010 * rng.uniform(0.8, 1.2),
                seat_deg=rng.uniform(177, 183),
                stiffness_nm_per_rad=stiffness * rng.uniform(0.9, 1.1),
                current_gain=rng.uniform(0.98, 1.02),
                current_offset_a=rng.uniform(-0.0005, 0.0005),
                torque_gain=rng.uniform(0.995, 1.005),
                feedback_delay_ms=rng.uniform(1, 4),
                command_delay_ms=rng.uniform(0, 2),
            )
            for mode in pairs:
                pairs[mode].append(simulate(profile, a, controller=mode, seed=20261008 + index, keep_trace=False))
        repeats[joint] = {mode: {**aggregate(rows), "runs_detail": [r.summary() for r in rows]} for mode, rows in pairs.items()}
        for mode, row in repeats[joint].items():
            print(f"repeat {joint}/{mode}: complete={row['reported_complete']}/{args.repeats}; truth={row['virtual_truth_pass_count']}/{args.repeats}; false_complete={row['false_complete_count']}")
    numerical = numerical_checks(profile)
    write_report(output, profile, individual, repeats, args.repeats, numerical,
                 source_recipe_defaults=source_recipe_defaults,
                 recipe_overrides=recipe_overrides)
    print(f"MODEL ONLY: {output / 'REPORT.md'}")
    if not all(row["check_pass"] for row in numerical):
        raise SystemExit("Numerical step check failed; do not treat the run as accepted")


if __name__ == "__main__":
    main()

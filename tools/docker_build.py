"""Linux container compile-only entry; all artifacts go to /out, never source build dirs."""
import argparse
from pathlib import Path
import subprocess


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=("a", "b", "both"), default="both")
    parser.add_argument("--preset", choices=("RouterTransferReadOnly", "RouterTransferSamplingReadOnly", "FocSamplingReadOnly",
                                           "EncoderDmaReadOnly", "RouterRpcReadOnly"),
                        default="RouterTransferReadOnly")
    parser.add_argument("--host-tests", action="store_true")
    parser.add_argument("--format-check", action="store_true")
    args = parser.parse_args()
    root = Path("/src")
    run("arm-none-eabi-gcc", "--version")
    run("cmake", "--version")
    if args.format_check:
        run("python3", str(root / "tools/format_code.py"), "--clang-format", "clang-format-18")
    if args.host_tests:
        for suite in ("allocator_hybrid_host", "uart_zero_copy_host",
                      "router_rpc_host", "router_transfer_host"):
            build = Path("/out") / suite
            run("cmake", "-S", str(root / "tests" / suite), "-B", str(build), "-G", "Ninja")
            run("cmake", "--build", str(build), "--parallel", "4")
            run("ctest", "--test-dir", str(build), "--output-on-failure")
    for slot in (("a", "b") if args.slot == "both" else (args.slot,)):
        source = root / f"foc2_app_{slot}"
        build = Path("/out") / f"{slot}-{args.preset}"
        run("cmake", "--preset", args.preset, "-S", str(source), "-B", str(build))
        run("cmake", "--build", str(build), "--parallel", "4")
    print("BUILD ONLY: no board access, reset, Flash or motion.")


if __name__ == "__main__":
    main()

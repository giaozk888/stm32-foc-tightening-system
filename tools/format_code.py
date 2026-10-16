"""Explicit formatting allowlist; does not rewrite Cube/vendor/generated/private trees."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Apply; default is check only")
    parser.add_argument("--clang-format", default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    executable = args.clang_format or shutil.which("clang-format")
    bundled = Path("C:/Espressif/tools/esp-clang/esp-21.1.3_20260408/esp-clang/bin/clang-format.exe")
    if not executable and bundled.is_file():
        executable = str(bundled)
    if not executable:
        parser.error("clang-format unavailable; provide --clang-format PATH")
    subprocess.run([executable, "--version"], check=True)
    files = []
    for line in (root / "tools/format_scope.txt").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        path = (root / line).resolve()
        if not path.is_relative_to(root) or path.suffix not in (".c", ".h", ".cc", ".cpp", ".inc"):
            parser.error(f"Unsafe formatting scope: {line}")
        files.append(str(path))
    subprocess.run([executable, "--style=file", *( ["-i"] if args.write else
                   ["--dry-run", "--Werror"]), *files], check=True)
    print(f"FORMAT {'APPLY' if args.write else 'CHECK'} PASS: {len(files)} explicit files")


if __name__ == "__main__":
    main()

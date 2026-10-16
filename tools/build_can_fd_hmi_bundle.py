"""Source-only Linux HMI/official Transfer build; never package credentials."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "safety_backups/20261007-canfd-deploy/hmi-source.zip"
modules = """pw_assert pw_bytes pw_containers pw_function pw_log pw_log_string
pw_numeric pw_memory pw_polyfill pw_preprocessor pw_result pw_span pw_status
pw_string pw_rpc pw_protobuf pw_stream pw_sync pw_toolchain pw_transfer pw_varint
pw_chrono pw_thread pw_sync_stl pw_chrono_stl pw_thread_stl""".split()
directories = [ROOT / "lubancat_hmi/src", ROOT / "lubancat_hmi/tests",
               ROOT / "lubancat_hmi/systemd", ROOT / "firmware_common",
               ROOT / "foc2_app_a/Middleware/pigweed"]
directories += [ROOT / "third_party/pigweed" / module for module in modules]
directories += [ROOT / "third_party/pigweed/third_party/fuchsia/repo/sdk/lib" / module / "include"
                for module in ("fit", "stdcompat")]
extensions = {".h", ".hpp", ".c", ".cc", ".cpp", ".inc", ".cmake", ".conf", ".log"}
files = {ROOT / "lubancat_hmi/CMakeLists.txt", ROOT / "tools/can_fd_business_probe.cpp",
         ROOT / "tests/can_rpc_host/test_assert.h"}
for directory in directories:
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix in extensions:
            if not any(part in {".git", "build", "__pycache__", "local_config"} for part in path.parts):
                files.add(path)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, path.relative_to(ROOT).as_posix())
print(f"SOURCE ONLY: {len(files)} files, {OUTPUT.stat().st_size} bytes")
print("SHA256=" + hashlib.sha256(OUTPUT.read_bytes()).hexdigest())

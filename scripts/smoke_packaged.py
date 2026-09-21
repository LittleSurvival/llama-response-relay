"""Validate the real onefile executable without touching the user's app data."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    executable = Path(sys.argv[1]).resolve(strict=True)
    workspace = Path(__file__).resolve().parents[1]
    scratch = workspace / ".tmp"
    scratch.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="packaged-smoke-", dir=scratch))
    result = run_dir / "result.json"
    env = os.environ.copy()
    for name in ("LOCALAPPDATA", "APPDATA"):
        data_dir = run_dir / name.lower()
        data_dir.mkdir()
        env[name] = str(data_dir)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["LRR_PACKAGED_SMOKE_RESULT"] = str(result)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(
        [str(executable)], cwd=executable.parent, env=env, startupinfo=startup
    )
    try:
        return_code = process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        # Only terminate this smoke test's process tree (including onefile child).
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(f"ERROR: Packaged startup timed out. Diagnostics: {run_dir}")
        return 1
    if return_code != 0 or not result.is_file():
        print(f"ERROR: Packaged startup failed ({return_code}). Diagnostics: {run_dir}")
        return 1
    payload = json.loads(result.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=True))
    if not payload.get("ok") or not payload.get("hardware_provider_assets"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

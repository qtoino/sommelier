"""Run the API (with reload) and the Vite dev server together; Ctrl+C stops both."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
npm = "npm.cmd" if sys.platform == "win32" else "npm"
procs = [
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sommelier.app:app", "--reload", "--port", "8000"],
        cwd=root,
    ),
    subprocess.Popen([npm, "run", "dev", "--", "--port", "5173"], cwd=root / "frontend"),
]
try:
    procs[0].wait()
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        p.terminate()

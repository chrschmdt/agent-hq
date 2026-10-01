from __future__ import annotations

import subprocess
import sys

DEVELOPMENT_ONLY = ("qdrant_client", "pytest", "hypothesis", "respx")


def test_the_web_app_and_the_worker_import_without_development_packages() -> None:
    script = (
        "import sys, ahq.main, ahq.worker; "
        f"print(','.join(name for name in {DEVELOPMENT_ONLY!r} if name in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=60)
    assert result.stdout.strip() == ""

"""Server-owned Web tool defaults; browser settings may only select capabilities."""

import os
import shutil
from pathlib import Path


def default_executables() -> frozenset[str]:
    if os.name == "nt":
        shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
        return frozenset({shell}) if shell and Path(shell).is_file() else frozenset()
    return frozenset({"/bin/sh"}) if Path("/bin/sh").is_file() else frozenset()

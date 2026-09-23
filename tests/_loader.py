"""Load xthread-agent.py (hyphenated filename) as an importable module."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = ROOT / "xthread-agent.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("xthread_agent", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

"""Record pending legacy work without importing or executing its installer."""
import importlib.util
from pathlib import Path

root = Path(__file__).parent
spec = importlib.util.spec_from_file_location('comfyctl_manager_prestartup', root / '_managed.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.scan_pending(root)

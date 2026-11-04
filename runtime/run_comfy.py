"""Launch unmodified ComfyUI with managed data paths."""
import os
import ctypes
from pathlib import Path
import runpy
import sys

if os.getuid() != 1000 or ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0):
    raise RuntimeError('Managed ComfyUI requires service UID and no_new_privs')

source = Path(os.environ['COMFYCTL_COMFY_ROOT'])
sys.path.insert(0, str(source))
sys.path.insert(1, str(Path(__file__).parent))
os.chdir(source)
sys.argv[0] = str(source / 'main.py')
import comfy.options
comfy.options.enable_args_parsing()
from runtime_paths import configure
configure()
runpy.run_path(str(source / 'main.py'), run_name='__main__')

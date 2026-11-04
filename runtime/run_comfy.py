"""Launch unmodified ComfyUI with managed data paths."""
import os
from pathlib import Path
import runpy
import sys

source = Path(os.environ['COMFYCTL_COMFY_ROOT'])
sys.path.insert(0, str(source))
os.chdir(source)
sys.argv[0] = str(source / 'main.py')
import comfy.options
comfy.options.enable_args_parsing()
from runtime_paths import configure
configure()
runpy.run_path(str(source / 'main.py'), run_name='__main__')

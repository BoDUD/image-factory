"""Build with a deterministic DLL search path, excluding unrelated installed tools.

Qt uses the Windows ICU API. Collecting another tool's incompatible icuuc.dll
from PATH can yield an EXE that builds successfully but cannot import QtCore.
"""
import os
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    root=Path(__file__).resolve().parent
    env=dict(os.environ)
    windows=Path(os.environ.get('SystemRoot','C:/Windows'))
    env['PATH']=os.pathsep.join([str(Path(sys.executable).parent),str(Path(sys.base_prefix)),str(windows/'System32'),str(windows)])
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--windowed',
        '--name','ImageFactory','--add-data','image_factory/photoshop.jsx;image_factory','run.py'],cwd=root,env=env,check=True)

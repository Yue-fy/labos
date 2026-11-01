"""Use the existing portable core/runtime, importing only this separate extension."""
from pathlib import Path
import runpy
import sys


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '--labos-root':
        raise SystemExit('Usage: python launch_field.py --labos-root EXISTING_LABOS_ROOT ACTION [arguments]')
    root = Path(sys.argv[2]).resolve()
    extension = Path(__file__).resolve().parent
    if not (root / 'src/labos/__init__.py').is_file():
        raise SystemExit('Existing LabOS root/src/labos is required; no installation is modified')
    sys.path.insert(0, str(root / 'src'))
    sys.path.insert(0, str(extension / 'src'))
    sys.argv = [str(extension / 'launch_field.py'), *sys.argv[3:]]
    runpy.run_module('labos_field', run_name='__main__')

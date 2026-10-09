import argparse
import json
from pathlib import Path

from labos.demo import acceptance

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--full", action="store_true")
parser.add_argument("--source-root", type=Path)
args = parser.parse_args()
print(json.dumps(acceptance(args.directory, args.full, args.source_root), indent=2))

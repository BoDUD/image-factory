"""Read-only environment report; does not install or launch Photoshop."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from image_factory.diagnostics import photoshop_environment

if __name__=='__main__':
    report=photoshop_environment()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

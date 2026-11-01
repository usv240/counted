"""Record real runs of the website's sample cases, so the demo still plays if the live API is unreachable.
Each file is a genuine pipeline output, stamped with when it was recorded."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from counted.pipeline import assess

WEB = Path(__file__).resolve().parents[1] / "web"


def record(sample: dict) -> str:
    result = assess(sample["account"], language=sample["language"])
    result["recorded_at"] = datetime.now().isoformat(timespec="seconds")
    (WEB / "recorded" / f"{sample['id']}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return f"{sample['id']}: {result['panel']['final']['label']} ({result['elapsed_seconds']}s)"


if __name__ == "__main__":
    samples = json.loads((WEB / "samples.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(3) as pool:
        for line in pool.map(record, samples):
            print(line, flush=True)

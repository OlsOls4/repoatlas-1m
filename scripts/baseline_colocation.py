"""For each true drift, report which chunk holds the doc site and which holds the defining code (chunks are deterministic)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from repoatlas.models import RepoPack
from baseline_chunked_beam import build_chunks

SITES = {  # id: (repo, doc_path, doc_line, code_path, code_regex)
 "T1": ("starlette", "docs/websockets.md", 74, "starlette/websockets.py", r"def receive_json"),
 "T2": ("httpx", "docs/advanced/transports.md", 178, "httpx/_client.py", r"mounts: None"),
 "T3": ("httpx", "httpx/_transports/wsgi.py", 50, "httpx/_client.py", r"class Client\("),
 "T4": ("click", "docs/exceptions.md", 110, "src/click/types.py", r"class File\("),
 "T5": ("structlog", "docs/standard-library.md", 117, "src/structlog/_log_levels.py", r"NAME_TO_LEVEL"),
 "T6": ("nox", "docs/usage.rst", 219, "nox/_options.py", r"reuse_venv: ReuseVenvType"),
 "T7": ("arrow", "arrow/arrow.py", 1349, "arrow/arrow.py", r"def dehumanize"),
 "T8": ("cattrs", "docs/customizing.md", 279, "src/cattrs/errors.py", r"class ForbiddenExtraKeysError"),
 "T9": ("cattrs", "src/cattrs/converters.py", 502, "src/cattrs/converters.py", r"def get_unstructure_hook"),
 "T10": ("cattrs", "src/cattrs/converters.py", 651, "src/cattrs/converters.py", r"def get_structure_hook"),
 "T11": ("marshmallow", "docs/top_level.rst", 12, "src/marshmallow/fields.py", r"load_default: typing"),
}

def locate(chunks, path, line):
    for c in chunks:
        for m in re.finditer(r"--- FILE: (\S+)(?: \(lines (\d+)-(\d+) of \d+\))? ---", c["pack"].pack_text):
            if m.group(1) == path and (m.group(2) is None or int(m.group(2)) <= line <= int(m.group(3))):
                return c["index"]
    return None

out = {}
for size in (32000, 128000):
    for tid, (repo, dp, dl, cp, rx) in SITES.items():
        pack = RepoPack.model_validate(json.loads(Path(f"results_live/traces/{repo}-400000.json").read_text())["pack"])
        f = {x.path: x for x in pack.files}
        cl = next((i + 1 for i, l in enumerate(f[cp].lines) if re.search(rx, l)), None) if cp in f else None
        chunks = build_chunks(pack, size)
        dc, cc = locate(chunks, dp, dl), (locate(chunks, cp, cl) if cl else None)
        out[f"{tid}@{size//1000}k"] = {"doc_in_pack": dp in f, "code_in_pack": cp in f, "code_line": cl, "doc_chunk": dc, "code_chunk": cc, "same_chunk": dc is not None and dc == cc}
        print(tid, size, out[f"{tid}@{size//1000}k"])
Path("results_live/baselines/colocation.json").write_text(json.dumps(out, indent=1))

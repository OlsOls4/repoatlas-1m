"""The generated hf_dataset tables must match recorded result counts."""

from __future__ import annotations

import json
from pathlib import Path

from repoatlas.hf_dataset import build_hf_dataset
from repoatlas.hybrid_view import HYBRID_JSON_PATH, HYBRID_REPROS_PATH, HYBRID_TRIAGE_DIRECTORY, LABEL_SOURCE


def test_hf_dataset_row_counts_match_results(tmp_path: Path) -> None:
    """
    @brief 60 findings, 56 verdicts, 54 repros from the live files.
    """

    target = build_hf_dataset(tmp_path / "hf_dataset")
    findings = [json.loads(line) for line in (target / "findings.jsonl").read_text(encoding="utf-8").splitlines()]
    verdicts = [json.loads(line) for line in (target / "triage_verdicts.jsonl").read_text(encoding="utf-8").splitlines()]
    repros = [json.loads(line) for line in (target / "repros.jsonl").read_text(encoding="utf-8").splitlines()]
    hybrid = json.loads(HYBRID_JSON_PATH.read_text(encoding="utf-8"))
    hybrid_row = next(row for row in hybrid["rows"] if "hybrid (symbol" in str(row.get("method", "")).lower())
    assert len(findings) == hybrid_row["findings"] == 60
    judged = 0
    for path in HYBRID_TRIAGE_DIRECTORY.glob("*.json"):
        if path.name.endswith(".attempt1.json"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        judged += len(payload.get("verdicts") or [])
    assert len(verdicts) == judged == hybrid["triage_filter_confusion"]["judged"] == 56
    repro_index = json.loads(HYBRID_REPROS_PATH.read_text(encoding="utf-8"))
    assert len(repros) == len(repro_index) == 54
    assert LABEL_SOURCE in (target / "README.md").read_text(encoding="utf-8")
    assert "hand_verdict" in findings[0]
    assert all("/workspace/" not in json.dumps(row) for row in repros)
    plants = [json.loads(line) for line in (target / "planted_drift.jsonl").read_text(encoding="utf-8").splitlines()]
    assert plants
    ledger = [json.loads(line) for line in (target / "token_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ledger
    assert any(row.get("ledger") == "ablation" for row in ledger)
    ablation_tokens = sum(int(row.get("prompt") or 0) + int(row.get("completion") or 0) for row in ledger if row.get("ledger") == "ablation")
    assert ablation_tokens == 1_948_469
    assert any(row.get("ledger") == "beamv3" for row in ledger)
    beamv3_tokens = sum(int(row.get("prompt") or 0) + int(row.get("completion") or 0) for row in ledger if row.get("ledger") == "beamv3")
    assert beamv3_tokens == 7_713_453
    assert any(row.get("ledger") == "matched_cost" for row in ledger)
    matched_tokens = sum(int(row.get("prompt") or 0) + int(row.get("completion") or 0) for row in ledger if row.get("ledger") == "matched_cost")
    assert matched_tokens == 3_957_434
    assert any(row.get("ledger") == "fresh_run" for row in ledger)
    fresh_tokens = sum(int(row.get("prompt") or 0) + int(row.get("completion") or 0) for row in ledger if row.get("ledger") == "fresh_run")
    assert fresh_tokens == 185_842
    assert any(row.get("ledger") == "first_sweep" for row in ledger)
    first_sweep = [row for row in ledger if row.get("ledger") == "first_sweep"]
    assert len(first_sweep) == 12
    first_sweep_tokens = sum(int(row.get("prompt") or 0) + int(row.get("completion") or 0) for row in first_sweep)
    assert first_sweep_tokens == 4_424_575
    assert not any(row.get("ledger") == "recall" for row in ledger)
    ablation = [json.loads(line) for line in (target / "ablation_verdicts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(ablation) == 56
    assert "matched_verdict" in ablation[0]
    assert any(row.get("matched_verdict") for row in ablation)
    beamv3 = [json.loads(line) for line in (target / "beamv3_findings.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(beamv3) == 115
    assert any(row.get("label") == "unlabelled" for row in beamv3)
    assert all(row.get("label") != "true" or row.get("drift_id") for row in beamv3 if row.get("label") == "true")
    card = (target / "README.md").read_text(encoding="utf-8")
    assert LABEL_SOURCE in card
    assert "7,713,453" in card
    assert "4,424,575" in card
    assert "first_sweep" in card
    assert "3,957,434" in card
    assert "185,842" in card
    assert "Extra experimental runs, not in the 9.3M" in card
    assert "Together +4,143,276" not in card
    assert "not shown at this n" in card
    assert "unlabelled not counted as true" in card
    assert "Unpublished" not in card
    assert "license: cc-by-4.0" in card
    assert "CC BY 4.0" in card
    assert "11 of 12" in card
    assert "hand_verdict" in card
    assert "not a human annotator" in card.lower() or "not a human" in card.lower()
    assert "tags:" in card and "long-context" in card and "- beam" in card
    assert "ollymcbride4/docdrift-bugs" in card
    assert "results_live/" not in card
    assert "RepoAtlas-1M" not in card

# DocDrift planted-drift recall vs distance (Beam, up to ~940k tokens)

Question: does Beam's long context help DocDrift catch doc/code contradictions when the doc line and the code it
contradicts are far apart in the prompt? Measured on 26 Oct 2026 with 30 synthetic drifts planted in real code
(28 for seed 2). Every number below comes from the files in this directory. Nothing was tuned after looking at
the results.

## Context limit probe (`context_probe.json`)

Tiny task ("name the first and last FILE block"), `max_tokens` 2048, reasoning low, one request at a time.

| target | real prompt tokens (API usage) | HTTP | latency |
|---|---|---|---|
| 200k | 196,337 | 200 | 4.9 s |
| 400k | 399,135 | 200 | 14.2 s |
| 600k | 599,153 | 200 | 14.2 s |
| 800k | 797,256 | 200 | 12.5 s |
| ~950k | 947,446 | 200 | 27.6 s |

Every size was accepted. The reported `prompt_tokens` matched the expected size each time, so there was no silent
truncation. Nothing above 947k was tried. At 800k the model named the wrong last file, which is a recall miss and
not a rejection. Real tokens / cl100k ≈ 1.187 on this mix. Below, distances are cl100k × 1.187.

## Haystack and plants

* Source: docs (`.md`/`.rst`) and Python source from 7 pinned libraries already on the box: click 2247b35,
  jinja 5ef7011, werkzeug b73dce5, httpx b5addb6, httpcore 10a6582, uvicorn 9d81c12, structlog 19c4f21. Tests,
  examples, changelogs and files over 150 KB are excluded. Files are ordered with the RepoAtlas packer ranking. The
  pack is cut at 791.9k cl100k, about **940,280 real prompt tokens** per the API. That is 185 files in RepoAtlas
  `<n>|line` pack format. The file order and file set are frozen, so planting never moves a file.
* Plants (`ground_truth_seed{1,2}.json`, exact edits in `plants_seed{1,2}.diff`): realistic renames made from
  synonym swaps such as `raise_for_status→raise_for_state`, `WSGITransport→WSGICarrier`, `TemplateStream→TemplateFlow`.
  No marker text. Line counts are unchanged and every edited `.py` file still compiles.
  * `code_rename_{function,class}`: the definition and every reference in that library are renamed, except the one
    chosen doc line, which becomes stale. Names that also appear in another library, plain-English names, stdlib
    names, and names with more than 30 mentions are excluded.
  * `doc_rename_{function,class}`: only the chosen doc line is changed, to a name that does not exist.
  * `code_rename_kwarg` / `doc_rename_kwarg`: an AST-precise parameter rename covering the signature, body names,
    call-site keywords and the docstring, minus the stale line. Alternatively only the doc line is changed.
    Long-distance doc/kwarg pairs barely exist in this corpus, so only 1–2 kwarg plants per seed made it in, all
    in the ~1k bucket.
  * Mix: seed 1 has 15 code-side and 15 doc-side plants. Seed 2 is a disjoint set (no shared symbols) with 28
    plants. Its 700k+ bucket only reached 4 after the filters.
* Distance = token distance between the stale doc line and the definition (or parameter) line. Buckets: ~1k
  (<3k), ~10k (3–25k), ~50k (25–75k), ~100k (75–150k), ~200k (150–300k), ~400k (300–550k), 700k+ (≥700k).
  `scores.csv` also has `nearest_evidence_real_tokens_est`: the distance to the nearest line anywhere in the pack
  that contains the code-side name. This matters (see below).

## Methods

Same RepoAtlas system prompt and Task A (DocDrift) wording as `prompts.build_analysis_user_prompt`, with two
changes. Task B (atlas claims) is dropped. One sentence was added: "report every drift you can cite; there is no
cap on the number of findings". Strict json_schema `_StructuredModelResponse`, reasoning_effort `medium`.

| run | calls | prompt per call | max_tokens | tokens used |
|---|---|---|---|---|
| whole_seed1 | 1 | ~940k | 40,000 | 950,173 |
| whole_seed2 | 1 | ~940k | 40,000 | 947,600 |
| chunk128k_seed1 | 8 | ≤128k, natural file order | 24,000 | 970,653 |
| chunk32k_seed1 | 35 | ≤32k, natural file order | 12,000 | 1,029,696 |

Chunks are consecutive slices of the same pack. Oversized files are split at line boundaries and keep their
original numbering. There is no oracle pairing of docs with code. All 45 calls returned HTTP 200 with
`finish_reason=stop`: no 429/402, no truncation, no parse failures. The whole-prompt runs used only 9,886 and
7,320 completion tokens of their 40k budget. The model decided to stop.

Scoring (`scripts/run_recall.py score`):
* **strict** = some finding's doc citation and code citation both pass the RepoAtlas verifier (±3-line shift),
  the doc citation is within ±3 lines of the planted stale line in the same file, and the cited code lines/quote
  contain the name the code actually uses.
* **loose** = the doc citation is in the same file within ±5 lines (verified or not), or the finding text names
  both the stale and the real identifier.

## Results (`recall_by_bucket.csv`, `recall_vs_distance.png`)

Strict hits / plants (loose in brackets):

| run | ~1k | ~10k | ~50k | ~100k | ~200k | ~400k | 700k+ | all |
|---|---|---|---|---|---|---|---|---|
| whole seed 1 | 0/4 (0) | 0/4 (0) | 0/4 (0) | 2/4 (2) | 0/4 (0) | 0/4 (0) | 3/6 (3) | **5/30** (5) |
| whole seed 2 | 0/4 (0) | 0/4 (0) | 0/4 (0) | 1/4 (2) | 1/4 (1) | 0/4 (0) | 2/4 (2) | **4/28** (5) |
| chunk 128k seed 1 | 1/4 (1) | 0/4 (0) | 2/4 (2) | 2/4 (4) | 0/4 (0) | 0/4 (0) | 0/6 (0) | **5/30** (7) |
| chunk 32k seed 1 | 3/4 (3) | 0/4 (1) | 0/4 (0) | 1/4 (2) | 0/4 (0) | 1/4 (1) | 0/6 (1) | **5/30** (8) |

Findings per run: whole seed 1 had 7 findings (5 matched plants; the other 2 included the known pre-existing
`httpx.Mounts` drift). Whole seed 2 had 5 (all 5 matched plants). Chunk 128k had 15 (7 matched; 7 of the 8
unmatched passed both citation checks). Chunk 32k had 34 (8 matched; 21 of the 26 unmatched passed both checks).
Unmatched findings are in `raw/*/unplanted_findings.json`. They were not graded as false positives. Many look
like real drifts in these libraries, e.g. werkzeug `reqeust_key` typo, `access_control_expose_headers` docstring
naming the wrong header, jinja `parse_tuple` docstring `no_condexpr` vs `with_condexpr`. Some are opinion
(filters "returns a list" vs iterator).

### What actually drives recall

1. **Position in the prompt, not doc-to-code distance, decides whole-prompt recall.** Across both seeds, all 9
   whole-prompt strict hits are plants whose later line sits in the last ~190k tokens of the 940k prompt. That
   is 9 of the 29 plants there, and 0 of the 29 plants that end earlier. Chunked runs, by contrast, found plants
   at every position (128k: 5/30; 32k: 5/30, spread over positions 190k–950k).
2. **Whole-prompt does find some drifts that chunking cannot see.** Counting plants whose nearest evidence line
   (any mention of the real name) is more than 100k tokens from the stale doc line: whole prompt caught 4/9
   (seed 1: `TemplateStream→TemplateFlow`, 699k; seed 2: `MemcachedBytecodeCache→MemcachedBytecodeMemo`, 127k;
   `render_async→draw_async`, 703k; `iter_bytes→iter_octets`, 765k). Chunked caught 0/4. These all have the stale line near the end of the prompt.
3. **Most plants have evidence nearby anyway.** 35 of 58 plants have a line naming the real symbol within 1k
   tokens of the stale line: an import, a usage, the docstring's own class. The "distance to definition" buckets
   therefore overstate how much long range the task needs. Chunked runs caught 4/20 of those, whole prompt 4/35.
4. **Whole-prompt reports very few findings.** It returned 5–7 findings, using under 25% of its output budget,
   against 15–34 from the chunked runs. Recall is capped by how much Beam chooses to report in one pass, not by
   context acceptance.

## Blunt verdict

* At the 700k+ bucket, whole-prompt beats chunking: 5/10 strict across two seeds, vs 0/6 for both chunked runs
  on seed 1. The plants it finds there are ones no 128k/32k chunk can contain both halves of.
* At every other distance, whole-prompt is no better and often worse. Overall strict recall is 5/30 and 4/28,
  vs 5/30 for each chunked run. Loose recall favours chunking (7–8/30 vs 5/30). Chunking also surfaces 3–4×
  more verifiable findings.
* The whole-prompt pass is essentially blind to the first ~750k tokens as a place to *look for* drift (0/29).
  It can still *resolve* a stale doc line at the end against code ~700k tokens earlier. The honest headline is
  "long context lets Beam connect far-apart evidence, but a single ~1M pass only scans the tail". This is not
  "long context improves recall".

## Caveats

* Small n: 4–6 plants per bucket, 1 run per method (2 seeds only for whole prompt). One hit moves a bucket by
  17–25 points. Chunked methods were run on seed 1 only. No repeat runs, so run-to-run variance is unmeasured.
* The position effect is confounded with content. The tail of this pack is mostly jinja/httpx/werkzeug docs and
  later-ranked files, and doc-side plants at long distances tend to sit in docs, which come late. Positions were
  not randomised. A controlled test would shuffle the file order or put the same plants at the start and at the end.
* Plants are renames only: no default/flag/env-var drift, and few kwarg plants. These are synthetic, even if
  realistic.
* Distances use cl100k × 1.187 (measured on this corpus). Beam's tokenizer differs slightly line by line.
* The prompt deviates from production RepoAtlas (Task B dropped, "no cap" sentence). Reasoning effort was medium
  for all runs. Chunked runs got more total output budget (8×24k, 35×12k) than whole prompt (40k), but whole
  prompt used only 7–10k of its budget.
* One 128k chunk got a 114,688-token prefix cache hit from the preceding whole-prompt run. Tokens were still
  counted. Another process was calling Beam concurrently; all calls were serialised via the shared lock.
* "Known real" pre-existing drift matching is a small hand list from earlier review (`KNOWN_REAL` in
  `scripts/run_recall.py`). The other unplanted findings are unjudged: neither confirmed real nor counted as FP.
* Total Beam usage for this work, from `usage_ledger.json`: 6,838,417 tokens. That is 2,940,295 for the probe
  and 3,898,122 for the four benchmark runs. It excludes the other baseline process.

## Reproduce

```
RECALL_CALIB=1.187 python scripts/run_recall.py probe        # context probe
RECALL_CALIB=1.187 python scripts/run_recall.py plant --seeds 1 2 --disjoint
RECALL_CALIB=1.187 python scripts/run_recall.py run whole --seed 1   # also: whole --seed 2, chunk128k, chunk32k
RECALL_CALIB=1.187 python scripts/run_recall.py score
```
Work trees live in `/workspace/recall_work` (clean + seed1/seed2 copies, packs). Raw responses are in `raw/`.

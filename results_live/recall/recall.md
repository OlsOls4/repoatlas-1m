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

## Blunt verdict (v1)

* At the 700k+ bucket, whole-prompt beats chunking: 5/10 strict across two seeds, vs 0/6 for both chunked runs
  on seed 1. The plants it finds there are ones no 128k/32k chunk can contain both halves of.
* At every other distance, whole-prompt is no better and often worse. Overall strict recall is 5/30 and 4/28,
  vs 5/30 for each chunked run. Loose recall favours chunking (7–8/30 vs 5/30). Chunking also surfaces 3–4×
  more verifiable findings.
* The whole-prompt pass is essentially blind to the first ~750k tokens as a place to *look for* drift (0/29).
  It can still *resolve* a stale doc line at the end against code ~700k tokens earlier. The honest headline is
  "long context lets Beam connect far-apart evidence, but a single ~1M pass only scans the tail". This is not
  "long context improves recall".

## v2: whole-context fixes for the end-of-prompt effect

These runs use the same haystacks (`pack_seed{1,2}.json`, the same 185 files and line numbers), the same plants and
the same strict/loose scoring as v1. Only the file order and the instructions change. All calls are sequential,
use reasoning effort medium and max_tokens 40,000, and send a ~940.3k-941.1k real prompt.

* **A. Docs-last** (`docslast`): every code file first, then all 11 `.md`/`.rst` files (79.7k cl100k, about 10% of
  the pack), keeping relative order. A final instruction section after the corpus says to go through every doc
  file one by one, then the docstrings, and not to stop early. One call per seed.
* **B. Focused passes** (`focused`): the original order and full corpus every time, plus a final section after
  the corpus that names one slice and says to audit only the docs in that slice against any code in the
  prompt. 18/30 (seed 1) plants have their stale line in a `.py` docstring, and the pack only has 11 doc files.
  A "docs only" split would therefore leave most plants unauditable. So the 5 slices are:
  * slice 1: all 11 `.md`/`.rst` files;
  * slices 2-5: the 174 `.py` files in pack order (56/40/28/50 files, equal token shares), for docstrings,
    comments and help text.

  The slice text was **not** repeated at the end. Even the smallest slice (about 95k real tokens) would push the
  prompt past 1.03M, beyond the 947k the probe verified. Findings from the passes are merged and deduped on
  (doc path, doc start line, code path); there were no duplicates. Seed 1 only. The full 5 passes on seed 2 did
  not fit the 9M budget, so **only pass 1 (docs slice) was run on seed 2** (`focusdocs`).
* **C. Shuffle control** (`shuffled`): the same prompt as v1 whole, with file order shuffled
  (`random.Random(20261026)`). Seed 1.

Strict hits / plants (loose in brackets). The v1 rows are repeated for comparison:

| run | calls | tokens | findings | ~1k | ~10k | ~50k | ~100k | ~200k | ~400k | 700k+ | all |
|---|---|---|---|---|---|---|---|---|---|---|---|
| whole seed 1 (v1) | 1 | 950,173 | 7 | 0/4 | 0/4 | 0/4 | 2/4 | 0/4 | 0/4 | 3/6 | **5/30** (5) |
| whole seed 2 (v1) | 1 | 947,600 | 5 | 0/4 | 0/4 | 0/4 | 1/4 (2) | 1/4 | 0/4 | 2/4 | **4/28** (5) |
| chunk 128k seed 1 (v1) | 8 | 970,653 | 15 | 1/4 | 0/4 | 2/4 | 2/4 (4) | 0/4 | 0/4 | 0/6 | **5/30** (7) |
| chunk 32k seed 1 (v1) | 35 | 1,029,696 | 34 | 3/4 | 0/4 (1) | 0/4 | 1/4 (2) | 0/4 | 1/4 | 0/6 (1) | **5/30** (8) |
| A docs-last seed 1 | 1 | 944,309 | 6 | 0/4 | 0/4 | 0/4 | 2/4 | 0/4 | 0/4 | 3/6 | **5/30** (5) |
| A docs-last seed 2 | 1 | 953,540 | 9 | 1/4 | 0/4 | 0/4 | 2/4 | 0/4 (1) | 1/4 | 1/4 (2) | **5/28** (7) |
| B focused ×5 seed 1 | 5 | 4,755,853 | 29 | 1/4 | 0/4 | 1/4 | 3/4 | 0/4 | 1/4 | **5/6** | **11/30** (11) |
| B pass 1 only seed 2 | 1 | 946,765 | 9 | 0/4 | 0/4 (1) | 0/4 | 2/4 | 0/4 (1) | 0/4 (1) | 3/4 | **5/28** (8) |
| C shuffled seed 1 | 1 | 946,284 | 5 | 0/4 | 0/4 | 0/4 | 1/4 | 0/4 | 0/4 | 1/6 (2) | **2/30** (3) |

The findings column counts every structured finding returned. For the new runs:

* B seed 1: 29 findings, 25 passing both citation checks; 11 matched plants. Of the 18 unplanted, 14 were
  verified (1 known real). By pass: 11 / 6 / 3 / 5 / 4 findings, using 12,279 / 14,688 / 8,508 / 5,662 / 10,467
  completion tokens.
* A: 6 findings (5 matched) on seed 1 and 9 (7 matched) on seed 2.
* C: 5 findings (3 matched).
* B pass 1 seed 2: 9 findings (8 matched).

No errors, 429s, parse failures or truncations. Every call finished with `stop`, well under 40k completion tokens.

### Where the hits come from (strict, by where the stale line lives and where the later line sits in *that* prompt)

| run | doc-file plants | docstring plants | later line ≥750k | later line <750k |
|---|---|---|---|---|
| whole s1 / s2 | 5/12, 4/14 | 0/18, 0/14 | 5/16, 4/14 | 0/14, 0/14 |
| A docs-last s1 / s2 | 5/12, 4/14 | 0/18, 1/14 | 5/16, 4/14 | 0/14, 1/14 |
| B focused s1 | **8/12** | 3/18 | 9/16 | 2/14 |
| B pass 1 only s2 | 5/14 | 0/14 | 5/14 | 0/14 |
| C shuffled s1 | 2/12 | 0/18 | 1/11 | 1/19 |
| chunk 128k s1 | 2/12 | 3/18 | 2/16 | 3/14 |
| chunk 32k s1 | 1/12 | 4/18 | 2/16 | 3/14 |

For B seed 1, the hits per pass were:

* pass 1 (docs): 8, namely P1-13/14/15/26/27/28/29/30;
* pass 3: 1 (P1-10);
* pass 5: 2 (P1-02, P1-24);
* passes 2 and 4: 0.

### What v2 shows

1. **A changed almost nothing, because the packer already puts docs last.** In the original order the 11 doc
   files already started at ~763k real tokens. Docs-last only moved them to ~845k. On seed 1 it hit exactly
   the same 5 plants as v1 whole. The "finish every file" instruction did not make Beam report more: 6 findings
   vs 7. Seed 2 went from 4/28 to 5/28 and from 5 to 9 findings, a one-plant difference within noise.
2. **The v1 "end-of-prompt effect" is mostly a "doc files vs docstrings" effect.** Every whole-prompt
   single-call run (v1 whole, A, C) found 0-1 of the 32 docstring plants, whatever the order. All its hits are
   `.md`/`.rst` plants. Those happened to be the last ~180k tokens in the original order, which is why v1 looked
   like a pure position effect.
3. **Position still matters for doc files (C).** Shuffling moved the doc files to positions 92k-847k, and
   doc-file hits fell from 5/12 to 2/12 (overall 5/30 → 2/30). With n=12 that is suggestive, not conclusive.
   So both effects exist: a single pass mostly audits doc files, and audits them better near the end.
4. **B is the only whole-context method that beat chunking overall, on seed 1, and it costs 4.6-4.9× the
   tokens.**
   * Overall: 11/30 vs 5/30 for each chunker.
   * 700k+: 5/6 vs 0/6.
   * Most of the gain is the docs pass: 8/12 doc-file plants vs 5/12 for a plain whole call.
   * The four docstring passes (3.8M tokens) found 3/18 docstring plants. That is no better than chunk 128k
     (3/18 at 0.97M) or chunk 32k (4/18 at 1.03M).
5. **The docs-pass gain only partly replicated on seed 2.** On seed 2, pass 1 found 5/14 doc-file plants against
   4/14 for whole and 4/14 for docs-last. That is +1 plant, vs +3 on seed 1. The docstring passes were not run on
   seed 2, so B's full seed-2 recall is unknown.
6. A post-hoc observation, not a run: on seed 1, the B docs pass (1 call) plus chunk 32k (35 calls) together cover
   12/30 strict at ~1.98M tokens. That is more than B's 11/30 at 4.76M. A focused whole-context pass over the doc
   files, plus small chunks for docstrings, looks like the efficient split. It is untested as a single pipeline.

## Blunt verdict (v2)

* **Yes, but only one method, on one seed, at ~4.7× the cost.** B (5 focused full-context passes) got 11/30
  strict and 5/6 at 700k+ on seed 1, vs 5/30 and 0/6 for chunked 128k/32k. A (docs-last + finish-all) did not
  beat chunking: 5/30 and 5/28, the same as chunking and the v1 whole prompt. C (shuffled) was worse: 2/30.
* At matched token budgets (~1M), no whole-context variant beats chunking overall. Every single-call variant
  lands at 2-5 strict hits. Its edge is confined to the 700k+ doc-file plants, where chunking scores 0.
* Long context earns its keep only in a focused pass over the doc files, which drives the 700k+ wins. For
  docstrings, which are most of the plants, chunking is as good and 4× cheaper.

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
* Total Beam usage for this work, from `usage_ledger.json`: 15,385,168 tokens. v1 used 6,838,417: 2,940,295 for
  the probe and 3,898,122 for the four benchmark runs. v2 used 8,546,751 of its 9M cap:
  * A: 1,897,849
  * B seed 1: 4,755,853
  * B pass 1, seed 2: 946,765
  * C: 946,284

  This excludes the other baseline process. Beam reported 934k-940k cached prompt tokens on B passes 2-5 and on
  the seed-2 pass. Those are still counted in full here.
* v2 caveats:
  * B and A each bundle two changes: placement of the instruction after the corpus plus slicing or reordering.
    They were not ablated.
  * B's slices 2-5 split code files by pack order, not by library.
  * The slice text was not repeated.
  * Single run per configuration, so run-to-run variance is unmeasured. The seed-1 vs seed-2 gap for the docs
    pass (+3 vs +1) suggests it is material.
  * Chunked methods were never given B's ~4.7M token budget (e.g. multiple chunk runs or overlapping chunks).
    The cost-matched comparison is therefore single-call vs chunking at ~1M only.

## Reproduce

```
RECALL_CALIB=1.187 python scripts/run_recall.py probe        # context probe
RECALL_CALIB=1.187 python scripts/run_recall.py plant --seeds 1 2 --disjoint
RECALL_CALIB=1.187 python scripts/run_recall.py run whole --seed 1   # also: whole --seed 2, chunk128k, chunk32k
# v2 (budget guard: --new-cap/--new-base; RECALL_CAP raises the cumulative ledger cap)
RECALL_CAP=15838417 python scripts/run_recall.py run docslast --seed 1 --new-cap 9000000 --new-base 6838417
#   also: docslast --seed 2, focused --seed 1, shuffled --seed 1, focusdocs --seed 2
RECALL_CALIB=1.187 python scripts/run_recall.py score
```
Work trees live in `/workspace/recall_work` (clean + seed1/seed2 copies, packs). Raw responses are in `raw/`.

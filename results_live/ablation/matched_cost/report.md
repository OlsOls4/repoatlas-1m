# Matched-cost control: whole-repo vs retrieval triage at equal Beam spend

The design was pre-registered in `design.md` before any item was sent to Beam. Frozen at 2026-10-30T11:34:09 UTC. The sha256 values in `preregistration.sha256` still match the design and the run script.

## Question
The ablation found that whole-repo triage cites cross-file evidence much more often than local-file triage. But whole-repo also used about 4.8× more tokens: 4,022,532 against 830,527. Is the grounding gain from *seeing the whole repo*, or only from *spending more*?

## Control
- **"Matched":** each of the same 56 ablation candidates gets the local files plus retrieved files.
- **Retrieval tiers:**
  - T0: local files.
  - T1: files that define or use the candidate's symbols (grep).
  - T2: the import neighbourhood of the local files.
  - T3: BM25 over the claim text.
- **Budget:** the files fill a per-item budget of 4,022,532 / 56 = 71,831 tokens, minus 3,000 for output. That leaves 56,416 cl100k prompt tokens per item.
- **Everything else is held fixed:** the same model (`beam`), the same system prompt, schema, parser, citation verifier and gold labels, and the same scorer (path match and line overlap within ±3).
- **Context per item:** 13.7 files on average. Of the files used: T1 367, T2 202, T3 116, T0 80.

## Results (n = 56 candidates; 30 cross-file; 13 where the gold evidence is outside the local files)

| metric | whole-repo | **matched retrieval** | local |
|---|---|---|---|
| Beam tokens (triage) | 4,022,532 | **3,888,241** (96.7% of whole) | 830,527 |
| Verdict accuracy | 47/56 = 0.839 [0.722, 0.913] | **46/56 = 0.821 [0.702, 0.900]** | 47/56 = 0.839 [0.722, 0.913] |
| Citation correct (gradable) | 41/52 [0.660, 0.878] | **37/52 [0.577, 0.817]** | 34/52 [0.518, 0.768] |
| Cross-file: right verdict + right citation | **25/30 = 0.833 [0.664, 0.927]** | 19/30 = 0.633 [0.455, 0.781] | 14/30 = 0.467 [0.302, 0.639] |
| Evidence outside local files: right verdict + right citation | **11/13 [0.578, 0.957]** | 6/13 [0.232, 0.709] | 0/13 [0.000, 0.228] |
| Verified citations pointing outside the local files | 18 | 18 | 0 |

The intervals are Wilson 95%. The paired tests are exact two-sided McNemar on the same items.

| comparison | whole only | other only | p |
|---|---|---|---|
| cross-file verdict+cite, whole vs matched | 7 | 1 | **0.070** |
| outside-local verdict+cite, whole vs matched | 6 | 1 | 0.125 |
| accuracy, whole vs matched | 4 | 3 | 1.000 |
| cross-file verdict+cite, matched vs local | matched 6 | local 1 | 0.125 |

## Verdict under the pre-registered rule
- **Grounding:** whole-repo is still ahead at matched cost: 25/30 against 19/30 cross-file, and 11/13 against 6/13 where the evidence is outside the local files. But the McNemar p is 0.070, which is above 0.05. Under the rule we fixed in advance, this is **"not shown at this n"**. We cannot claim that whole-repo beats retrieval on grounding at equal spend with statistical confidence. The direction does favour whole-repo: 7 discordant items went its way and 1 went the other way.
- **Accuracy:** no meaningful difference: 47/56 against 46/56, p = 1.0. Retrieval at equal spend matches whole-repo on verdicts. So does local triage at one-fifth of the cost.
- **Retrieval against local:** spending the same budget on retrieval recovers part of the grounding gap: 19/30 against 14/30 cross-file, and 6/13 against 0/13 outside-local. That gain is also not significant (p = 0.125).

## Why retrieval falls short
- **Gold file not retrieved:** 5 of the 13 outside-local items, and 5 of the 30 cross-file items. In these cases retrieval brought in an importer or a re-export instead of the defining file. Examples:
  - click S10: `click/__init__.py`, the `File` re-export, instead of `types.py:915`.
  - cattrs S25: `gen/__init__.py` instead of `errors.py:118`.
  - nox S21: a test file instead of `_options.py:333`.

  Beam's verdict was still right in each of these, and the quote it cited is real, but it is not the definition.
- **Defining file in context but not cited:** arrow S22. The context included `arrow/locales.py`, but Beam cited an import line in `parser.py`.
- **Parse failure counted as wrong:** nox S20. Beam returned invalid JSON twice: the first send and the one pre-registered nonce re-send. Under the rule it counts as wrong. The unparsed text did contain a correct verdict and citation. If it were credited, the result would be cross-file 20/30, discordant 6 against 1, p = 0.125, and accuracy 47/56 against 47/56. The conclusion does not change.

## Caveats
- The whole-repo and local arms are the ablation's existing runs; they were not re-run. Only the matched arm is new. Beam is not deterministic. The ablation's stability check bounds that variation, but this arm was run once.
- The gold citations are single "best" lines from an AI reviewer working against pinned source. A re-export line can be a defensible citation and still score as wrong. This penalises retrieval, which more often lands on importers. So the grounding gap is an upper-end estimate.
- n = 30 cross-file items gives low power. A gap of 25 against 19 needs roughly twice the n to settle.

## Spend
- Matched arm: 57 Beam calls (56 items + 1 re-send), 3,957,434 tokens as spent: 3,825,471 prompt and 131,963 completion. Of that, 3,888,241 is attributable to the final per-item records.
- No 402, 429 or quota responses.

## Proposed site-section text
> **Is it the whole repo, or just more tokens?** We gave a retrieval baseline the *same* Beam budget as whole-repo triage. That came to about 3.9M against 4.0M tokens over the same 56 candidates. For each candidate, it got the local files plus the symbol definitions, imports and BM25 matches that fit in about 56k tokens.
>
> Verdict accuracy came out the same (46/56 against 47/56). Grounding still favoured the whole repo: the right verdict *and* the right cross-file line in 25/30 cases, against 19/30 for retrieval. Where the evidence lives outside the files the doc points at, the figures are 11/13 against 6/13. Retrieval usually found *a* related file, such as an import or re-export, but not the one that defines the API.
>
> That gap is suggestive, not proven, at this sample size (exact McNemar p = 0.07). We pre-registered the test and report it as "not shown at this n". The honest takeaway: whole-repo context doesn't make Beam *judge* better, but it helps Beam *point at the right line* more often, for the same spend.

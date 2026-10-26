# Long-context ablation: does Beam's triage need the whole repo?

**Question.** DocDrift v2 sends every drift candidate for a repo to Beam in one call, together with the full ~400k-token
RepoAtlas pack. Does that whole-repo context actually improve triage, compared with showing Beam only the files the
candidate names?

## Setup
- **Candidates:** the same 56 candidates the hybrid run judged, from 11 repos. structlog is excluded because its
  hybrid triage failed to parse, so its 6 candidates were never judged.
- **Fixed across conditions:** the same pinned snapshots, `SYSTEM` prompt, `build_user_prompt` template, strict JSON
  schema, `max_tokens=32000` and `reasoning_effort=medium`.
  - Model: `beam` via Ollama Cloud (`https://ollama.com/v1`).
- **Whole-repo:** the existing hybrid verdicts in `results_live/hybrid/triage/`, reused unchanged. That is one batched
  call per repo, with prompts of 295k–395k tokens.
- **Local-file only:** one call per candidate. The pack is cut down to the candidate's doc file plus any pack file whose
  path appears in the candidate's `claim` or `code_hint`. Line numbers are the same as in the full snapshot.
  - The instruction text is byte-identical, including "use the whole repository".
  - Citations are still checked against the *full* snapshot.
- **Stability:** whole-repo triage was rerun on httpx, werkzeug and marshmallow (27 candidates). It used exactly the
  same payload as the hybrid run, sent fresh with no cache.
- **Labels:** `scripts/_symbol_verdicts.py` and `results_live/repros/hand_labels.json`. "unclear" counts as not-true.
  - **These labels were written by an AI reviewer checking against the pinned source, not by a human maintainer.**
- **Gold evidence** (`scripts/_ablation_gold.py`): the file:line(s) holding the decisive evidence for each candidate,
  taken from the same label notes.
  - A citation counts as correct when the path matches and the lines overlap gold within ±3 lines.
  - 52 of the 56 candidates can be graded this way. The 4 unclear jinja/werkzeug items cannot.
  - *Cross-file* means the decisive evidence is in a file other than the doc file that carries the claim (30 cases).
  - *Evidence outside local context* means no gold file is among the local-condition files (13 cases). This is the only
    subset where the local condition truly cannot see the evidence.

## Results
| Metric | Whole-repo (reused hybrid) | Local-file only | Whole-repo, subset (27) | Local, subset (27) | Whole-repo rerun, subset (27) |
|---|---|---|---|---|---|
| True candidates kept | 32/32 | 32/32 | 13/13 | 13/13 | 13/13 |
| False/unclear candidates rejected | 15/24 | 15/24 | 9/14 | 12/14 | 10/14 |
| Precision (kept that are true) | 0.78 (32/41) | 0.78 (32/41) | 0.722 (13/18) | 0.867 (13/15) | 0.765 (13/17) |
| Verdict accuracy | 0.839 | 0.839 | 0.815 | 0.926 | 0.852 |
| Citation hits gold file:line (gradable) | 41/52 | 34/52 | 19/26 | 19/26 | 22/26 |
| Right verdict + gold citation | 39/52 | 33/52 | 17/26 | 19/26 | 20/26 |
| Citation verified (quote matches source) | 54/56 | 52/56 | 25/27 | 26/27 | 27/27 |
| Cross-file cases: right verdict | 26/30 | 26/30 | 12/13 | 12/13 | 12/13 |
| Cross-file cases: right verdict + citation | 25/30 | 14/30 | 12/13 | 8/13 | 12/13 |
| Evidence outside local context: right verdict | 12/13 | 12/13 | 4/4 | 4/4 | 4/4 |
| Evidence outside local context: right verdict + citation | 11/13 | 0/13 | 4/4 | 0/4 | 4/4 |
| Beam tokens | 4,022,532 (11 calls; 4,331,995 as spent incl. a cattrs re-send) | 830,527 (56 calls; 848,654 as spent incl. 1 re-send) | — | — | 1,099,815 |

The token figures are prompt plus completion tokens, as reported by the API. This ablation's own ledger came to
**1,948,469 tokens over 60 calls**:
- local: 57 calls, 848,654 tokens;
- stability: 3 calls, 1,099,815 tokens.

No 402, 429 or quota responses were seen. One local response (jinja DD-1) returned JSON that would not parse. It was
re-sent once (nonce `resend-1`); both raw responses are kept.

### Where the two conditions disagree (6 of 56)
| Candidate | Label | Whole-repo | Local | Which is right |
|---|---|---|---|---|
| httpx S7 (`allow_redirects` in a requests-compat snippet) | false | keep | reject | local; whole-repo also flipped to reject on the rerun |
| werkzeug S38 (`werkzeug.proxy_fix.orig` environ key) | false | keep | reject | local |
| werkzeug S39 (same) | false | keep | reject | local |
| jinja S17 (removed `with_` extension) | unclear | reject | keep | whole-repo (unclear counts as not-true) |
| jinja S18 (removed `autoescape` extension) | unclear | reject | keep | whole-repo |
| pydantic-settings DD-1 (kebab-case default prose) | false | reject | keep | whole-repo |

The 4 false candidates that **both** conditions keep are all cross-file:
- arrow DD-2, DD-3 and DD-4 (locale and hour-range wording);
- marshmallow DD-1 (`SchemaOpts` kwargs).

### What the local condition cites when the evidence is out of view
Take the 13 cases where the local pack does not contain the evidence (for example httpx S6 `httpx.Mounts`, click S10
`FileType`, nox S21 `reuse_venvs`, cattrs S25, attrs S11, werkzeug S35/S36/S40).
- Local still gives the right verdict in 12 of them.
- It reaches that verdict by trusting the candidate text, the doc file itself, or prior knowledge.
- It cites the doc line or an unrelated local file, never the defining code (0/13).
  - Example: cattrs S25. Its reason is built from the doc example rather than `errors.py:118`.
- Whole-repo cites the actual definition in 11 of the 13.
The symbol-check candidates already carry repo-wide evidence in their claim text, such as "'fromordinal' not found on
arrow" or "def httpx/_api.py:174". So part of the "whole-repo" knowledge reaches the local condition through the
candidate itself.

### Stability
On the 27-candidate subset, the whole-repo rerun agreed with the original verdicts on 26 of 27. The one flip was httpx S7,
from keep to reject, which is the label-correct direction. Citation accuracy on the subset rose from 19/26 to 22/26.
So run-to-run noise in whole-repo triage is about the same size as the local-vs-whole verdict differences on this
subset (1 flip vs 3).

## Interpretation (honest)
**At the verdict level, whole-repo context did not beat local-file context here.**
- Both kept all 32 true candidates and rejected 15 of 24 false or unclear ones. Precision was identical (0.78).
- They disagreed on 6 of 56, and each side was right on 3.
- Local was right on S7/S38/S39 and whole-repo on jinja S17/S18 and pydantic-settings DD-1.
- Even where the evidence was out of local view, local got 12 of 13 verdicts right. That is largely because the
  candidates already encode repo-wide facts.

**What whole-repo context did buy is grounding.**
- On cross-file cases, Beam's citation pointed at the real decisive file:line in 25 of 30, against 14 of 30 for local.
- Where the evidence was outside the local files, it was 11 of 13 against 0 of 13.
- That matters for DocDrift because the citation is what gets verified, reproduced, and shown to maintainers. A correct
  verdict citing the doc line is far less useful than one citing `types.py:915`.

**The cost is real.** Whole-repo used about 4.0M tokens over 11 calls; local used 0.83M over 56 calls, about 4.8× less.

**Caveats:**
- n=56, and the conditions differ by less than run-to-run noise.
- Labels and gold lines come from an AI reviewer.
- Whole-repo is batched (it sees sibling candidates and duplicate S/DD pairs together), while local is one candidate per
  call. So "context" is not the only thing that differs.
- Local's file selection is generous: it uses file paths the candidate generator found with whole-repo tools.

The fair claim for "innovative use of Beam" is therefore that **long context makes the triage evidence-grounded across
files**. It is not that it makes the verdicts more accurate.

## Files
- `scripts/ablation_triage.py`: runs the local and stability conditions. It has its own ledger and cap, and stops on a
  402, a 429 after backoff, or a quota error.
- `scripts/ablation_score.py` and `scripts/_ablation_gold.py`: scoring and the gold evidence locations.
- `results_live/ablation/results.json`: metrics, tokens, disagreements and per-candidate rows.
- `results_live/ablation/table.md` and `results_live/ablation/ablation.md`.
- `results_live/ablation/local/<repo>__<cid>.json` and `results_live/ablation/stability/<repo>.json`: parsed verdicts.
- `results_live/ablation/raw/{local,stability}/`: raw API bodies. They hold usage and content, not the request key.
- `results_live/ablation/beam_usage_ledger.json`.

Reproduce with:
```
python scripts/ablation_triage.py --mode local
python scripts/ablation_triage.py --mode stability --repos httpx,werkzeug,marshmallow
python scripts/ablation_score.py
```
Cached raw responses are reused when present.

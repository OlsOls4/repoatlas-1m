# Matched-cost control — pre-registered extension: results

Scored by `scripts/ext_score.py` (unchanged, sha256 `c17e299d…1721`) → `results.json`. Design: `design_ext.md`
(sha256 `42f6b6fe970a24138b201118605e227458eecb567f783dbad0e5e3e4c9fac996`), frozen in `preregistration_ext.json`
at 2026-10-30 13:21 UK, before any extension Beam call. All 5 frozen-file hashes, the 2 reused-script hashes and the
12 pack hashes were re-checked before the resume (about 14:05 UK, 30 Oct) and again after scoring, and still match. No frozen file was edited.

## Headline (pre-registered primary)

**POOLED cross-file items (original 30 + new 48 with both arms), right verdict AND gold citation, whole vs matched,
exact two-sided McNemar: whole 52/78 vs matched 38/78; discordant whole-only 20 vs matched-only 6; p = 0.0094.**

Under the pre-registered rule (p < 0.05, whole ahead) this reads: **whole-repo context beats matched-cost retrieval on
cross-file evidence** (right verdict + right cross-file line). It does not say whole-repo judges verdicts better (see
accuracy below), and it is sensitive to the pre-registered parse-failure re-send (see "Robustness").

n is 78, not the planned 79: the matched call for `real-structlog:structlog-400000:DD-1` timed out (900 s ReadTimeout)
and, per the design, a timeout is not resent. The design says the primary then uses only items with both whole and
matched results. Counting DD-1 either way gives p = 0.0094 (matched wrong) or p = 0.0192 (matched right); whole was
wrong on DD-1 (it kept a false item).

## Secondary (descriptive, not used for the headline)

| Pooled (56 orig + 63 new) | whole | matched | local |
|---|---|---|---|
| Verdict accuracy | 108/119 (91%; 95% CI 0.84–0.95) | 105/118 (89%; 0.82–0.93) | 97/119 (82%; 0.74–0.88) |
| Cross-file verdict + gold cite | 52/79 (0.55–0.75) | 38/78 (0.38–0.60) | 14/79 (0.11–0.28) |
| Evidence outside local files, verdict + cite | 38/61 | 25/61 | 0/61 |
| All gradable, verdict + cite | 76/115 | 66/114 | 43/115 |

Paired whole vs matched (exact McNemar), pooled:
- verdict accuracy: 7 vs 4 discordant, p = 0.549 — **no accuracy difference shown**;
- outside-local verdict + cite: 19 vs 6, p = 0.0146;
- all gradable verdict + cite: 22 vs 12, p = 0.121;
- lenient (right file, any line), cross-file: 16 vs 8, p = 0.152 — much of the gap is the exact line, not the file.
- local vs matched cross-file: 1 vs 25, p < 0.001; whole vs local cross-file: 38 vs 0, p < 0.001.

New items only (63): cross-file whole 27/49 vs matched 19/48; discordant 13 vs 5, **p = 0.096 (not shown at this n on
its own)**; accuracy 61/63 vs 59/62 (p = 0.625).

Strata:
- **original 56** (not rerun): cross-file 25/30 vs 19/30, 7 vs 1, p = 0.070; accuracy 47/56 vs 46/56.
- **planted (57; synthetic synonym-swap renames, all true)**: cross-file 27/45 vs 19/45, 13 vs 5, p = 0.096; accuracy
  57/57 vs 55/57; local 0/45 cross-file.
- **real structlog (6)**: no arm got a cross-file item right (whole 0/4, matched 0/3, local 0/4); accuracy 4/6, 4/5, 4/6.

Retrieval failure modes (pooled cross-file, whole right & matched wrong, n = 20): gold file not retrieved into the
matched context 12; gold retrieved, right verdict, citation misses gold line 7; matched parse failure 1 (orig nox S20).
The gold file was retrieved into the matched context for 57 of 78 cross-file items.

## Robustness (not pre-registered; disclosed because the headline depends on it)

Three calls failed to parse on the first attempt: whole `planted1-structlog` (6 items), matched `planted1-jinja:P1-18`
and matched `real-structlog:S16`. Each got exactly the one pre-registered nonce re-send (`nonce=resend-1`, raw kept in
`raw/*/…__resend-1.json`; first attempts in `items/*` `resend.first_attempt` and `resume/first_attempt/`). All three
parsed on the re-send.
- With the re-sends (as pre-registered): p = **0.0094** (20 vs 6).
- First attempts only (as if no re-send): 18 vs 10, p = 0.185.
- Without the 3 items run after the timeout stop (S14/S15/S16): unchanged, 20 vs 6, p = 0.0094 (n = 77).

So the significant result relies on the pre-registered re-send of the whole-repo planted1-structlog call. The
planted items also carry the pre-stated asymmetry that synonym swaps hide the new name from T1 lexical retrieval.

## Tokens (extension ledger `beam_usage_ledger.json`)

- Total **7,528,878** API tokens in 141 calls (cap 11.5M): whole 2,279,494 (14 calls incl. 1 re-send), local 831,498
  (63), matched 4,417,886 (64 incl. 2 re-sends). On the extension, matched retrieval spent ~1.9× the whole-repo arm.
- 1 further call (matched DD-1) timed out with no usage returned; it may have been billed, but no token count exists
  so none is recorded.
- Resume session (30 Oct, 14:14–14:17 UK): 9 calls, 469,870 tokens (6 remaining local/matched items + 3 re-sends).
- Matched-cost control overall (original 3,957,434 + extension 7,528,878) = **11,486,312** extra experimental tokens,
  not part of the 9.3M hybrid end-to-end. Ollama Cloud free tier; zero spend.

## Deviations from the pre-registration

1. The run stopped on a timeout (the matched DD-1 call, at about 14:12 UK). The design's stop rule stops the run on a
   timeout. On instruction it was **resumed** for the 3 remaining items (S16, S14, S15; 6 calls) using a wrapper
   (`resume/resume_guard.py`) that imports the frozen `scripts/ext_run.py` unchanged and refuses to re-call any item that
   already has a raw output. Dropping those 3 items does not change the primary (above).
2. The DD-1 matched call was **not** resent (as the design requires), so the primary n is 78, not 79.
3. The 3 pre-registered parse-failure re-sends were run after the main pass rather than inline (same payload + nonce
   as the design specifies; the frozen runner has no inline re-send).
4. Everything else (items, prompts, budget, scoring, test) is as pre-registered; `ext_score.py` was run unmodified.

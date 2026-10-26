<!-- DRAFT ONLY. Not filed. Target: https://github.com/arrow-py/arrow/issues (verified against arrow-py/arrow main @ 2224255, 2026-10-26) -->

**Title:** `Arrow.dehumanize` docstring documents `timestring`, but the parameter is `input_string`

**Body:**

> NOTE: already covered by the open PR arrow-py/arrow#1355 (2026-09-15), which makes exactly this change. **Do not file. Kept for the record only.**

`arrow/arrow.py:1349` has `:param timestring:`, but the signature at `:1344` is `dehumanize(self, input_string, locale="en_us")`. `dehumanize(timestring=...)` raises `TypeError` (reproduced).

Fix: `:param input_string:`.

Still present on master @ 2224255 (2026-10-26).

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

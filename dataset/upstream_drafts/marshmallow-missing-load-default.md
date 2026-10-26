<!-- DRAFT ONLY. Not filed. Target: https://github.com/marshmallow-code/marshmallow/issues (verified against marshmallow-code/marshmallow main @ b762ea2, 2026-10-26) -->

**Title:** docs/top_level.rst: `missing` falls back to `load_default`, not `default`

**Body:**

`docs/top_level.rst:12-14` (the `marshmallow.missing` entry):

> If the field's value is not required, its ``default`` value is used.

Fields no longer have a `default` parameter. It was replaced by `load_default`/`dump_default`, and `fields.Int(default=5)` now raises `TypeError: Field.__init__() got an unexpected keyword argument 'default'` (reproduced). Deserialization uses `load_default` (`src/marshmallow/fields.py:380-381`).

Suggested one-line fix:

```diff
-   its ``default`` value is used.
+   its ``load_default`` value is used.
```

Still present on dev @ b762ea2 (2026-10-26). No existing issue or PR found (#2040 is related but closed and about other wording).

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

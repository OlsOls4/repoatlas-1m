<!-- DRAFT ONLY. Not filed. Target: https://github.com/python-attrs/cattrs/issues (verified against python-attrs/cattrs main @ 7a24f77, 2026-10-26) -->

**Title:** docs/customizing.md shows a non-existent `ForbiddenExtraKeyError`

**Body:**

The `forbid_extra_keys` example in `docs/customizing.md:279` shows:

```
ForbiddenExtraKeyError: Extra fields in constructor for TestClass: nummber
```

There is no `ForbiddenExtraKeyError`. The class is `ForbiddenExtraKeysError` (`src/cattrs/errors.py:118`), and `hasattr(cattrs.errors, "ForbiddenExtraKeyError")` is `False`. So a user who writes `except cattrs.errors.ForbiddenExtraKeyError` gets an `AttributeError`. Also, with the default `detailed_validation=True`, this example actually raises `ClassValidationError` wrapping a `ForbiddenExtraKeysError` (reproduced).

Suggested one-line fix:

```diff
-ForbiddenExtraKeyError: Extra fields in constructor for TestClass: nummber
+ForbiddenExtraKeysError: Extra fields in constructor for TestClass: nummber
```

(Optionally note that, with detailed validation on, it arrives inside a `ClassValidationError`.)

Still present on main @ 7a24f77 (2026-10-26). No existing issue or PR found.

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

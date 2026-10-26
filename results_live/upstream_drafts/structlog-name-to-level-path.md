<!-- DRAFT ONLY. Not filed. Target: https://github.com/hynek/structlog/issues (verified against hynek/structlog main @ 19c4f21, 2026-10-26) -->

**Title:** Docs point to `_NAME_TO_LEVEL` at paths that don't exist

**Body:**

Two places tell users where the level-name mapping lives, and neither path works:

- `docs/standard-library.md:117`: "The mapping of names to numbers is in `structlog.stdlib._NAME_TO_LEVEL`." But `hasattr(structlog.stdlib, "_NAME_TO_LEVEL")` is `False`.
- `src/structlog/stdlib.py:861-862` (docstring): "``structlog.stdlib._log_levels._NAME_TO_LEVEL``". `structlog.stdlib` is a module with no `_log_levels` attribute.

The mapping is `structlog._log_levels.NAME_TO_LEVEL` (`src/structlog/_log_levels.py:27`, with the alias `_NAME_TO_LEVEL` at :46). `stdlib.py:39` imports it as `NAME_TO_LEVEL`.

Suggested fix (both places):

```diff
-The mapping of names to numbers is in `structlog.stdlib._NAME_TO_LEVEL`.
+The mapping of names to numbers is in `structlog._log_levels.NAME_TO_LEVEL`.
```

Still present on main @ 19c4f21 (2026-10-26). No existing issue or PR found.

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

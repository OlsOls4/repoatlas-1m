<!-- DRAFT ONLY. Not filed. Target: https://github.com/pallets/click/issues (verified against pallets/click main @ 2247b35, 2026-10-26) -->

**Title:** docs/exceptions.md refers to a non-existent `FileType` class

**Body:**

`docs/exceptions.md:109-110`:

> {exc}`FileError` this is an error that is raised by the {class}`FileType` if Click encounters issues opening the file.

Click has no `FileType` class. The parameter type is `click.File` (`src/click/types.py:915`), so the cross-reference does not resolve. (`FileError` is actually raised from `LazyFile.open`, `src/click/utils.py:165-167`. Eager `File.convert` reports through `self.fail` and raises `BadParameter`.)

Suggested one-line fix:

```diff
-  {class}`FileType` if Click encounters issues opening the file.
+  {class}`File` type if Click encounters issues opening the file.
```

Still present on main @ 2247b35 (2026-10-26). No existing issue or PR found.

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

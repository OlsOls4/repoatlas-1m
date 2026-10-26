<!-- DRAFT ONLY. Not filed. Target: https://github.com/python-attrs/cattrs/issues (verified against python-attrs/cattrs main @ 7a24f77, 2026-10-26) -->

**Title:** `get_structure_hook`/`get_unstructure_hook` docstrings document `cache`, but the parameter is `cache_result`

**Body:**

`src/cattrs/converters.py`:

- `get_unstructure_hook(self, type, cache_result=True)` (:492). Its docstring at :502 says `:param cache: Whether to cache the returned hook.`
- `get_structure_hook(self, type, cache_result=True)` (:641). Its docstring at :650 says the same.

Following the docs raises:

```
TypeError: BaseConverter.get_structure_hook() got an unexpected keyword argument 'cache'
```

(reproduced for both methods)

Suggested fix (both docstrings):

```diff
-        :param cache: Whether to cache the returned hook.
+        :param cache_result: Whether to cache the returned hook.
```

Still present on main @ 7a24f77 (2026-10-26). No existing issue or PR found.

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

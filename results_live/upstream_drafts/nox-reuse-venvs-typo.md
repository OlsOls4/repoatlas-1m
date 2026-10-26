<!-- DRAFT ONLY. Not filed. Target: https://github.com/wntrblm/nox/issues (verified against wntrblm/nox main @ afa3983, 2026-10-26) -->

**Title:** docs/usage.rst: `nox.options.reuse_venvs` should be `reuse_venv`

**Body:**

`docs/usage.rst:219`:

> Similarly you can override ``nox.options.reuse_venvs`` from the Noxfile via the command line by using ``--reuse-venv=yes|no|always|never``.

The option is `reuse_venv` (`nox/_options.py:333`, and correctly documented in `docs/config.rst:578`). Setting the documented name in a noxfile fails:

```
AttributeError: 'NoxfileOptions' object has no attribute 'reuse_venvs'
```

(reproduced)

Suggested one-line fix:

```diff
-Similarly you can override ``nox.options.reuse_venvs`` from the Noxfile
+Similarly you can override ``nox.options.reuse_venv`` from the Noxfile
```

Still present on main @ afa3983 (2026-10-26). No existing issue or PR found (#488 is unrelated).

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

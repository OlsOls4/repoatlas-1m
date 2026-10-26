<!-- DRAFT ONLY. Not filed. Target: https://github.com/encode/httpx/issues (verified against encode/httpx main @ b5addb6, 2026-10-26) -->

**Title:** docs/advanced/transports.md: example uses non-existent `httpx.Mounts`

**Body:**

> NOTE: already covered by the open PR encode/httpx#3774 ("docs: fix two broken examples in transports.md", 2026-02-23). **Do not file. Kept for the record only.**

`docs/advanced/transports.md:190-193` builds `httpx.Mounts({...})`, but `httpx` has no `Mounts` attribute, so the example raises `AttributeError`. The dict literal is also missing a comma. Mounting is done with `httpx.Client(mounts={...})` (`httpx/_client.py:652`).

Suggested fix: `client = httpx.Client(mounts={...})` with the missing comma added.

Still present on master @ b5addb6 (2026-10-26).

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

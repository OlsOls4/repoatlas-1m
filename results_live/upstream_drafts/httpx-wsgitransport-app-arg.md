<!-- DRAFT ONLY. Not filed. Target: https://github.com/encode/httpx/issues (verified against encode/httpx main @ b5addb6, 2026-10-26) -->

**Title:** `WSGITransport` docstring still recommends the removed `Client(app=...)` shortcut

**Body:**

The class docstring at `httpx/_transports/wsgi.py:47-51` says:

> The simplest way to use this functionality is to use the `app` argument.
> ```
> client = httpx.Client(app=app)
> ```

The `app` argument was removed in 0.28 (CHANGELOG deprecation; #3050). `Client.__init__` (`httpx/_client.py`) no longer accepts it, so the example raises:

```
TypeError: Client.__init__() got an unexpected keyword argument 'app'
```

(reproduced on httpx 0.28.1)

Suggested fix: replace the shortcut with the explicit transport form that the rest of the docstring already shows:

```diff
-    The simplest way to use this functionality is to use the `app` argument.
-
-    ```
-    client = httpx.Client(app=app)
-    ```
+    ```
+    transport = httpx.WSGITransport(app=app)
+    client = httpx.Client(transport=transport)
+    ```
```

Still present on master @ b5addb6 (2026-10-26). No existing issue or PR found.

---
_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

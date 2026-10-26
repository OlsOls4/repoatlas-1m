<!-- DRAFT ONLY. Not filed. Target: https://github.com/Kludex/starlette/issues (verified against main @ 8aa828c, 2026-10-24) -->

**Title:** Docs: `websocket.receive_json(data, mode="binary")` example passes a nonexistent `data` argument

**Body:**

`docs/websockets.md:74` says:

> Use `websocket.receive_json(data, mode="binary")` to receive JSON over binary data frames.

But `receive_json` takes no `data` parameter (`starlette/websockets.py:136`):

```python
async def receive_json(self, mode: str = "text") -> Any:
```

Following the docs gives `TypeError: WebSocket.receive_json() got multiple values for argument 'mode'`. The line looks like it was copied from the `send_json(data, mode="binary")` sentence a few lines above (`docs/websockets.md:63`), where `data` is correct.

Suggested one-line fix in `docs/websockets.md:74`:

```diff
-Use `websocket.receive_json(data, mode="binary")` to receive JSON over binary data frames.
+Use `websocket.receive_json(mode="binary")` to receive JSON over binary data frames.
```

Still present on `main` at 8aa828c. #3580 recently corrected other WebSocket signatures in this file but didn't touch this line.

_Found by RepoAtlas-1M (a docs-vs-code drift checker) running the Beam model over a packed snapshot of the repo, then verified by hand against the source._

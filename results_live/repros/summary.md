# DocDrift tutorial runner: repro results

| Finding | Hand label | Repro status | Reason | Observed | Predicted | Model verdict |
|---|---|---|---|---|---|---|
| arrow-400000:DD-1 | true | reproduced | expected_exception | TypeError | TypeError | likely_true |
| arrow-400000:DD-2 | false | reproduced | expected_exception | AssertionError | AssertionError | likely_true |
| arrow-400000:DD-3 | false | reproduced | expected_exception | ValueError | ValueError | unclear |
| arrow-400000:DD-4 | false | reproduced | expected_exception | AssertionError | AssertionError | likely_true |
| cattrs-400000:DD-1 | true | reproduced | expected_exception | ImportError | ImportError | likely_true |
| cattrs-400000:DD-2 | true | reproduced | expected_exception | TypeError | TypeError | likely_true |
| cattrs-400000:DD-3 | true | reproduced | expected_exception | TypeError | TypeError | likely_true |
| click-400000:DD-1 | true | reproduced | expected_exception | AttributeError | AttributeError | unclear |
| hatch-400000:DD-1 | unclear | could_not_run | lint | - | none | unclear |
| httpx-400000:DD-1 | true | reproduced | expected_exception | AttributeError | AttributeError | likely_true |
| httpx-400000:DD-2 | true | reproduced | expected_exception | TypeError | TypeError | likely_true |
| jinja-400000:DD-1 | unclear | reproduced | expected_exception | AssertionError | AssertionError | likely_true |
| marshmallow-400000:DD-1 | false | not_reproduced | ran_ok | - | none | likely_false |
| marshmallow-400000:DD-2 | true | could_not_run | failed_outside_doc_literal | TypeError | AssertionError | likely_true |
| nox-400000:DD-1 | true | reproduced | expected_exception | AttributeError | AttributeError | unclear |
| poetry-400000:DD-1 | false | could_not_run | timeout | - | AssertionError | likely_true |
| pydantic-settings-400000:DD-1 | false | reproduced | expected_exception | AssertionError | AssertionError | likely_true |
| starlette-400000:DD-1 | true | reproduced | expected_exception | TypeError | TypeError | likely_true |
| structlog-400000:DD-1 | false | reproduced | expected_exception | AssertionError | AssertionError | likely_true |
| structlog-400000:DD-2 | true | reproduced | expected_exception | AttributeError | AttributeError | likely_true |
| werkzeug-400000:DD-1 | false | reproduced | expected_exception | AssertionError | AssertionError | likely_true |

## Summary

```json
{
  "findings": 21,
  "hand_true": 11,
  "hand_false_or_unclear": 10,
  "true_by_status": {
    "reproduced": 10,
    "not_reproduced": 0,
    "could_not_run": 1
  },
  "false_or_unclear_by_status": {
    "reproduced": 7,
    "not_reproduced": 1,
    "could_not_run": 2
  },
  "precision_without_filter": 0.5238,
  "kept_with_filter": 17,
  "kept_true_with_filter": 10,
  "precision_with_filter": 0.5882,
  "recall_of_true_with_filter": 0.9091,
  "reproduced_via_assertion": 6,
  "strict_filter": "reproduced with an interface error (TypeError/AttributeError/ImportError/NameError)",
  "kept_with_strict_filter": 10,
  "kept_true_with_strict_filter": 10,
  "precision_with_strict_filter": 1.0,
  "recall_of_true_with_strict_filter": 0.9091,
  "model_says_false": {
    "hand_true": 0,
    "hand_false_or_unclear": 1
  }
}
```

## Beam usage (this run)

```json
{
  "prompt_tokens": 7446,
  "completion_tokens": 976,
  "calls": 3,
  "cached_calls": 23,
  "http_429": 0,
  "total_live_tokens": 8422,
  "errors": []
}
```

## Beam usage across all runs
- Development call (relative-venv-path bug, wasted): 6,355 tokens
- Starlette check calls: 6,942 tokens
- First full run of the 21 findings: 82,107 tokens (24 calls, 0 HTTP 429)
- Rerun after tightening the marker lint (23 responses from cache, 3 live retries): 8,422 tokens
- **Total: 103,826 tokens** (budget 2,000,000). The strict-filter tier was defined after seeing the first run's results, so treat it as a hypothesis to confirm on new findings.

# DocDrift demo: voiceover narration (v4, optional)

Voice: Kokoro-82M (Apache-2.0), voice `af_heart`, speed 1.1, run locally through `kokoro-onnx` 0.6.1 (MIT) with its bundled espeak-ng phonemiser. No cloud, no sign-up, no spend.
Every number below matches the burned-in captions (`work/captions_voice.srt`). The spoken text uses phonetic spellings where needed (column 'TTS input').
Words: 192 · video 93.5 s · mix −16 LUFS integrated, true peak −1.5 dBTP.

| # | Start (s) | End (s) | Shot | Script | TTS input |
|---|---|---|---|---|---|
| 1 | 0.3 | 5.0 | Hero → drift card | DocDrift gives Beam a whole Python library in one call, to find docs that lie. | DocDrift gives Beam a whole Python library in one call, to find docs that lie. |
| 2 | 5.6 | 12.1 | Hero → drift card | Starlette's docs say: call receive JSON with mode binary. Run it as written, and it crashes with a TypeError. | Starlette's docs say: call receive Jason, with mode binary. Run it as written, and it crashes with a type error. |
| 3 | 13.2 | 23.7 | starlette run (player) | One Beam call, the whole library: 394,577 prompt tokens. 3 candidates; 2 kept as real drift, 1 rejected. | One Beam call, the whole library: three hundred ninety-four thousand, five hundred seventy-seven prompt tokens. Three candidates. Two kept as real drift, one rejected. |
| 4 | 24.2 | 29.4 | PR #3746 page | A fix is filed upstream: pull request 3746, open, not merged. | A fix is filed upstream: pull request thirty-seven forty-six. Open, not merged. |
| 5 | 29.9 | 38.0 | Bugs wall | Every card shows what the docs say, what the code says, and what running it gives: 34 real docs bugs in 11 of 12 libraries. | Every card shows what the docs say, what the code says, and what running it gives: thirty-four real docs bugs, in eleven of twelve libraries. |
| 6 | 40.8 | 59.6 | Why 1M bars | Does the 1M-token context help? Accuracy is about the same. But grounding is better: the right cross-file line 25 of 30 times, versus 19 at matched cost. Off-file evidence: 11 of 13, versus 6. p = 0.070: suggestive, not proven. | Does the one million token context help? Accuracy is about the same. But grounding is better: the right cross-file line twenty-five of thirty times, versus nineteen at matched cost. Off-file evidence: eleven of thirteen, versus six. P equals zero point zero seven zero: suggestive, not proven. |
| 7 | 60.4 | 69.6 | Benchmark + Repros | On the benchmark: 34 of 45 known drifts found; 30 crash exactly as the docs are written. 32 of the 34 bugs ship a script. | On the benchmark: thirty-four of forty-five known drifts found; thirty crash exactly as the docs are written. Thirty-two of the thirty-four bugs ship a script. |
| 8 | 71.8 | 75.7 | tomlkit CLI run | Then a fresh run on tomlkit, a library DocDrift had never seen. | Then a fresh run on toml kit, a library DocDrift had never seen. |
| 9 | 78.0 | 84.7 | tomlkit report (held) | 2 findings: 1 verified version drift, and 1 arguable missing-imports NameError, in 96 seconds. | Two findings: one verified version drift, and one arguable missing-imports name error, in ninety-six seconds. |
| 10 | 85.6 | 89.4 | Run it tab → end card | Run it on your repo with docdrift run, using a free Ollama key. | Run it on your repo with doc drift run, using a free Oh-llama key. |

## Script (plain)

DocDrift gives Beam a whole Python library in one call, to find docs that lie.
Starlette's docs say: call receive JSON with mode binary. Run it as written, and it crashes with a TypeError.
One Beam call, the whole library: 394,577 prompt tokens. 3 candidates; 2 kept as real drift, 1 rejected.
A fix is filed upstream: pull request 3746, open, not merged.
Every card shows what the docs say, what the code says, and what running it gives: 34 real docs bugs in 11 of 12 libraries.
Does the 1M-token context help? Accuracy is about the same. But grounding is better: the right cross-file line 25 of 30 times, versus 19 at matched cost. Off-file evidence: 11 of 13, versus 6. p = 0.070: suggestive, not proven.
On the benchmark: 34 of 45 known drifts found; 30 crash exactly as the docs are written. 32 of the 34 bugs ship a script.
Then a fresh run on tomlkit, a library DocDrift had never seen.
2 findings: 1 verified version drift, and 1 arguable missing-imports NameError, in 96 seconds.
Run it on your repo with docdrift run, using a free Ollama key.

| Metric | Whole-repo (reused hybrid) | Local-file only | Whole-repo, subset (27) | Local, subset (27) | Whole-repo rerun, subset (27) |
|---|---|---|---|---|---|
| True candidates kept | 32/32 | 32/32 | 13/13 | 13/13 | 13/13 |
| False/unclear candidates rejected | 15/24 | 15/24 | 9/14 | 12/14 | 10/14 |
| Precision (kept that are true) | 0.78 (32/41) | 0.78 (32/41) | 0.722 (13/18) | 0.867 (13/15) | 0.765 (13/17) |
| Verdict accuracy | 0.839 | 0.839 | 0.815 | 0.926 | 0.852 |
| Citation hits gold file:line (gradable) | 41/52 | 34/52 | 19/26 | 19/26 | 22/26 |
| Right verdict + gold citation | 39/52 | 33/52 | 17/26 | 19/26 | 20/26 |
| Citation verified (quote matches source) | 54/56 | 52/56 | 25/27 | 26/27 | 27/27 |
| Cross-file cases: right verdict | 26/30 | 26/30 | 12/13 | 12/13 | 12/13 |
| Cross-file cases: right verdict + citation | 25/30 | 14/30 | 12/13 | 8/13 | 12/13 |
| Evidence outside local context: right verdict | 12/13 | 12/13 | 4/4 | 4/4 | 4/4 |
| Evidence outside local context: right verdict + citation | 11/13 | 0/13 | 4/4 | 0/4 | 4/4 |
| Beam tokens | 4,022,532 (11 calls; 4,331,995 as spent incl. a cattrs re-send) | 830,527 (56 calls; 848,654 as spent incl. 1 re-send) | — | — | 1,099,815 |

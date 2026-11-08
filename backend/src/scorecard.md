# Warrant scorecard

Scenarios and labels are our own (n=36). Classifier: offline keyword stub (NOT the LLM; dry run only).


## Split: report

| Arbiter | Cases | Agrees with label | Unsafe refunds/accepts | Guessed when it should hand off |
|---|---|---|---|---|
| rules-only | 24 | 21/24 | 0 | 0/3 |
| hybrid (keyword stub) | 24 | 24/24 | 0 | 0/3 |

## Split: tune

| Arbiter | Cases | Agrees with label | Unsafe refunds/accepts | Guessed when it should hand off |
|---|---|---|---|---|
| rules-only | 12 | 11/12 | 0 | 0/2 |
| hybrid (keyword stub) | 12 | 12/12 | 0 | 0/2 |

## Split: all

| Arbiter | Cases | Agrees with label | Unsafe refunds/accepts | Guessed when it should hand off |
|---|---|---|---|---|
| rules-only | 36 | 32/36 | 0 | 0/5 |
| hybrid (keyword stub) | 36 | 36/36 | 0 | 0/5 |

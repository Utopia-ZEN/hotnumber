# Evidence-First Lotto Experiment

This experiment tests whether historical draw data contains a small,
repeatable departure from the uniform Lotto 6/45 baseline. It does not assume
that a historical pattern is predictive.

## Protocol

1. Fit only on draws earlier than the target draw.
2. Shrink number inclusion rates toward the uniform `6/45` rate.
3. Normalize the model over all `C(45, 6) = 8,145,060` combinations.
4. Compare average log loss against the uniform model.
5. Generate five games as a portfolio, preferring unused numbers before
   progressively relaxing overlap constraints.
6. Seal future predictions in an append-only SHA-256 hash-chain ledger.
7. Append results as new evaluation records; never edit predictions.

The primary success criterion is lower out-of-sample log loss than the uniform
baseline. Prize hits are reported, but they are too sparse to be the sole model
selection criterion.

The report includes a 95% interval for the mean log-loss improvement. A model
is not treated as evidence of signal when that interval crosses zero.

## Commands

Run a strict walk-forward test over all locally available rounds:

```powershell
python -B -m PickNumber.order_experiment backtest --start-round 1 --games 5
```

Seal five games for the next locally unknown round:

```powershell
python -B -m PickNumber.order_experiment predict --start-round 1 --games 5
```

After the target draw has been collected, append its immutable evaluation:

```powershell
python -B -m PickNumber.order_experiment settle --round 1237
```

Verify the ledger chain:

```powershell
python -B -m PickNumber.order_experiment verify-ledger
```

Run the weekly owner-pick cycle:

```powershell
python -B -m PickNumber.order_experiment owner-cycle --start-round 1
```

The cycle settles the latest sealed owner set when its draw exists, then seals
five order-model games and five reproducible uniform-random games for the next
round. The ten games are published to the existing `star.lotto` path consumed
by the web UI. Before sealing the next set, it also runs the strict walk-forward
evaluation over every locally available round through the latest completed
round and saves `walk_forward_report.json`. The new prediction record retains
the report digest and summary so each update can be audited against the exact
data interval used. A negative report does not promote the model or replace
the owner picks.

Outputs are written under `outputs/order_experiment/`.

## Physical Context Roadmap

Historical numbers alone do not preserve the physical initial state of a draw.
The next research phase should collect source-backed context fields such as
machine identifier, ball-set identifier, replacement dates, ordered extraction
sequence, and video-derived timing. A context-aware model should only be added
after coverage and provenance checks pass, and it must use the same sealed
walk-forward protocol.

Context records must conform to `draw_context.schema.json`. Unknown values stay
`null`; they must never be inferred from winning numbers. Every record requires
a source URL and retrieval timestamp.

Official-video sources and manual observations are managed with:

```powershell
python -B -m PickNumber.draw_context_collection discover --min-round 1208
python -B -m PickNumber.draw_context_collection annotate --round 1237 `
  --order "10 40 20 34 37 23" --bonus 36 --result-offset 325
python -B -m PickNumber.draw_context_collection import-batch `
  --batch lotto_data/draw_context/collection_batch_002.json
python -B -m PickNumber.draw_context_collection audit --minimum-sample 100
```

Discovery verifies the YouTube title and the `동행복권` channel through
YouTube oEmbed metadata. Discovery never turns a video into a training row.
An observation becomes verified only after manual video review, and its six
ordered values plus bonus must match the canonical draw file. Machine and ball
set identifiers remain `null` unless the video image or narration identifies
them directly.

The timestamp is evidence-specific. For example, the 1237 video at 05:25 shows
the completed result rack, so it is stored as `result_board_offset_seconds`,
not as a machine-start timestamp.

As of the fourth preselected collection batch, the repository had 219 verified
official-channel extraction sequences. The channel's own search index appeared
to stop at round 1055, but exact general YouTube searches located older videos
on the same verified `동행복권` channel. Rounds 988 through 1054 that were not
already present were therefore reviewed from the official videos and imported
only after their extracted sets and bonus balls matched the canonical draw
files. The current exact-search pass did not locate official-channel videos for
round 987 or earlier.

Batch 005 preregistered the 81 consecutive rounds from 987 through 907 before
video-content review. When no official-channel source was available, a
third-party reupload was admitted only if the visible round label, continuous
six-ball extraction, completed winning set, and bonus ball all matched the
canonical draw data. The uploader and source URL remain attached to every row,
and `source_type` distinguishes these records from official-channel evidence.
Seventy-nine reuploads passed all checks. Rounds 974 and 910 showed only result
or analysis screens, so they are recorded as rejected batch rows and were not
imported.

Batch 006 preregistered rounds 906 and 905. An initial timeline beginning at
the start of each upload covered only the introduction and was insufficient to
classify the videos. A corrected timeline beginning at four minutes exposed
the continuous draw footage. The reviewed extraction orders were
`28, 5, 31, 2, 14, 32` with bonus `20` for round 906 and
`4, 40, 38, 16, 3, 27` with bonus `20` for round 905. Both completed sets and
bonus balls match the canonical draw files, so both observations were imported
as verified third-party reuploads. The repository now has 300 verified
extraction sequences: 219 from the official channel and 81 from third-party
reuploads. Later preregistered batches remain pending and have not contributed
observations.

Batch 011 added two manually reviewed LottoLab reuploads for rounds 1065 and
1068, bringing the verified total to 302 sequences. Their visible round labels,
continuous six-ball extraction, completed winning sets, and bonus balls matched
the canonical draw files. The 05:25 timestamp convention applies only to
official-channel videos; these reuploads therefore retain the observed order
without an assumed fixed timestamp. These two rows extend collection evidence
but do not reopen the frozen 300-record checkpoint.

A four-video identifiability sample found a numbered selection display in the
wide shot, but the official metadata reviewed so far does not define whether
that number identifies a machine, a ball set, or another control. The sample is
stored in `lotto_data/draw_context/physical_context_identifiability_review.json`.
Machine and ball-set fields therefore remain `null`.

## Milestones And Gates

### Phase 1: Reproducible Baseline (complete)

- Canonical draw loader and data digest
- Uniform and regularized Bayesian combination probabilities
- Strict walk-forward comparison with a 95% improvement interval
- Diversified five-game portfolio
- Append-only prediction and evaluation ledger

Gate: tests pass, draw history is contiguous, and the ledger verifies.

### Phase 2: Context Collection

- Collect machine, ball-set, extraction-order, and source provenance fields.
- Produce coverage and missingness reports before fitting a model.
- Keep unknown values as missing; do not backfill them from outcomes.

Gate: at least 100 source-backed draws per tested context category and no
target-derived fields.

The gate is enforced per category: 100 verified ordered sequences for an
order-aware model, 100 records for each machine or ball-set value, and 100 for
each tested machine/ball-set pair. A smaller sample remains collection data and
cannot enable a conditional model.

### Phase 3: Conditional Models

- Compare machine-only, ball-set-only, order-only, and combined hierarchical
  models.
- Select hyperparameters inside an earlier validation window.
- Reserve the newest contiguous block as a one-time untouched test window.

Gate: positive log-loss improvement whose 95% interval excludes zero on the
untouched window. Otherwise the model is rejected.

Once the ordered-sequence gate reaches 100 verified draws, run the isolated
order-condition experiment with:

```powershell
python -B -m PickNumber.context_order_model
```

The first 60 observations train the initial model, the next 20 select only the
prior strength, and the newest 20 form an untouched test. The report is written
to `outputs/order_experiment/context_order_report.json`. A failed test remains
an explicit rejection and is not connected to owner-pick generation.

The first 100-record experiment was rejected: mean test log-loss improvement
was -0.03820695 and its 95% interval was [-0.09477040, 0.01835649]. Additional
records are collection evidence only until the preregistered 200-record
checkpoint; the rejected model is not repeatedly retested as data trickles in.

At the 200-record checkpoint, the original 100-record model and selected prior
were frozen. Collection batches 002 and 003 supplied a separate 100-record
acquisition holdout; none of those observations were used for fitting or
retuning. Run the checkpoint with:

```powershell
python -B -m PickNumber.context_order_model `
  --frozen-development-report outputs\order_experiment\context_order_report.json `
  --holdout-batch lotto_data\draw_context\collection_batch_002.json `
  --holdout-batch lotto_data\draw_context\collection_batch_003.json `
  --output outputs\order_experiment\context_order_checkpoint_200.json
```

The checkpoint was also rejected. Mean holdout log-loss improvement versus
uniform was -0.01977513 with a 95% interval of
[-0.04285002, 0.00329976]. The order-aware model remains disconnected from
owner-pick generation. Machine and ball-set conditional models remain blocked
because their identifiers are still not source-defined.

Batch 004 added 19 collection-only observations after that rejected checkpoint,
batch 005 added 79 strictly reviewed third-party reuploads, and batch 006 added
the two verified observations for rounds 906 and 905. At exactly 300 verified
sequences, the original 100-record development cohort and the prior 100-record
holdout were kept frozen. The new batches supplied a second 100-record
acquisition holdout. Run this checkpoint with:

```powershell
python -B -m PickNumber.context_order_model `
  --frozen-development-report outputs\order_experiment\context_order_report.json `
  --prior-holdout-batch lotto_data\draw_context\collection_batch_002.json `
  --prior-holdout-batch lotto_data\draw_context\collection_batch_003.json `
  --holdout-batch lotto_data\draw_context\collection_batch_004.json `
  --holdout-batch lotto_data\draw_context\collection_batch_005.json `
  --holdout-batch lotto_data\draw_context\collection_batch_006.json `
  --output outputs\order_experiment\context_order_checkpoint_300.json
```

The 300-record checkpoint was rejected. Mean holdout log-loss improvement
versus uniform was -0.00750004 with a 95% interval of
[-0.02816507, 0.01316499]. The interval still crosses zero and the mean is
negative, so the order-aware model remains disconnected from owner-pick
generation.

For inspection only, a rejected-model spectrum can produce five unsealed games
from five fixed prior strengths. The same frozen development and newest
100-record holdout rank two worst, one median, and two best variants. This
post-checkpoint view is marked `experimental_only` and never replaces sealed
owner picks:

```powershell
python -B -m PickNumber.context_order_model `
  --spectrum `
  --frozen-development-report outputs\order_experiment\context_order_report.json `
  --prior-holdout-batch lotto_data\draw_context\collection_batch_002.json `
  --prior-holdout-batch lotto_data\draw_context\collection_batch_003.json `
  --holdout-batch lotto_data\draw_context\collection_batch_004.json `
  --holdout-batch lotto_data\draw_context\collection_batch_005.json `
  --holdout-batch lotto_data\draw_context\collection_batch_006.json
```

### Phase 4: Live Prospective Trial

- Freeze one model version and five-game generation policy.
- Seal each prediction before the draw and append the result afterward.
- Compare against a simultaneously sealed uniform five-game baseline.

Gate: review after 52 future draws. No model changes are allowed inside that
trial; a changed model starts a new trial series.

# Collusion-Watch: Curating and Auditing a Small Monitor for Agent-Market Coordination

> **Preliminary evaluation — updated 16 November 2026.** The source snapshot has
> 112 episodes and the seed-disjoint test set has only four benign episodes.
> The sweep's exported judge-failure counter undercounts unparseable responses.

## Abstract

Multi-agent systems can coordinate through conversation or signals embedded in
market actions, while benign price convergence can look suspicious. We present
Collusion-Watch, an English-language benchmark and monitor pipeline for
simulated double-auction episodes. The monitor ladder compares transcript
rules, a Tiny Aya Fire transcript judge, model-free market signals, and their
combination. We evaluate base and fine-tuned judges on the same 16 seed-held-out
episodes (12 collusive, four benign). Fine-tuning raises M2 collusion-score
AUROC from 0.15 to 0.58, but neither M2 arm flags a collusive episode at its
operating policy; the fine-tuned arm flags none of the 16. The base judge
flags one of 12 harmful and two of four benign episodes, with three
unparseable outputs. M4 flags all 16 episodes for both judge arms, including
all benign examples. The source archive has 112 complete episodes (30 A2, 41
A3, 41 A5), with A2 seed 20 absent; its verified seed-level split contains 78
train, 18 validation, and 16 test examples. The small test set and a corrected
failure count preclude claims of reliable detection, generalization, or
safety-preserving fine-tuning.

## 1. Introduction

An agent-market monitor must distinguish harmful coordination from benign
cooperation and price discovery. Collusion-Watch studies this problem in a
controlled continuous double auction, where sellers can coordinate overtly
(A3) or encode rotation signals in their asks (A5), while A2 honest seller chat
provides a benign comparison.

The project separates three questions: does a monitor rank collusive episodes
above benign ones, does it flag episodes for review, and do interventions
reduce harm without unacceptable benign-market costs? These are not
interchangeable outcomes. A higher AUROC alone does not demonstrate that a
monitor will act correctly at a usable threshold.

This draft follows the organization of the research paper: environment and
threat model, monitor design, experimental protocol, results, then limitations
and discussion. The reported monitor comparison is a small, imbalanced
offline replay and should not be read as a generalization estimate.

## 2. Threat model and environment

The environment is a 15-round simulated double auction with five
Tiny Aya Global sellers and four scripted ZIP buyers. A2 is benign seller
chat, A3 is overt cartel coordination, and A5 is coded bid rotation. Labels
come from the environment's recorded episode truth. Market outcomes are
measured against the competitive-equilibrium benchmark.

The source archive, `aya_market_base_a2prompt-latest`, contains:

| Condition | Episodes | Seeds | Collusive / harmful | Mean collusion index | Mean buyer surplus | Mean efficiency |
|---|---:|---|---:|---:|---:|---:|
| A2 honest chat | 30 | 0-30 except 20 | 0 / 1 | -0.0186 | 1451.15 | 0.7610 |
| A3 overt cartel | 41 | 0-40 | 41 / 41 | 0.9298 | 83.44 | 0.2369 |
| A5 price rotation | 41 | 0-40 | 41 / 41 | 0.9394 | 78.41 | 0.2309 |
| **Total** | **112** | **41 distinct seeds** | **82 / 83** | — | — | — |

The A2 series contains seeds 0-19 and 21-30; seed 20 is absent, not a
malformed episode. All 112 episodes pass the dataset builder's evidence-chain
and metadata checks, and none is skipped. The CSV records zero decision
timeouts. One A2 episode is labeled non-collusive by episode truth but marked
harmful in its outcome metrics; collusion labels and outcome-harm indicators
are therefore reported separately. Every episode used the trusted-entrant
intervention, and no online monitor acted. These economic outcomes are
descriptive outcomes under entrant intervention, not an untreated-market
comparison or a causal estimate of monitor impact.

The 112-row `episodes.csv` matches the complete episode records. The verified
M2 transcript dataset has 112 examples across 41 seed groups: 78 train, 18
validation, and 16 test. The test set contains 12 collusive and 4 competitive
episodes; it is still small and includes only four A2 examples.

## 3. Trusted monitor and data pipeline

The replay evaluates four monitor levels:

- **M1:** transcript and market-rule heuristics.
- **M2:** an LLM judge over the episode evidence.
- **M3:** model-free market verification and coordination signals.
- **M4:** the combined verification, judge, and rule-based monitor.

The two M2 arms use `CohereLabs/tiny-aya-fire` and
`munip/tiny-aya-fire-m2-monitor-sft-41seed-v1`. The sweep pins one model per
arm and replays the same stored trajectories. M1 and M3 are judge-independent
references. A `HOLD` or `CONSTRAIN` counts as a flagged episode in the sweep;
this is not the same as a correct collusion verdict or a successful
intervention.

The intended dataset workflow uses CuratorKIT for schema/provenance checks
and export, SafeTune for plain supervised fine-tuning, and AuditKIT-compatible
metrics plus the repository's replay evaluator. Targets are based on episode
truth; rationale text in the earlier dataset version was templated from the
label and is not evidence-grounded.

The accompanying dataset manifest records 112 examples split by seed into 78
train, 18 validation, and 16 test examples. The CuratorKIT manifest records
78 exported training examples and zero rejections. The Colab notebook specifies
Plain SFT on that train-only export for one epoch with batch size one. The
sweep identifies the fine-tuned judge as
`munip/tiny-aya-fire-m2-monitor-sft-41seed-v1`, but the supplied artifacts do
not include a training log or immutable model revision linking that exact
checkpoint to the recipe. No safety-hardening or safety-preservation result is
claimed.

## 4. Experimental protocol

The sweep output, `aya_m2_monitor_41seed30_comparison_v1`, scores the same
16 seed-disjoint test episodes for each monitor arm:

| Evaluation subset | Episodes | Label |
|---|---:|---|
| A2 honest chat, seeds 0, 12, 15, 29 | 4 | Benign |
| A3 overt cartel, seeds 0, 12, 15, 20, 29, 36 | 6 | Collusive |
| A5 price rotation, seeds 0, 12, 15, 20, 29, 36 | 6 | Collusive |
| **Total** | **16** | **12 collusive, 4 benign** |

The test seeds are disjoint from the training and validation seeds. A2 seed
20 is absent and the A2 series ends at seed 30, so only four A2 episodes
appear in the six held-out seed groups. A5 is represented in training and
test; this is not a held-out-mechanism evaluation. The replay archive includes
96 per-monitor decisions (16 examples for each of M1, M2-base, M2-SFT, M3,
M4-base, and M4-SFT).

The sweep reports AUROC and bootstrap 95% intervals against the instructed
collusion label, recall at a nominal 10% false-positive rate, and observed
harmful/benign flag rates. These episode-level estimates are descriptive;
four benign examples are not enough to establish a stable operating point.

## 5. Results

### Monitor comparison

| Monitor | Judge | Collusion AUROC (reported 95% CI) | Recall at 10% FPR | Harmful episodes flagged | Benign episodes flagged |
|---|---|---:|---:|---:|---:|
| M1 | Rules | 0.75 [0.62, 0.88] | 0.50 | 100% (12/12) | 0% (0/4) |
| M2 | Base Tiny Aya Fire | 0.15 [0.00, 0.31] | 0.00 | 8% (1/12) | 50% (2/4) |
| M2 | Fine-tuned Tiny Aya Fire | 0.58 [0.22, 0.79] | 0.00 | 0% (0/12) | 0% (0/4) |
| M3 | Model-free | 0.38 [0.07, 0.67] | 0.00 | 100% (12/12) | 100% (4/4) |
| M4 | Base Tiny Aya Fire | 0.27 [0.00, 0.57] | 0.00 | 100% (12/12) | 100% (4/4) |
| M4 | Fine-tuned Tiny Aya Fire | 0.38 [0.07, 0.67] | 0.00 | 100% (12/12) | 100% (4/4) |

Fine-tuning improves M2 ranking AUROC on this test set (0.15 to 0.58), but
does not improve observed collusion detection at the action policy: the
fine-tuned judge flags none of the 12 harmful episodes. It also does not flag
any of the four benign episodes, but that apparent specificity is based on a
very small negative set. The base judge flags one harmful and two benign
episodes. M3 and both M4 arms flag every episode, so adding the judge does not
make the combined policy selective in this test. None of these results
establishes a reliable threshold or an improvement in intervention
effectiveness.

### Output parsing and fail-open behavior

The exported summary reports zero judge failures, but the per-episode
`reasons` field contains three `unparseable judge output` responses for the
base judge, on two A2 episodes and one A3 episode. The same three failures
appear in M2 and M4, because both monitors use the judge. The SFT arm has no
such failures. A corrected offline aggregation of the saved decisions counts
3/16 failures in each base-judge monitor arm; it does not rerun the model.
The repository counter fix now recognizes unparseable output reasons as
failures. The archive does not include full raw judge responses, so a complete
schema-validity audit is still unavailable.

### Interpretation

The results support only a narrow observation: on this 16-episode test set,
the fine-tuned M2 scores rank collusive examples above benign ones more often
than the base M2 scores do. The fine-tuned arm nevertheless flags none of the
collusive examples. It does not show reliable harm detection, generalization
to diverse benign markets, or improvement to the combined monitor. Per-seed
and causal claims are not justified.

## 6. Discussion

This pilot illustrates why monitor evaluation needs both score-based metrics
and action-level outcomes. AUROC improved for the fine-tuned M2 judge, but its
action policy flagged no collusive test episode. Conversely, a fail-closed
parser created holds on two benign A2 examples; those failures were omitted
from the original summary counter. A larger, balanced test set and a
reproducible raw-response parse audit are needed before selecting a threshold.

Next, add benign A2 seeds (including the missing seed 20 if feasible), retain
a seed-disjoint test set, and evaluate on a held-out coordination mechanism.
Online intervention, utility, and consumer-surplus effects require paired
episodes with and without intervention; this offline sweep cannot establish
those effects.

## Limitations and responsible release

- The environment is synthetic, English-only, and limited to three
  conditions. It is not evidence of real-world collusion or behavior in
  deployed markets.
- The source archive is imbalanced (30 A2 versus 41 each for A3 and A5), with
  the A2 seed-20 episode missing. The current test split contains only four
  competitive examples.
- A5 appears in the training data; no held-out-scheme result is available.
- The curated train export has 78 examples, but an immutable model revision
  and training log linking the swept checkpoint to the notebook recipe are
  not included.
- No refusal, over-refusal, multilingual-retention, or safety-hardening
  evaluation is available. Do not claim safety-preserving fine-tuning or
  Track 2b #5 on these results.
- The sweep summary's judge-failure column is incorrect: it reports zero
  despite three unparseable base-judge responses per judge-using monitor arm.
  Use the corrected aggregation of the saved decisions and preserve the
  original archive for audit.
- The project owner has confirmed permission to release the selected logs and
  model weights. Verify the dataset license and each model's terms, and exclude
  credentials, private monitor keys/anchors, and unreviewed raw captures.

## Reproducibility and artifacts

The supplied artifacts include the 112-example dataset manifest, the
78-example CuratorKIT export, and the 16-episode sweep decisions. The sweep's
scores and action counts were checked against those decisions; the judge
failure counts were recalculated from `reasons` because the exported counter
is stale. Preserve the sweep archive and report both the original counter
field and the corrected failure count. Confirm dataset license and model
terms before finalizing public Hugging Face links.

## References and model terms

- [Tiny Aya Global](https://huggingface.co/CohereLabs/tiny-aya-global)
- [Tiny Aya Fire](https://huggingface.co/CohereLabs/tiny-aya-fire)
- Fine-tuned judge evaluated in this sweep:
  [munip/tiny-aya-fire-m2-monitor-sft-41seed-v1](https://huggingface.co/munip/tiny-aya-fire-m2-monitor-sft-41seed-v1)

Verify each model card's exact license and acceptable-use terms before
publication. Do not rehost base model weights.

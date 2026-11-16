---
title: Collusion-Watch
emoji: 🛡️
colorFrom: blue
colorTo: purple
sdk: static
app_file: index.html
pinned: false
---

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

## Lexsi track and problem-statement coverage

This release is closest to Track 2a, statement 2 (a labeled, domain-specific
evaluation set). Its 15-round episodes are multi-turn traces, but the reported
analysis is episode-level rather than a turn-by-turn audit. It does not cover
Track 2a, statement 4: all data and evaluations are English-only. It also
does not demonstrate Track 2b, statement 5: the training run is plain SFT,
with no SafeGrad/hardening comparison, refusal or over-refusal benchmark, or
safety-retention result. These are explicit gaps, not completed contributions.

The code pipeline uses CuratorKIT for the 78-example train-only export and
SafeTune's `PlainSFTTrainer` for the plain-SFT path. The repository includes
an AuditKIT adapter, but the reported sweep was produced by the project's
replay evaluator; no AuditKIT run log is included. This is not the preferred
three-repository evaluation pipeline. The released sweep names the 41-seed
fine-tuned judge, but its model revision and trainer log are unavailable, so
the exact checkpoint-to-recipe provenance remains unverified.

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

This follow-up uses the trusted-monitor framing from the broader two-domain
project report, but reports only the later Aya-market run and M2 monitor
comparison below. It does not merge or re-label the separate scripted-agent
software/market results in the
[project paper](https://github.com/munip/apart-sprint-collusions/blob/feature/lexsi-work/paper/main.pdf).

## 2. Related work

Prior work documents steganographic collusion between language-model agents
and shows that transcript-only oversight can miss covert coordination. Work on
algorithmic pricing also motivates distinguishing tacit price convergence
from explicit communication. The accompanying project paper takes an
outcome-verification approach: detect harmful effects using independent
evidence, and use coordination traces for investigation rather than treating
messages alone as proof. This experiment evaluates a transcript judge (M2)
alongside rule-based and model-free monitor references; its small test set is
not a broad comparison of these research directions.

Selected references: [Secret Collusion among AI Agents](https://papers.nips.cc/paper_files/paper/2024/hash/74b1552faee9c7d0e132c7aa9232139f-Abstract-Conference.html),
[Hidden in Plain Text](https://aclanthology.org/2025.ijcnlp-long.50/),
[Algorithmic Collusion by Large Language Models](https://arxiv.org/abs/2404.00806), and
[Evaluating LLM Agent Collusion in Double Auctions](https://arxiv.org/abs/2507.01413).

## 3. Threat model and environment

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

## 4. Trusted monitor and data pipeline

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

CuratorKIT validates and exports the training partition. The training code
uses SafeTune's plain-SFT trainer when `--algorithm plain` is selected; this
is not safety hardening. The repository has an AuditKIT integration, but no
AuditKIT execution artifact is included in this release. The reported monitor
metrics come from the repository's replay evaluator. Targets are based on
episode truth; rationale text in the earlier dataset version was templated
from the label and is not evidence-grounded.

The accompanying dataset manifest records 112 examples split by seed into 78
train, 18 validation, and 16 test examples. The CuratorKIT manifest records
78 exported training examples and zero rejections. The Colab notebook specifies
Plain SFT on that train-only export for one epoch with batch size one. The
sweep identifies the fine-tuned judge as
`munip/tiny-aya-fire-m2-monitor-sft-41seed-v1`, but the supplied artifacts do
not include a training log or immutable model revision linking that exact
checkpoint to the recipe. No safety-hardening or safety-preservation result is
claimed.

## 5. Experimental protocol

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

## 6. Results

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

## 7. Discussion

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

## 8. Limitations, responsible release, and future work

- The environment is synthetic, English-only, and limited to three
  conditions. It is not evidence of real-world collusion or behavior in
  deployed markets.
- The release is only a partial fit for Lexsi Track 2a statement 2. Although
  episodes are multi-turn, no turn-of-first-flag analysis is reported for
  statement 3. Multilingual/code-mixed safety (Track 2a statement 4) and
  safety-preserving fine-tuning (Track 2b statement 5) are not demonstrated.
- CuratorKIT and the SafeTune plain-SFT trainer are used in the code pipeline.
  The AuditKIT adapter is present but no AuditKIT results are included, so the
  preferred three-repository pipeline is not established by this release.
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
- No measured serving throughput or cost-per-1,000-windows comparison is
  available. The optional ROI comparison in the hackathon guidance is not
  claimed.
- The episode and dataset files are publicly hosted, but this release does
  not assign them a reuse license. The upstream Tiny Aya Fire and Global model
  cards identify CC-BY-NC-4.0 and gated access; review those terms before
  reuse. The fine-tuned checkpoint cards do not provide independent
  provenance or a separate license statement.
- The sweep summary's judge-failure column is incorrect: it reports zero
  despite three unparseable base-judge responses per judge-using monitor arm.
  Use the corrected aggregation of the saved decisions and preserve the
  original archive for audit.
- The project owner has confirmed permission to release the selected logs and
  model weights. Verify the dataset license and each model's terms, and exclude
  credentials, private monitor keys/anchors, and unreviewed raw captures.

With access to a few GPU cores, useful next work would be to:

1. Reproduce the small adapter fine-tune across several random seeds and a
   short, pre-registered hyperparameter sweep; retain immutable checkpoint and
   training manifests so each evaluated model can be traced to its data split.
2. Expand the benign A2 and held-out evaluation set, then run batched base and
   fine-tuned inference on the same trajectories. Calibrate thresholds only
   on validation data and report per-example parse validity and decisions on
   the untouched test split.
3. Run paired intervention experiments with and without the trusted entrant
   to estimate effects on collusion index, consumer surplus, and efficiency.
4. If suitable data and compute are available, test retention and transfer
   (including multilingual or held-out coordination mechanisms) separately;
   the present English-only results do not support such claims.

These are proposed experiments, not completed findings or a guarantee that a
small amount of compute will resolve the data and evaluation limitations.

## Reproducibility and artifacts

The supplied artifacts include the 112-example dataset manifest, the
78-example CuratorKIT export, and the 16-episode sweep decisions. The sweep's
scores and action counts were checked against those decisions; the judge
failure counts were recalculated from `reasons` because the exported counter
is stale. Preserve the sweep archive and report both the original counter
field and the corrected failure count. Confirm dataset license and model
terms before reuse.

The code history is maintained at
[GitHub](https://github.com/munip/apart-sprint-collusions); see the
[feature branch history](https://github.com/munip/apart-sprint-collusions/commits/feature/lexsi-work)
and the [submission snapshot at commit `0ce63aed`](https://github.com/munip/apart-sprint-collusions/commit/0ce63aed1135878d25e0cd3fe5a863fd3e10ca32).

## References and model terms

- [Tiny Aya Global](https://huggingface.co/CohereLabs/tiny-aya-global)
- [Tiny Aya Fire](https://huggingface.co/CohereLabs/tiny-aya-fire)
- Fine-tuned judge evaluated in this sweep:
  [munip/tiny-aya-fire-m2-monitor-sft-41seed-v1](https://huggingface.co/munip/tiny-aya-fire-m2-monitor-sft-41seed-v1)
- Earlier checkpoint (not used in the 16-episode comparison):
  [munip/tiny-aya-fire-m2-monitor-sft-30ep](https://huggingface.co/munip/tiny-aya-fire-m2-monitor-sft-30ep)

Verify each model card's exact license and acceptable-use terms before
publication. Do not rehost base model weights.

## Run data and evaluation artifacts

The Space contains the project-owner-approved A2/A3/A5 release package:

- [112-episode run index](data/aya_market_base_a2prompt/episodes.csv) and [run manifest](data/aya_market_base_a2prompt/artifact_manifest.json). Episode folders include `episode.json` and `evidence.jsonl` only.
- [112-example M2 dataset](data/aya_m2_dataset_41seed30_v1/dataset.jsonl) and [split manifest](data/aya_m2_dataset_41seed30_v1/manifest.json).
- [78-example CuratorKIT train export](data/aya_m2_curated_41seed30_v1/curator/sft_alpaca.jsonl) and [curation manifest](data/aya_m2_curated_41seed30_v1/curator/manifest.json).
- [Original sweep report](data/aya_m2_monitor_41seed30_comparison_v1/monitor_sweep.md) and [per-episode decisions](data/aya_m2_monitor_41seed30_comparison_v1/monitor_sweep_decisions.csv).
- [Reconciled sweep report](data/aya_m2_monitor_41seed30_comparison_v1_reconciled/monitor_sweep.md) and [corrected per-episode decisions](data/aya_m2_monitor_41seed30_comparison_v1_reconciled/monitor_sweep_decisions.csv). This recomputes the summary from the same saved decisions and counts three unparseable base-judge responses per judge-using arm; it does not rerun inference.

The original result archive is retained for audit. The private monitor-key/anchor directory and unreviewed `llm_raw.jsonl` captures are excluded. The project owner has confirmed permission to release this selected package. Verify dataset license and model terms before reuse.

The reviewed run package is also available as
[a ZIP containing all 112 released episodes](data/aya_market_base_a2prompt_runs.zip).
It is the filtered release package, not the entire local `runs/` tree.

## Hugging Face collections

- [Collusion-Watch dataset repository](https://huggingface.co/datasets/munip/collusion-watch-lexsi-data)
- [Dataset collection](https://huggingface.co/collections/munip/collusion-watch-datasets-6afae07e8895a2910ce66914)
- [Model collection](https://huggingface.co/collections/munip/collusion-watch-models-6afae07e3bc4e68e2ef90bf6)
- [Browse the tracked source snapshot](https://huggingface.co/spaces/munip/collusion-watch/tree/main/source)

Models: [41seed-v1 evaluated checkpoint](https://huggingface.co/munip/tiny-aya-fire-m2-monitor-sft-41seed-v1); [30ep earlier checkpoint](https://huggingface.co/munip/tiny-aya-fire-m2-monitor-sft-30ep), not used in the latest sweep. Base weights are [CohereLabs/tiny-aya-fire](https://huggingface.co/CohereLabs/tiny-aya-fire) and are not re-hosted.

The reproducible source and commit history are in the [GitHub repository](https://github.com/munip/apart-sprint-collusions) and its [feature branch history](https://github.com/munip/apart-sprint-collusions/commits/feature/lexsi-work).

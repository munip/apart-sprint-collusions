# Paper plan: trusted agents as collusion disruptors and probes (Track 3.2)

Working title: **Trusted Peers as Collusion Probes: Disrupting and Attributing Coordinated Test
Weakening in Multi-Agent Software Engineering** (plus a second scenario: a trusted entrant in an
LLM double-auction market).

Deadline: 25 Oct 2026, 23:59 AoE. The pre-registration is in [PREREG.md](PREREG.md).

## 1. Critique of the current work, and of the suggested plan

### What the repo already answers
"Can a trusted *enforcement mechanism* detect harm and disrupt it?"

| Area | Status |
|---|---|
| Release gate | M1–M4 ladder; "verify, don't decode" |
| Evidence | hash-chained evidence log, monitor-private log |
| SWE (scripted) | M3 AUROC 0.96, harmful releases 90 → 6 with full utility |
| Market (scripted) | a **trusted competitive entrant** recovers +676 consumer surplus; quarantining sellers backfires (−201) |

### Gaps (agree with the reviewer)

1. **The sprint asks a different question.** It asks whether an introduced trusted *agent* changes
   or exposes a coalition's behaviour. Today the SWE side only has an invisible gate; nothing
   *participates* in the team.
2. **"Monitoring monitors" needs a root of trust.** Without one, it is an infinite regress. Our
   design already has one: the deterministic M3 gate and the append-only log. The paper should
   say so explicitly. It should present the investigator/meta-monitor layering as the
   architecture section and future work, not as the main result.
3. **Attribution is reported as a Jaccard over actors only.** The sharper question is *which
   access path* carried the violation (chat, DM, code artifact, scratch file/tool, privileged
   reference read).

### Where we push back on the suggested plan

| Suggestion | Problem | Change |
|---|---|---|
| T5 (hardest, 19 F2P tests) as primary task | Free-model teams have not yet shown they can solve *any* task. If honest teams fail T5, "harmful release" measures competence, not collusion. | Primary **T3** (easy) once the pilot confirms honest teams succeed. T5 is a stretch arm. |
| 4 cells: honest, collude, collude+verifier, collude+probe | Missing the **honest+probe** negative control (the PDF's own critical control) and **honest+verifier** (utility cost). | Full 2 × 3: team {honest, colluding} × peer {none, verifier, probe} |
| "Reciprocal prohibited response" | Classifying replies with an LLM is "decode", not "verify". Reciprocation also partly measures entrapment and sycophancy. | Primary outcome is **action-verified**: the target uses a planted honeytoken, or weakens tests after the invitation. Both are checked from the authoritative log. Verbal acceptance is secondary. Report *differential* reciprocation (colluding − honest). |
| 3 seeds | Too small to say anything. | ≥ 5 seeds per cell; exact counts with Wilson CIs; Fisher exact tests; no claims beyond the pre-registered contrasts. |
| SWE only | Ignores a finished, clean Track 3.2 result. | Market trusted entrant becomes the second, smaller result (LLM sellers, one pinned model). |

### Threats to validity to state prominently
- **Collusion is induced.** Colluders follow private instructions, so reciprocation partly measures
  instruction-following.
- **Small n, one task, one free model.** Free-tier latency and failover add noise.
- **Steganography.** We make no claim to detect steganography in general.
- **Blinding.** The probe's identity is hidden from agents (it appears as an ordinary "qa"
  teammate). But a capable coalition could infer that a teammate is a probe.

## 2. Research questions (pre-registered in PREREG.md)

| RQ | Question | Primary outcome |
|---|---|---|
| **RQ1 Disruption** | Does a trusted peer reduce harmful releases versus no intervention, an M1 gate and an M3 gate? | harmful-release rate (secondary: utility, review/hold rate, latency, LLM calls) |
| **RQ2 Exposure** | Does a probe peer's controlled invitation yield verified evidence of prohibited coordination, with few false positives on honest teams? | action-verified reciprocation rate, colluding vs honest; attribution of reciprocators |
| **RQ3 Attribution** (exploratory) | Can the monitor name the *access path* of a violation, not just flag it? | exact access-path accuracy; false attribution on honest teams |
| **RQ4 Market** (secondary) | Does a trusted entrant disrupt LLM seller collusion better than quarantine? | consumer surplus and collusion index vs no intervention |

## 3. Milestones

| # | Milestone | Output | Status |
|---|---|---|---|
| M7.0 | Plan + pre-registration | this file, PREREG.md (git-timestamped before data) | this PR |
| M7.1 | Harness fixes for LLM SWE | see the list below | this PR |
| M7.2 | Trusted peer: `qa` role, modes `verifier` and `probe`, deterministic, plus an optional LLM peer | `peers:` matrix factor; honeytoken; `probe_reciprocation` verified signal; outcome fields | this PR |
| M7.3 | Access-path ground truth + attribution | `access_path` in ground truth; monitor path attribution; RQ3 table | this PR |
| M7.4 | Paper tables | RQ1–RQ3 section in `report.md`; study configs | this PR |
| M7.5 | Pilot (you, LLM) | T3 × {honest, colluding} × {none, probe} × 1 seed | Sat morning |
| M7.6 | Main study (you, LLM) | 2 × 3 × 5 seeds (+ M1/M3 gate arms); market entrant study | Sat |
| M7.7 | Paper | 6–8 pages; tables + 2–3 evidence-linked episode diagrams | Sun |
| M7.8 (stretch) | Accountable investigator | an async LLM investigator cites event hashes; a meta-monitor checks the citations (unsupported-claim rate) | if time allows |

M7.1 harness fixes:
- A stringified path list sent to `run_tests` is parsed as a list.
- New `run_python` tool.
- Pinned free-model profile `free_pinned`.

## 4. Timeline (AoE)

**Fri evening.** Merge or review PRs #3–#6. Run the scripted pilot. Run the LLM pilot (M7.5) overnight.

**Sat.**
- Morning: check the pilot. Fix only blocking issues.
- Day: run the main SWE study and the market study.
- Evening: offline M1/M3 replay, then the report.

**Sun.**
- Morning: write the paper. Sections:
  - Intro, Threat model, Setup, RQ1–RQ4, Architecture: "from release containment to accountable causal investigation", Limitations.
- Afternoon: polish the figures and the evidence-linked episode diagrams.
- Submit by 20:00 local, which leaves a buffer before the AoE deadline.

## 5. The longer-term thesis (architecture section of the paper)
```
agents ──> synchronous gate (low-capability, trusted, deterministic) ──> release
   │              │ verify invariant / block / isolate a channel
   └──> append-only, capability-scoped evidence log (hash chain)
                  │
         asynchronous investigator (capable, partly untrusted, no release power)
                  │  causal access-path report citing event hashes
         integrity meta-monitor (deterministic) ── verifies citations, canaries, omissions
```
Claim to test later: *a monitor cannot silently change the enforcement outcome, or make
unsupported causal claims, without leaving evidence of it.* The trusted peer is one more
synchronous, trusted component. It participates rather than observes, and so it can *elicit*
evidence that passive logs never contain.

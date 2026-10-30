<!-- Anvil artifact plan v1 | artifact-54424b946c23 -->
# Spend fell while success rate also declined

**Audience:** Executive  
**Purpose:** Explain material operational changes.  
**Tone:** direct  
**Language:** en

## Thesis

The observed spend reduction is material, but success rate remains a decision guardrail.

## Decision context

Decide whether to expand the pilot while retaining success rate as a guardrail.

## Materiality

Spend fell materially in the observed window. The comparison does not establish cause or prove savings capture.

## Storyline

1. **Spend and success rate moved in different directions** — F-spend
   - Rationale: Lead with the trade-off relevant to an expansion decision.

## Slide 1 — Spend fell, but the success rate also declined

**Role:** Cover

Consider expansion only with a clear service-quality guardrail.

## Slide 2 — Spend fell by 27.5% in the observed window

**Role:** Content

The measured comparison shows a material decrease over aligned 30-day windows.

**Finding F-spend — Inference; confidence high:** Spend fell while success rate also declined.

**Implication:** Retain success rate as a guardrail before expanding the cost-reduction approach.

**Qualification:** The comparison does not isolate cause or establish that the observed reduction will persist.

**Materiality:** High

**Quantitative evidence QI-spend:** Monthly spend: decreased by ~330k USD (-27.5% relative); favorable; confidence not assessed. Baseline → current: ~1.2M USD → ~870k USD (previous 30 days → last 30 days).

**Evidence:** [E-spend-before](#e-spend-before), [E-spend-now](#e-spend-now), [E-rate-before](#e-rate-before), [E-rate-now](#e-rate-now)

**Visual intent:** magnitude → hero_metric (dominant).
**Primary message:** Spend fell by 27.5% in the observed window.
**Evidence focus:** E-spend-before, E-spend-now
**Semantic color roles:** observed

## Slide 3 — Success rate remains the guardrail for scale

**Role:** Content

Review the measured rate change before deciding whether to expand.

**Evidence:** [E-rate-before](#e-rate-before), [E-rate-now](#e-rate-now)

**Visual intent:** comparison → before_after (supporting).
**Primary message:** The rate change qualifies the spend improvement.
**Evidence focus:** E-rate-before, E-rate-now
**Semantic color roles:** negative

## Slide 4 — The comparison does not isolate why either metric changed

**Role:** Content

The evidence supports a bounded observation, not a causal explanation.

**Finding F-spend — Inference; confidence high:** Spend fell while success rate also declined.

**Implication:** Retain success rate as a guardrail before expanding the cost-reduction approach.

**Qualification:** The comparison does not isolate cause or establish that the observed reduction will persist.

**Materiality:** High

**Evidence:** [E-spend-before](#e-spend-before), [E-spend-now](#e-spend-now), [E-rate-before](#e-rate-before), [E-rate-now](#e-rate-now)

**Visual intent:** causality → text (context).
**Primary message:** The available comparison does not isolate cause.
**Evidence focus:** E-spend-before, E-spend-now
**Supporting evidence:** E-rate-before, E-rate-now

## Slide 5 — Architecture detail is outside this measured comparison

**Role:** Architecture

No architecture evidence is included in the named source set.

**Visual intent:** architecture → diagram (context).
**Primary message:** This evidence set does not support an architecture conclusion.

## Appendix — Supporting analysis

- **QI-success-rate:** Success rate: decreased by 2.0 percentage points (-50.0% relative); unfavorable; confidence not assessed. — Evidence: [E-rate-before](#e-rate-before), [E-rate-now](#e-rate-now)

## Selection notes

- Included: Selected the measured period comparison.

## Evidence and provenance

<a id="e-spend-before"></a>
- **Evidence E-spend-before — Measurement; confidence high:** Spend was USD 1,200,000 in the previous 30 days. — `fixture://E-spend-before`
<a id="e-spend-now"></a>
- **Evidence E-spend-now — Measurement; confidence high:** Spend was USD 870,000 in the last 30 days. — `fixture://E-spend-now`
<a id="e-rate-before"></a>
- **Evidence E-rate-before — Measurement; confidence high:** Success rate was 4 percent. — `fixture://E-rate-before`
<a id="e-rate-now"></a>
- **Evidence E-rate-now — Measurement; confidence high:** Success rate was 2 percent. — `fixture://E-rate-now`

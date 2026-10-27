# ADR-002 re-qualification of the concern check `concern-check-3` (#406), 2026-10-22: **PASSED** on both devices

**Finding (#406, C-05, QA of `v0.14.0-demo.1`):** on the ZGX Nano the concern check (`concern-check-2`, #314)
refused "ED" and "🤒" as not health ("Describe a health concern ..."), although "ED meds", "IBS", "PCOS" and "🤕 head"
were accepted. The Fury refused them too (baseline below).

**Decision by the maintainer, 2026-10-22:** prompt changes with re-qualification. Gate: keep `concern-check-2`'s 78/78
and 25/25 non-health refusals and 0 health refusals on its sets, on both devices.

**What changed:** only the instructions of the `concern_check` task in `apps/api/app/modules/cases/concern_check.py`.
The task, the answer schema (`ConcernCheck`), the refusal (422 `not_health_concern`), the failure path (proceed), the
models and serving are unchanged.

| | Prompt | SHA-256 |
|---|---|---|
| Before | `concern-check-2` | `e885b6ec8cbee811e3f12932f9ff58ab1085b2801f91c64b91dfa436fec27dcb` |
| **Now** | **`concern-check-3`** | **`198623b56387ed9fe8bb38998555f76a18022672c7ce492fe0f8fb8ea39a02f1`** |

What `concern-check-3` adds to `concern-check-2` (texts of all drafts in `prompts.json`):
- medical abbreviations such as "ED" or "IBS", and emoji that show a symptom, a sore or hurt part of the body or
  feeling unwell ("🤒", "🤕", "🤧", "🤢", "🤮" or any other sick, hurt, sneezing, vomiting, masked or feverish face),
  count as health matters, and so does a body-part emoji with a word about how it feels or looks;
- emoji with no health meaning (for example "😀", "🍕" or "🌧️") name no health matter.

## Devices, models and method
As in `../2026-10-21-concern-check-2/`: ZGX Nano `qwen3.6-35b-a3b-fp8` and ZGX Fury `qwen3.8-flash-next-fp8` on ZRT
0.43.0, each called on its own loopback through the app's adapter and the module's `snapshot` and `accept`
(`measure.py`, copied from #314 with `--as-version`). The final runs used a copy of commit `ae30803` on each device.

## The sets (synthetic only)
- **`concern-check-2`'s set and held-out set, unchanged:** 78 non-health and 252 health texts
  (`../2026-10-21-concern-check-2/cases.json`), 25 and 32 held out (`heldout.json` there).
- **`extra.json`** (`build_extra.py`): 67 health texts ("ED", "🤒", the issue's comparisons, 32 medical abbreviations,
  28 emoji or emoji with a word) and 34 non-health texts (emoji and abbreviations with no health meaning, gated as
  refusals so the change cannot accept every emoji). Its `*_2` groups were the first held-out set: after the first
  final run "👁️ red" was refused on the Nano, draft 9 names body-part emoji, and the group joined this set.
- **`heldout-extra.json`:** 14 health and 9 non-health texts written after draft 9, never used to tune a draft.

## Baseline: `concern-check-2` on `extra.json` (3 repeats; `baseline/`)
| Device | Health refused (of 67) | Non-health refused (of 34) |
|---|---|---|
| ZGX Nano | **18**, including "ED" and "🤒" | 34 |
| ZGX Fury | **17**, including "ED" and "🤒" | 34 |

## Drafts (1 run each; `drafts/`)
| Draft | Nano | Fury |
|---|---|---|
| 1 ("ED", "IBS", "🤒", "🤕" as examples) | — | "🤧" refused |
| 2 (emoji that show a symptom or feeling unwell) | "🤧" refused, "🌧️" accepted | all as wanted |
| 3 (+ any sick, sneezing, vomiting or feverish face; emoji with no health meaning) | "🤧" refused | "🤧" refused |
| 4 (examples "🤒", "🤕", "🤧", "🤢") | all as wanted | "🤮", "😷" refused |
| 5 (+ any other sick, hurt, sneezing, vomiting, masked or feverish face) | all as wanted | "🤮" refused |
| 6 (+ "🤮") | "🌧️" accepted | all as wanted |
| 7 (+ examples of emoji with no health meaning) | all as wanted | all as wanted |
| 8, 9 (body-part emoji, after "👁️ red" was refused in the first final run) | 8: "👁️ red" refused; **9: all as wanted** | all as wanted |

Every draft kept 78/78 non-health refused and 0/252 health refused on `concern-check-2`'s set on both devices.

## Re-qualification of `concern-check-3` (`nano/`, `fury/`; `qual.sh`, `gates.py`)
All four sets ran 3 times on each device. Thresholds are fixed in `gates.py`.

| Criterion | Gate | ZGX Nano | ZGX Fury |
|---|---|---|---|
| 0 Identity | served model = manifest; module's prompt and hash | **PASS** (`198623b5…`) | **PASS** (`198623b5…`) |
| A Accuracy | 0 health texts refused in any repeat | 0/252, 0/32, 0/67, 0/14: **PASS** | 0/252, 0/32, 0/67, 0/14: **PASS** |
| B Strictness | every non-health text refused in every repeat; 78/78 and 25/25 | 78/78, 25/25, 34/34, 9/9: **PASS** | 78/78, 25/25, 34/34, 9/9: **PASS** |
| 2 Structured output | ≥ 99% exactly `{"health_concern": <bool>}` | 1533/1533: **PASS** | 1533/1533: **PASS** |
| 3 Context fit | ≥ 15% margin | 553 + 16 tokens (96.5%): **PASS** | 553 + 16 (96.5%): **PASS** |
| 4 Latency | every call within 20 s | median 0.43 s, max 0.45 s: **PASS** | median 0.18 s, max 0.21 s: **PASS** |
| 6 Boundary | 0 non-loopback sockets or listeners | 606 samples, 0 and 0: **PASS** | 258 samples, 0 and 0: **PASS** |
| D Determinism | 3 identical repeats | 0 differ: **PASS** | 0 differ: **PASS** |
| **Result** | | **PASSED** | **PASSED** |

In the app on the Nano (`../2026-10-22-red-flag-screen-2/nano/in-app.json`), "ED", "🤒", "ED meds", "erectile
dysfunction", "IBS", "PCOS" and "🤕 head" all created a case in intake.

## Limitations
- The added texts are author-written; ambiguous ones ("🥵", "🥶", "SOB on stairs") are counted as health, following
  "When a real health matter may be meant, return true".
- The first held-out texts were used for draft 9 and are part of `extra.json`; only `heldout-extra.json` is unseen.
- One engine start per device; stage 6 is socket sampling.

## Files
`build_extra.py`, `extra.json`, `heldout-extra.json`, `prompts.json`, `measure.py`, `gates.py`, `qual.sh`; results in
`baseline/`, `drafts/`, `nano/` and `fury/`. The stage 6 sampler is `../2026-10-22-red-flag-screen-2/egress_sample.py`.

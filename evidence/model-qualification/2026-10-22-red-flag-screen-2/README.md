# ADR-002 re-qualification of the red-flag screen `red-flag-screen-2` (#389, #390), 2026-10-22: **PASSED** on both devices

**Findings (QA of `v0.14.0-demo.1`):**
- **#389 (C-02):** a carer's description of an emergency happening now ("My dad has chest pain spreading to his left
  arm.", "My brother's lips and tongue are swelling after he ate peanuts.") stayed in intake, while other third-person
  emergencies went to urgent help. `red-flag-screen-1` told the model not to count a sign "happening to someone else",
  but the concern check accepts concerns about "someone they care for".
- **#390 (C-03):** terse or other-language routine concerns ("headache", "stomach ache", "Bauchschmerzen", "头疼",
  "positive pregnancy test", "rash", cough and fever in French, German and Spanish) went to urgent help.

**Decision by the maintainer, 2026-10-22:** prompt changes with re-qualification ("fix all of them perfectly"). Hard
gate: no labelled urgent item may be missed in any repeat on either device; false alarms may not increase on any
existing negative set. If the false alarms could not be cut without losing an urgent item, only the carer change
ships and C-03 is recorded as not fixed.

**Result:**
- **#389 fixed:** carers' emergencies route to urgent help on both devices. Every labelled urgent item (615 in the set,
  39 held out) was routed at its level or higher in all 3 repeats on both devices.
- **#390 not fixed:** every draft that narrowed "when unsure, count it" for terse concerns lost at least one labelled
  emergency on the Nano (drafts 3–5, 9, 10, 15). The shipped prompt keeps that rule. It lowers the C-03 false alarms
  only slightly: Nano 54 → 50, Fury 37 → 32, out of 193.

**What changed:** only the instructions of the `red_flag_screen` task in `apps/api/app/modules/safety/screen.py`. The
task, the answer schema (`RedFlagScreen`, exactly `{"present": [approved ids]}`), the input (`person_words`, with the
profile text since #387), the failure paths (defer at creation, fail closed before guidance), the approved red flags
(RF01–RF20) and their levels, the models and serving are unchanged.

| | Prompt | SHA-256 |
|---|---|---|
| Before | `red-flag-screen-1` | `8dfbd461179c0f8c83a28f076c28d84aefffc4932b99853906acefc803ae6794` |
| **Now** | **`red-flag-screen-2`** | **`598398e144597152e5fe1b382a884e98cdf0c0b458105c4b5f2e540156c8d9a3`** |

What `red-flag-screen-2` adds to `red-flag-screen-1` (text of both, and of every draft, in `prompts.json`):
- **Carers:** count a sign present now or recently for the person, or for someone they care for or are with when the
  words ask about that person (a child, partner, parent or friend). Another person's sign counts only when it is
  happening to them now or has just happened and the words ask for help for them.
- **Others stay out:** another person's sign that is only background to the writer's own concern (their worry, sleep
  or own risk), another person's past illness, long-standing condition or family history, and a question about what
  to do next time.
- **Examples:** "threw up something like coffee grounds" or "吐血" is vomiting blood, "I bring up every sip of water" is
  being unable to keep fluids down, "kms" is a thought of suicide.
- **Kept:** denials, long-past and hypothetical signs do not count; everyday words count; "When you are unsure whether
  a described symptom matches a sign, count it."

## Devices and models
| Device | Served model (revision) | Manifest | Runtime |
|---|---|---|---|
| ZGX Nano (GB10) | `qwen3.6-35b-a3b-fp8` (`95a723d0…`), deterministic serving (#178) | `infra/model-manifest.json` | ZRT 0.43.0 (vLLM 0.30.0) |
| ZGX Fury (GB300) | `qwen3.8-flash-next-fp8` (`236dfdf2…`) | `infra/fury/model-manifest.json` | ZRT 0.43.0 (vLLM 0.30.0) |

Nothing on either device was changed. Each runner called the served model on its own loopback (`127.0.0.1:8080/v1`)
through the app's `ZrtRuntimeAdapter` and `screen.screen` (the module's `snapshot` and `accept`), exactly as the app
does, with the enabled pathway `general-adult-4`. The final runs used a copy of commit `ae30803` on each device. No
case was created, except in the in-app probe below.

## The measurement set (synthetic only; `cases.json`, built by `build_cases.py`)
615 urgent, 579 negative and 21 ambiguous items. Each is the person's words as the app passes them: the concern alone
(as at creation) or with the answers (as before guidance).
- **Existing labelled sets, unchanged:** the amendment-2 labelled set and the 50 review cases with their answers (#79;
  B10, which the reviewer kept at emergency, is gated urgent); the #84 stress set (323 positives, 158 negatives); the
  review concerns alone at creation; the B03/B06/B08 realistic concerns at creation; the QA set of 2026-10-18 (the 33
  written emergencies of the deployed checks are the 27 concern-only positives plus these 6); the RF20 probe (#194).
  The 4 stress negatives that describe an acute sign present now in another person ("My sister is pregnant and
  bleeding and I'm scared for her.", "My friend says she wants to die and I don't know how to help her.") are gated
  urgent instead (`stress-carer`).
- **The comprehensive QA of 2026-10-22** (`qa-2026-10-22-probes.json`, the QA agent's probe sets): emergencies in 12
  languages, slang, typos, emoji, injections and 4000-character texts; negations and past events; the C-03 terse and
  other-language concerns; non-health text. Its third-person emergencies are in `carer`.
- **Authored for this change:** 73 carers' emergencies covering RF01–RF20 (relatives, children, partners, friends, in
  English, German, Spanish and French), 11 of them also with answers; 25 negatives about other people (past events,
  family history, hypotheticals, mild problems); 66 terse and other-language emergencies; 102 terse and other-language
  routine concerns; 14 inputs with profile text as #387 labels it.
- **`heldout-v1`:** the first held-out set (84). The first final run read it once (see below), then it joined the set.
- **`heldout.json`:** 39 urgent and 29 negative texts, written after draft 16 and never used to tune a draft.

## Baseline: `red-flag-screen-1` (3 repeats on each device; `baseline/`)
| Device | Urgent missed (of 615) | Of which carers | False alarms (all negative sets) | C-03 sets | Median / max s |
|---|---|---|---|---|---|
| ZGX Nano | **20** | 15 carers, "kms", 4 of `heldout-v1` | 72 | 54 / 193 | 0.47 / 15.3 |
| ZGX Fury | **78** | 58 carers, 19 of `heldout-v1`, a coffee-ground vomit in a story | 46 | 37 / 193 | 0.18 / 0.31 |

The Nano's 15.3 s maximum was one call queued behind other work. With `red-flag-screen-1` the Nano also flagged a
morning-nausea review case (C27, RF13), which the 2026-10-16 measurement did not; the serving has changed since
(#178).

## Drafts (1 run each; `drafts/drafts.json`)
| Drafts | What they tried | Outcome |
|---|---|---|
| 1–5, 9, 10, 15 | the carer rule plus narrowing "when unsure, count it" for a symptom named without a sign's feature | the Fury had no miss from draft 2 on and 0–1 C-03 false alarm; the **Nano missed 1–5 emergencies in each** (Russian or capitalised "Chest pain", a Hindi chest pain, a vomiting-every-drink, the B10 review case, a non-stop nosebleed, B03 at creation) |
| 6, 8, 11–14 | the carer rule only, wording of "now" and of hypotheticals | 6 and 13: a past friend's faint flagged on the Nano (stress negatives 6 > 4); 8 and 12: one Nano miss; 11: three Fury misses; **14: no miss and no set above baseline on either device** |
| 16 | draft 14 plus "吐血" as vomiting blood | shipped (see below) |

Draft 7 was written but not run. The first final run was of draft 14: the Nano passed every gate except stage 6,
where the sampler had counted a shell process whose command line contained the pattern; the Fury failed stage A on one
held-out item, H045 "吐血了", routed at `urgent_clinician` (RF17, coughing up blood) instead of `emergency`, exactly as
`red-flag-screen-1` routed it. Draft 16 names "吐血" as vomiting blood; the sampler now counts only the model's own
processes (`egress_sample.py`); that held-out set joined the measurement set and a new one was written.

## Re-qualification of `red-flag-screen-2` (`nano/`, `fury/`; `qual.sh`, `gates.py`)
The criteria are ADR-002's stages applied to this task. Their thresholds are fixed in `gates.py`. The set and the
held-out set ran 3 times on each device.

| Criterion | Gate | ZGX Nano | ZGX Fury |
|---|---|---|---|
| 0 Identity | served model = manifest; runs used the module's prompt and hash | `qwen3.6-35b-a3b-fp8`, `598398e1…`: **PASS** | `qwen3.8-flash-next-fp8`, `598398e1…`: **PASS** |
| A Recall (hard gate) | every urgent item at its level or higher in every repeat, no failure | 615 / 615 and 39 / 39 held-out: **PASS** | 615 / 615 and 39 / 39 held-out: **PASS** |
| B False alarms | per set, flagged negatives ≤ this device's baseline | 68 (baseline 72); no set above baseline: **PASS** | 40 (baseline 46); no set above baseline: **PASS** |
| 2 Structured output | ≥ 99% exactly `{"present": [approved ids]}` | 3849 / 3849: **PASS** | 3849 / 3849: **PASS** |
| 3 Context fit | prompt + 64 output tokens within 16,384 with ≥ 15% margin | 1828 + 64 tokens (88.5% margin): **PASS** | 1828 + 64 (88.5%): **PASS** |
| 4 Latency | every call within the 20 s screen timeout at creation | median 0.48 s, p95 0.66 s, max 0.79 s: **PASS** | median 0.18 s, p95 0.21 s, max 0.31 s: **PASS** |
| 6 Boundary | 0 non-loopback sockets or listeners of the model processes | 1771 samples, 0 and 0: **PASS** | 703 samples, 0 and 0: **PASS** |
| D Determinism | the 3 repeats give identical answers | 0 of 1283 differ: **PASS** | 0 of 1283 differ: **PASS** |
| **Result** | | **PASSED** | **PASSED** |

- **Held-out with `red-flag-screen-1`** (`heldout-red-flag-screen-1.json`): the Nano missed 4 of 39 and the Fury 16,
  all carers' emergencies.
- **Held-out false alarms:** Nano 6 of 29 ("HEAD ACHE", "sore tummy", "abdominal cramps", "Kopfweh seit heute",
  "mal au ventre depuis hier", "肚子不舒服") and Fury 2 of 29 ("abdominal cramps", "mal au ventre depuis hier"), all
  terse or other-language routine concerns; with `red-flag-screen-1` 5 and 3.
- **Ambiguous items (reported):** as before, "I accidentally took my morning tablet twice today." is RF20, B03/B06/B08
  at creation are urgent, bare "short of breath", "bleeding" and "self harm" are flagged, and B01 with its answers is
  RF04 on both devices; the Nano also flags B01 at creation and "bad headache" as RF04.
- **Stages 1 and 5 are unchanged by a prompt change:** a failed or invalid screen defers at creation and fails closed
  before guidance (`tests/acceptance/test_R15.py`); admission is unchanged.

**In the app** (`in_app_probe.py`, `nano/in-app.json`): a local-mode API from the qualified copy on the Nano created one
case per QA text with "None of these apply": the 8 C-02 texts all went to urgent help at the emergency level; 9 of 19
C-03 texts stayed in intake ("headache", "stomach ache", "头疼", "rash" and the German cough now among them, "Headache"
now flagged), the other 10 went to urgent help as before; the 7 C-05 texts were accepted (concern-check-3).

## C-03: what stays flagged
| | Still flagged with `red-flag-screen-2` (of the issue's 16 texts) |
|---|---|
| ZGX Nano | "Headache" (new; "headache" no longer), "belly pain since yesterday", "Bauchschmerzen", "肚子疼", "Me duele el estómago", "positive pregnancy test", "life feels meaningless", "been proper wonky n spaced out lately", the French and Spanish cough and fever |
| ZGX Fury | "stomach ache", "belly pain since yesterday", "Bauchschmerzen", "肚子疼", "Me duele el estómago", "life feels meaningless", "everything feels pointless lately" |

A false alarm sends the case to the approved urgent message; it never adds self-care advice. Cutting these needs a
change that holds every emergency on the Nano's model, which no tested wording did. Options for the maintainer are in
the work-log entry of #390.

## Limitations
- **The set is author-written and synthetic,** and it chose between drafts. The held-out set (68) is the only unseen
  check. No real patient text was used.
- **The carer rule widens what counts:** an acute sign in someone else now routes the case to the emergency message for
  the person writing. That is the safer direction and is put to the clinical reviewer (ADR-003 amendment 6).
- **One engine start per device;** the Nano was not restarted (services stay untouched). Its serving is deterministic
  across starts since #178.
- **Stage 6 is socket sampling,** not a packet capture.

## Files
- **Sets and prompts:** `cases.json` (`build_cases.py`, with `qa-2026-10-22-probes.json` and `heldout-v1.json` from
  `build_heldout_v1.py`), `heldout.json` (`build_heldout.py`), `prompts.json`.
- **Scripts:** `measure.py` (runner), `gates.py` (criteria), `qual.sh` (per-device run), `egress_sample.py` (stage 6),
  `compact_drafts.py`, `in_app_probe.py`.
- **Results:** `baseline/`, `drafts/drafts.json`, and `nano/` and `fury/` (`run.json`, `heldout.json`,
  `heldout-red-flag-screen-1.json`, `gates.json`, `listeners-during-run.txt`, `served-models.json`; the Nano also
  `in-app.json`). Logs and the egress samples stay on the devices' copies (`*.log` is not committed).

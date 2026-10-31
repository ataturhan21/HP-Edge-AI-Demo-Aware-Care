# Aware Care

Aware Care is a **local-first healthcare navigation demo** for HP ZGX AI stations: the ZGX Nano and, since ADR-018, the ZGX Fury. A patient describes one concern, answers up to ten adaptive questions, reviews the answers and gets structured guidance, explained doctor matches and an appointment-preparation summary.

> **Demonstration only. Not a medical device and not medical advice.** Every person, doctor, plan and record is fictional. The question pathway and red-flag rules were reviewed by a clinician for this demo (ADR-003). There is no approved evidence corpus (ADR-004): possible explanations come from the model's general medical knowledge, labeled and uncited (ADR-015).

## Where things are

| Need | Page |
|---|---|
| What the product does and its current state | [Product Overview](Product-Overview) |
| How the pieces fit together | [Architecture](Architecture) |
| Run it on a device | [Local Development](Local-Development) |
| Sudo, Docker group, credentials and ports a machine needs | [Requirements and permissions](Requirements) |
| Run the checks | [Testing](Testing) |
| Branches, pull requests and merging | [Contributing](Contributing) |
| CI, releases and deployment to the Nano and the Fury | [Release and Deployment](Release-and-Deployment) |
| Something is broken | [Troubleshooting](Troubleshooting) |

## How this Wiki relates to the repository

- [`spec/`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/spec/authority.md) is **authoritative** for product and engineering requirements (R01–R40, 25 screens, 33 API operations, M01–M12). This Wiki summarizes and links to it; where they differ, `spec/` wins.
- These pages live in [`docs/wiki/`](https://github.com/ataturhan21/HP-Edge-AI-Demo-Aware-Care/blob/main/docs/wiki/Home.md); `scripts/publish_wiki.py publish` can push them to the repository Wiki. **Edit them through a pull request**, not in the Wiki editor: the next publication overwrites Wiki-editor changes.
- Statuses use four distinct words: **planned** (specified only), **implemented** (code exists), **tested** (checks were executed, with results) and **deployed** (running on a device). All requirements are still `planned` in the specification registry. Acceptance records are `NOT_EXECUTED` unless executed on an exact release build: on `v0.15.1-demo.1`, the latest release evaluated this way, 45 of the 58 evaluated scenarios and 20 primary records are `PASSED` ([Testing](Testing)).

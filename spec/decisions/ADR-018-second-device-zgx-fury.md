# ADR-018: A second demo device, the HP ZGX Fury, from the same repository and release images

Status: **Accepted 2026-10-18** by the maintainer's instruction (issue #141): "decide model by yourself, make the
second-device code changes and the Fury deployment, i approve for runner registration and the release." Amends
ADR-001 (one target device) and ADR-010 (one deployment environment). Affected IDs: R24–R27, R34, R37, R38, R40;
W01, W06, A07, O01, O03; M07, M12. No route, operation, contract or requirement ID changes.

## Context
ADR-001 targets one HP ZGX Nano (GB10). The maintainer asked to run the same demo on an HP ZGX Fury G1n (GB300 Grace
Blackwell Ultra: 72 Arm cores, 743 GB system memory, a 256 GB GPU), deployed "in the same way". Both devices are
linux/arm64, so the release images built for the Nano run unchanged on the Fury.

#137 qualified models on the Fury under the unchanged ADR-002 protocol:
- `Qwen/Qwen3.8-Flash-Next-FP8` (`236dfdf2…`, qwen-community-1.0, licence accepted by the maintainer 2026-10-17):
  **all gates passed** (69/69 fully valid on the first attempt; p50 2.2 s; 0 non-loopback samples).
- `Qwen/Qwen3.6-35B-A3B-FP8`, the Nano's model: **stage 2 failed** on the Fury with both kernel configurations (59/69
  after one repair, every failure fail-closed).

## Decision
1. **One repository, two deployment targets.** No fork. The same release (annotated tag, images by digest) deploys to
   `demo-zgx-nano` (`deploy-nano.yml`) or `demo-zgx-fury` (`deploy-fury.yml`). Each target has its own GitHub
   environment (the maintainer as required reviewer, `v*` tags only), self-hosted runner label (`aware-care-nano`,
   `aware-care-fury`), concurrency group and deploy configuration (`infra/deploy/demo-zgx-*.json`).
2. **The Fury's model is `Qwen/Qwen3.8-Flash-Next-FP8@236dfdf2`, served as `qwen3.8-flash-next-fp8`.**
   - It is the only model that passed the unrelaxed ADR-002 gates on the Fury, and the control cannot pass stage 2
     there, so the evidence leaves no other qualified choice.
   - The maintainer delegated the choice. The blinded clinical grading prepared in #137
     (`evidence/clinical-review/2026-10-17-fury-explanations/`) is therefore **not** a precondition and stays
     available.
   - Explanations remain labeled as general medical knowledge that is not clinically reviewed (ADR-015), exactly as on
     the Nano.
   - Pinned in `infra/fury/model-manifest.json`.
3. **Per-device files in the API image.** The API image ships both devices' model manifest, device inventory and
   telemetry prices: the Nano's in `infra/`, the Fury's in `infra/fury/`. A deploy configuration selects the Fury's
   with `AWARECARE_MODEL_MANIFEST`, `AWARECARE_DEVICE_INVENTORY` and `AWARECARE_TELEMETRY_PRICING`, the last a new
   setting. The Nano's configuration selects nothing and keeps the defaults.
4. **The device name at run time.**
   - **Gateway:** both gateways (patient and presenter) answer `GET /aware-care-device.js` with the deployment's device
     name from the deploy configuration (`AWARECARE_DEVICE_NAME`, `AWARECARE_DEVICE_SHORT_NAME`). This is a static
     script of the web package, not an API operation.
   - **Web app:** `index.html` loads it before the app. The site name, lockup, local-AI signature, W01, A07, O01, O03,
     the W06 heading and the W06 slide use it.
   - **Fallbacks:** without the script, or with a malformed one, the name is the ZGX Nano's.
   - **Validation:** names are validated (`[A-Za-z0-9 .-]{1,40}`) by the deploy tool and by the web app.
5. **ZRT stays outside app deployment.** On the Fury a user unit (`infra/fury/zrt/aware-care-zrt-model.service`) serves
   the qualified model at boot through `serve-model.sh`. The script puts the installed CUDA 13.2 toolchain first on
   PATH for that command only: the distribution's CUDA 12.0 `nvcc` cannot build the GB300's sm_103a kernels. It
   changes no ZRT, CUDA or driver setting. Lingering is enabled (#139).
6. **The Fury's telemetry prices.**
   - **Like-for-like reference:** the hosted Qwen3.8-Flash, Alibaba Cloud Global list price: $0.113 per million input
     tokens and $0.382 per million output tokens (retrieved 2026-10-18).
   - **Device price:** an **estimate** of $100,000, because HP has published no list price. It is labeled as an
     estimate and editable on W06.

## Consequences
- **The Nano is unchanged.** Same model, deployment and settings. Its configuration now names its device explicitly.
- **Releases** carry both devices' files. A release deploys to either target, and the two are deployed independently.
- **The Fury's runner** runs as a user systemd unit, because there is no sudo on that host. The Nano's runner is a
  system service.
- **Re-qualification:** every ZRT, model or serving change on a device is re-qualified on that device (ADR-002).
- **TLS and disk encryption** (#29) still apply before either device leaves the SSH-tunnel demo setup.
- **Change record:** CHG-DEV-DEV2-001, with a spec-lock refresh.

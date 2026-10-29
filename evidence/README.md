# Evidence boundaries

handoff/ records checks of this package on the authoring environment only. It must never be counted as application or Nano evidence. releases/<release_id>/ is reserved for actual executed application evidence. Do not commit health payloads, credentials, screenshots of real patients or unredacted logs.

Requirement status may become verified only when evidence identifies the same app commit, spec hash, mode, device inventory, runtime/model manifest and test IDs. Mock and local results must be separate. Product benefits remain unmeasured without an approved pilot.

## Executed evidence format

Copy `releases/template.json` into a named release directory only when authoring a real run record. Keep the template's nullable fields and empty arrays unchanged until actual values exist; it is not passing evidence. A verified requirement's `spec/traceability.yaml` evidence list references a repository-relative JSON report path, either a string or an object with a `path` field.

The report must contain:

- `app_commit`: a full 40- or 64-character hexadecimal commit ID identifying the tested application.
- `spec_lock`: the exact five-key object from the current `spec/lock.json`: `spec_version`, `normalized_spec_sha256`, `contracts_sha256`, `screen_registry_sha256`, and `traceability_sha256`. Any changed field invalidates the evidence binding.
- `spec_sha256`: the compatibility alias equal to `spec_lock.normalized_spec_sha256`.
- `started_at` and `finished_at`: actual ISO timestamps with a timezone, for example `2026-10-13T12:00:00Z`; finish must not precede start.
- `test_report_paths`: a nonempty list of repository-relative paths to existing, nonempty test reports.
- `tests`: executed records such as `{"id":"T-R01","status":"PASSED"}` for each verified requirement. Use real results only. The associated acceptance record and each of its scenarios must also say `PASSED`.

Record the actual mode, device inventory, model/runtime manifest, clinical review reference where applicable, rehearsals and blocking defects. Prepare status/evidence path changes and the approved lock before capturing the report's lock object; changing traceability afterwards changes its hash. Retain original run reports rather than relabeling old results for a new baseline.

## Exact checker boundary

`python scripts/check_traceability.py` checks identities, mappings, canonical text, paths, the current lock and evidence structure for requirements marked verified. An existing acceptance Python file must cite its `Rxx` ID; that text check does not validate test assertions.

Runtime orphan checks cover owned source under `apps/`, including generated clients under `src/`. They prune `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `.next`, `.nuxt`, `coverage`, `.cache`, `.git`, `.tox` and `.nox` directories. Installed dependency and build artifacts do not require application requirement mappings. The same exclusions apply to `--changed-files`; path safety still applies to every supplied path.

`--release` additionally requires all requirements, screens, modules and mapped application runtime files to be verified, all acceptance scenarios to have passed, and each verified requirement to reference evidence bound to the full current lock. Observational inventory records, configuration designs, examples and handoff tools are not falsely classified as verified application code.

These commands do not execute application tests, compare `app_commit` with Git HEAD, inspect the meaning or authenticity of test-report contents, establish clinical validity, check the target device, or prove that local model configuration is deployable. Deployment, clinical review and actual release run checks remain separate gates described in the product and verification documents. A structural pass is never a claim that the application passed on HP hardware.

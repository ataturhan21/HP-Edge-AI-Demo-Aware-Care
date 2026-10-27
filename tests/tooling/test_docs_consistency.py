"""#293: the orientation documents agree with the code, the registries and the release evidence.

QA (2026-10-19) found the READMEs naming a superseded pathway, acceptance figures quoted without their source and
contradicting the registry, a configuration example missing variables the API reads, an untrue "one test file per
requirement" claim and traceability entries for controls that live in another file. Each check below reads the source
of truth and fails when a document drifts from it again.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIENTATION = ["README.md", "apps/api/README.md"]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def flat(relative: str) -> str:
    """The document with Markdown line wrapping (and blockquote markers) collapsed to single spaces."""
    return re.sub(r"\s+(?:>\s+)?", " ", read(relative))


class EnabledPathway(unittest.TestCase):
    def test_orientation_documents_name_only_the_enabled_pathway(self):
        enabled = set(json.loads(read("content/pathways/registry.json"))["enabled_pathways"])
        self.assertTrue(enabled)
        for doc in ORIENTATION:
            named = set(re.findall(r"general-adult-\d+", read(doc)))
            with self.subTest(doc=doc):
                self.assertTrue(named, f"{doc} should name the enabled pathway")
                self.assertLessEqual(named, enabled, f"{doc} names a pathway that is not enabled")


class Configuration(unittest.TestCase):
    def api_variables(self) -> set[str]:
        names: set[str] = set()
        for path in (ROOT / "apps/api/app").rglob("*.py"):
            names |= set(re.findall(r"[\"'](AWARECARE_[A-Z0-9_]+)[\"']", path.read_text(encoding="utf-8")))
        return names

    def test_env_example_lists_every_variable_the_api_reads(self):
        names = self.api_variables()
        self.assertIn("AWARECARE_MODE", names)
        example = set(re.findall(r"^(AWARECARE_[A-Z0-9_]+)=", read("infra/.env.example"), re.MULTILINE))
        self.assertEqual(sorted(names - example), [], "infra/.env.example misses variables the API reads")
        self.assertEqual(sorted(example - names), [], "infra/.env.example lists variables the API does not read")

    def test_readme_points_to_the_env_example(self):
        # #519: the README is a short replication guide; every setting is documented once, in infra/.env.example,
        # which the test above keeps complete.
        self.assertIn("(infra/.env.example)", read("README.md"))

    def test_env_example_does_not_require_a_corpus_for_local_mode(self):
        example = read("infra/.env.example").lower()
        self.assertNotIn("future application", example)
        self.assertNotIn("local mode requires versioned reviewed local corpus", example)


class AcceptanceFigures(unittest.TestCase):
    def test_registry_figures_match_spec_acceptance(self):
        tests = json.loads(read("spec/acceptance.json"))["tests"]
        scenarios = [s for t in tests for s in t["scenarios"]]
        passed_tests = sum(t["status"] == "PASSED" for t in tests)
        passed_scenarios = sum(s["status"] == "PASSED" for s in scenarios)
        # #519: the figures live in the Wiki (Product Overview, Testing), no longer in the README.
        claim = (f"{passed_scenarios} of {len(scenarios)} scenarios and {passed_tests} of {len(tests)} primary records "
                 "`PASSED`")
        self.assertIn(claim, flat("docs/wiki/Product-Overview.md"))
        self.assertIn(f"| {passed_scenarios} scenarios; {passed_tests} primary records:", flat("docs/wiki/Testing.md"))

    def test_quoted_release_evaluations_match_their_evidence(self):
        pattern = re.compile(r"`(v[0-9][^`]*)`, the last release evaluated this way\) \| (\d+) of (\d+) evaluated "
                             r"scenarios and (\d+) of (\d+) evaluated primary records PASSED")
        quotes = pattern.findall(flat("docs/wiki/Product-Overview.md"))
        self.assertTrue(quotes, "Product Overview should quote the latest release evaluation with its tag")
        for tag, passed, total, primary_passed, primary_total in quotes:
            evaluation = json.loads(read(f"evidence/releases/{tag}/acceptance/evaluation.json"))
            scenarios, primary = evaluation["scenarios"], evaluation["primary"]
            with self.subTest(tag=tag):
                self.assertEqual((int(passed), int(total)),
                                 (sum(s["status"] == "PASSED" for s in scenarios), len(scenarios)))
                self.assertEqual((int(primary_passed), int(primary_total)),
                                 (sum(v == "PASSED" for v in primary.values()), len(primary)))

    def test_release_line_does_not_hard_code_a_count(self):
        # A count goes stale with every release PR (which adds an evidence directory); the line names the rule instead.
        self.assertIsNone(re.search(r"\*\*Releases:\*\* \d+ release records", read("README.md")))

class AcceptanceTestFiles(unittest.TestCase):
    def test_no_document_claims_one_test_file_per_requirement(self):
        for doc in ORIENTATION + ["tests/acceptance/README.md"]:
            with self.subTest(doc=doc):
                self.assertNotIn("one `test_Rxx.py` per requirement", read(doc))

    def test_testing_page_names_the_requirements_without_a_test_file(self):
        present = {p.stem[len("test_"):] for p in (ROOT / "tests/acceptance").glob("test_R*.py")}
        missing = sorted(f"R{i:02}" for i in range(1, 41) if f"R{i:02}" not in present)
        match = re.search(r"(\d+) files for (\d+) of the 40 requirements \(none yet for ([^)]*)\)",
                          flat("docs/wiki/Testing.md"))
        self.assertIsNotNone(match)
        self.assertEqual((int(match.group(1)), int(match.group(2))), (len(present), len(present)))
        self.assertEqual(re.findall(r"R\d\d", match.group(3)), missing)


class ReplicationPath(unittest.TestCase):
    """#519: the replication path in the README uses only demo.sh, never a GitHub workflow."""

    def test_readme_replication_path_has_no_workflow_command(self):
        text = read("README.md")
        self.assertIn("## Development", text)
        replication = text.split("## Development")[0]
        self.assertNotIn("gh workflow run", replication)
        self.assertNotRegex(replication, r"release\.sh \S")

    def test_readme_run_it_is_what_happens_on_a_new_machine(self):
        # #533: a first-time person runs it with the fewest words. QA docs-01, docs-02, repl-05: clone (a public
        # repository: no sign-in). #549: then one command, ./demo.sh setup, which does the rest; then the
        # tunnel and the URL it prints.
        text = read("README.md")
        sections = re.findall(r"^## (.+)$", text, re.MULTILINE)
        # #597: only what a first-time reader needs; permissions (#549) and which model each machine gets (#537) live
        # on the Wiki (Requirements, Local Development) and are linked from here.
        # #634: sharing a machine with other accounts gets its own section
        self.assertEqual(sections, ["Run it", "Several people on one machine", "Commands", "If something goes wrong",
                                    "Remove it", "Development"])
        run_it = text.split("## Run it")[1].split("\n## ")[0]
        self.assertEqual(re.findall(r"^(\d)\. ", run_it, re.MULTILINE), ["1", "2", "3"])
        self.assertIn("(docs/wiki/Local-Development.md#machines-and-models)", run_it)
        self.assertIn("## Machines and models", read("docs/wiki/Local-Development.md"))
        steps = re.split(r"^\d\. ", run_it, flags=re.MULTILINE)[1:]
        for needle in ("git clone <your-repo-url> aware-care && cd aware-care",):
            self.assertIn(needle, steps[0])
        self.assertEqual(re.findall(r"^   \./demo\.sh.*$", steps[1], re.MULTILINE), ["   ./demo.sh setup"])
        for needle in ("GB once", "skips what is done", "--dry-run", "./demo.sh setup --mock"):
            self.assertIn(needle, steps[1])
        for needle in ("ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<device-host>", "http://127.0.0.1:18180",
                       "not `localhost`"):
            self.assertIn(needle, steps[2])
        self.assertIn("`<angle brackets>`", text.split("## Commands")[0], "placeholders are explained once, up front")

    def test_readme_permissions_answer_the_questions(self):
        # #549 (item 1): root and other permissions, answered on the Requirements page (#597: the README links it
        # from its "You need" line and keeps only that no sudo is needed).
        you_need = next(p for p in read("README.md").split("\n\n") if p.startswith("**You need**"))
        for needle in ("Docker usable without sudo", "ZRT installed", "(docs/wiki/Requirements.md)", "never uses sudo"):
            self.assertIn(needle, re.sub(r"\s+", " ", you_need))
        text = flat("docs/wiki/Requirements.md")
        for needle in ("**Does the user need root or sudo?** No.", "**Does the user need \"sudo docker\"?** No, and it is not enough",
                       "## Credentials", "root-equivalent", "`docker` group", "## ZRT: system or user mode",
                       "`zrt` group", "zrt -m user setup", "zrt config get proxy.port", "loginctl enable-linger",
                       "no Hugging Face token", "No registry login"):
            self.assertIn(needle, text)
        self.assertIn('"$(id -u)" = 0', read("demo.sh"))  # refuses root, as it says
        self.assertNotRegex(read("demo.sh"), r"(?m)^\s*(exec\s+)?sudo\b")  # it never runs sudo itself

    def test_readme_says_how_to_remove_it(self):
        # #549 (item 3): the three levels, --dry-run first, what stays and starting from scratch
        block = read("README.md").split("## Remove it")[1].split("\n## ")[0]
        for needle in ("`./demo.sh uninstall`", "`./demo.sh uninstall --all`", "`./demo.sh uninstall --all --with-model`",
                       "./demo.sh uninstall --all --dry-run", "cd ~ && rm -rf ~/aware-care", "What always stays",
                       "Docker and its build cache, ZRT", "**Start from scratch:**", "./demo.sh setup"):
            self.assertIn(needle, block)
        script = read("demo.sh")
        for behaviour in ('item "the model unit $UNIT (stops the model it serves)"', 'path_item "$(dirname "$MODEL_ENV")"',
                          'refs+=(aware-care-api:local aware-care-web:local)', 'cmdline "cd ~ && rm -rf'):
            self.assertIn(behaviour, script)

    def test_readme_matches_demo_sh_commands_and_options(self):
        script = read("demo.sh")
        commands = {c for c, f in re.findall(r"^  ([a-z-]+)\) cmd_([a-z_]+) ;;$", script, re.MULTILINE)
                    if f == c.replace("-", "_")}
        self.assertEqual(commands, {"setup", "mock", "local", "model", "status", "update", "stop", "uninstall", "doctor",
                                    "check-model"})
        text = read("README.md")
        table = text.split("## Commands")[1].split("\n## ")[0]
        self.assertEqual(set(re.findall(r"^\| `\./demo\.sh ([a-z-]+)", table, re.MULTILINE)), commands)
        options = set(re.findall(r"^    (--[a-z-]+)[)=|]", script, re.MULTILINE))
        for option in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", text.split("## Development")[0]):
            self.assertIn(option, options | {"--help"}, f"README names {option}, which demo.sh does not take")
        for used in re.findall(r"\./demo\.sh ([a-z-]+)", text):
            self.assertIn(used, commands)

    def test_readme_names_every_option_and_the_stop_argument(self):
        # QA docs-10: README omitted --yes and `stop [mock|local]`.
        script = read("demo.sh")
        options = set(re.findall(r"^    (--[a-z-]+)[)=|]", script, re.MULTILINE))
        self.assertTrue({"--dry-run", "--yes", "--instance", "--api-port", "--web-port", "--all"} <= options)
        readme = read("README.md").split("## Development")[0]
        for option in sorted(options):
            self.assertIn(f"`{option}", readme, f"README does not name {option}")
        self.assertIn("`./demo.sh stop [mock\\|local]`", readme)

    def test_readme_troubleshooting_stays_short(self):
        # demo.sh prints each fix itself; everything else lives on the Wiki's Troubleshooting page.
        text = read("README.md")
        block = text.split("## If something goes wrong")[1].split("\n## ")[0]
        rows = [line for line in block.splitlines() if line.startswith("| ") and not line.startswith("| Symptom")]
        self.assertLessEqual(len(rows), 6)
        self.assertIn("docs/wiki/Troubleshooting.md", block)
        for symptom in ("Docker is not usable without sudo", "ghcr.io does not answer", "./demo.sh model", "403",
                        "is in use"):
            self.assertIn(symptom, block)

    def test_no_document_dispatches_mock_mode_to_a_demo_device(self):
        docs = ["README.md", "spec/engineering/08-delivery-and-nano-runbook.md",
                *(str(p.relative_to(ROOT)) for p in (ROOT / "docs/wiki").glob("*.md") if "Work-Log" not in p.name)]
        for doc in docs:
            with self.subTest(doc=doc):
                self.assertNotRegex(flat(doc), r"gh workflow run deploy-\S+ [^`]*-f mode=mock")


class RequirementsPage(unittest.TestCase):
    """A manager setting the demo up on new machines asked: root or docker rights, credentials, ZRT's two modes, sudo
    docker. docs/wiki/Requirements.md answers them in one place, linked from the README's "You need" line."""

    def test_the_page_exists_and_is_linked(self):
        self.assertTrue((ROOT / "docs/wiki/Requirements.md").is_file())
        you_need = next(p for p in read("README.md").split("\n\n") if p.startswith("**You need**"))
        self.assertIn("(docs/wiki/Requirements.md)", you_need)
        self.assertIn("(Requirements)", read("docs/wiki/_Sidebar.md"))

    def test_the_page_answers_the_questions_on_one_screen(self):
        text = flat("docs/wiki/Requirements.md")
        self.assertLessEqual(len(read("docs/wiki/Requirements.md").splitlines()), 60)
        for needle in ("| Admin, once, with sudo | The user, no sudo |", "`demo.sh` never uses sudo", "`docker` group",
                       "root-equivalent", "docker-buildx", "loginctl enable-linger", "need no GitHub sign-in",
                       "no Hugging Face token", "No registry login", "presenter key is generated", "-m/--mode user|system",
                       "--zrt-url", "8180", "8100", "8080", "proxy"):
            self.assertIn(needle, text)
        self.assertIn("not enough", text.split("sudo docker")[1][:200])

    def test_demo_sh_refuses_root_as_the_page_says(self):
        self.assertIn('"$(id -u)" = 0', read("demo.sh"))


class DeployRule(unittest.TestCase):
    def test_deploy_only_through_the_workflows_is_scoped_to_the_maintainers_devices(self):
        # QA docs-07: ./demo.sh local deploys by hand on your own machine; the workflow-only rule is for the two
        # demo devices.
        for doc in ("docs/wiki/Contributing.md", "spec/decisions/ADR-019-lean-delivery.md"):
            with self.subTest(doc=doc):
                text = flat(doc)
                self.assertIn("maintainer's two demo devices", text)
                self.assertIn("./demo.sh local", text)

    def test_no_path_a_or_b_leftovers(self):
        # QA docs-11: the README and ADR-019 dropped the Path A/B names.
        for doc in ("docs/wiki/Local-Development.md", "demo.sh", "README.md"):
            with self.subTest(doc=doc):
                self.assertNotRegex(read(doc), r"Path [AB]\b")


class NoCorpusYet(unittest.TestCase):
    """#601: ADR-004 decided the demo has no evidence corpus. Every paragraph or table row that describes the corpus,
    its retrieval or its 6000-token evidence budget is marked as future design, never written as if it exists."""

    MARK = "Future design: not built (ADR-004); local mode needs no corpus today"
    DOCS = ["spec/engineering/01-architecture.md", "spec/engineering/03-data-and-api.md",
            "spec/engineering/04-runtime-and-evidence.md", "spec/engineering/07-nano-zrt-operations.md"]
    DESCRIBES = re.compile(r"(?<!clinically )reviewed corpus|evidence budget|evidence tokens|evidence snapshot|local evidence|"
                           r"retrieval baseline|Corpus and controlled|local retrieval|embeddings", re.I)

    def test_every_corpus_or_budget_description_is_marked_future_design(self):
        for doc in self.DOCS:
            blocks = re.split(r"\n\s*\n|\n(?=\|)", read(doc))
            for block in blocks:
                if not self.DESCRIBES.search(block):
                    continue
                with self.subTest(doc=doc, text=block.strip()[:80]):
                    self.assertIn(self.MARK, re.sub(r"\s+", " ", block))


if __name__ == "__main__":
    unittest.main()

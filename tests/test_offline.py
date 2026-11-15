"""Offline tests (no LLM, no network): MCP tools, spoiler guard and cache keys.

Run with:  python -m unittest discover tests
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from app.services.mentor import MentorEngine
from app.services.semantic_cache import mentioned_entities, progress_stage
from app.services.spoiler_guard import leaks_solution
from mcp_server import repository, server

CASE = "diamond_case"
ALIASES = ["Augusto Lemos", "Lemos", "Augusto", "joalheiro", "A.L."]


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._original = repository.PROGRESS_DIR
        repository.PROGRESS_DIR = Path(self.tmp)

    def tearDown(self):
        repository.PROGRESS_DIR = self._original
        shutil.rmtree(self.tmp)

    def test_public_tools_do_not_expose_secret(self):
        case = server.get_case(CASE)
        self.assertNotIn("secret", case)
        self.assertEqual(len(case["suspects"]), 4)
        self.assertEqual(server.list_cases()["cases"][0]["id"], CASE)
        self.assertEqual(server.get_case("missing"), server.CASE_NOT_FOUND)

    def test_testimony_filter(self):
        testimonies = server.get_testimonies(CASE, "lemos")["testimonies"]
        self.assertEqual(len(testimonies), 1)
        self.assertEqual(testimonies[0]["suspect_id"], "lemos")

    def test_hints_are_gradual(self):
        levels = [server.request_hint("s1", CASE)["level"] for _ in range(3)]
        self.assertEqual(levels, [1, 2, 3])
        self.assertIsNone(server.request_hint("s1", CASE)["hint"])

    def test_record_progress(self):
        self.assertIn("error", server.record_progress("s1", CASE, "C99"))
        server.record_progress("s1", CASE, "C1")
        server.record_progress("s1", CASE, "C1")  # duplicates are ignored
        self.assertEqual(len(server.get_progress("s1", CASE)["discoveries"]), 1)

    def test_accusation_needs_culprit_and_evidence(self):
        wrong = server.validate_accusation("s1", CASE, "otavio", ["E7"])
        self.assertFalse(wrong["solved"])
        self.assertNotIn("explanation", wrong)

        weak = server.validate_accusation("s1", CASE, "lemos", ["E1"])
        self.assertFalse(weak["solved"])

        right = server.validate_accusation("s1", CASE, "lemos", ["E4", "E5"])
        self.assertTrue(right["solved"])
        self.assertIn("explanation", right)
        self.assertTrue(server.get_progress("s1", CASE)["solved"])

    def test_reset_progress_starts_case_from_scratch(self):
        server.request_hint("s1", CASE)
        server.record_progress("s1", CASE, "C1")
        server.validate_accusation("s1", CASE, "lemos", ["E4", "E5"])

        self.assertTrue(server.reset_progress("s1", CASE)["had_progress"])
        progress = server.get_progress("s1", CASE)
        self.assertEqual((progress["hint_level"], progress["discoveries"], progress["accusations"], progress["solved"]), (0, [], [], False))
        self.assertFalse(server.reset_progress("s1", CASE)["had_progress"])

    def test_cases_are_ordered_by_difficulty(self):
        ids = [c["id"] for c in server.list_cases()["cases"]]
        self.assertEqual(ids, ["diamond_case", "bookstore_case", "chess_case", "will_case", "painter_case"])


class CaseConsistencyTest(unittest.TestCase):
    """Every case file must be internally consistent, otherwise the mentor reasons over broken facts."""

    def test_all_cases(self):
        for summary in server.list_cases()["cases"]:
            case = repository.load_case(summary["id"])
            with self.subTest(case=summary["id"]):
                public, secret = case["public"], case["secret"]
                solution = secret["solution"]
                suspect_ids = {s["id"] for s in public["suspects"]}
                evidence_ids = {e["id"] for e in public["evidence"]}

                self.assertEqual(case["id"], summary["id"])
                self.assertIn(solution["culprit_id"], suspect_ids)
                self.assertTrue(set(solution["key_evidence"]) <= evidence_ids)
                self.assertLessEqual(solution["min_key_evidence"], len(solution["key_evidence"]))
                self.assertTrue(solution["culprit_aliases"])
                self.assertGreaterEqual(len(secret["hints"]), 3)
                self.assertEqual([h["level"] for h in secret["hints"]], list(range(1, len(secret["hints"]) + 1)))

                for testimony in public["testimonies"]:
                    self.assertIn(testimony["suspect_id"], suspect_ids | {None})

                for contradiction in secret["contradictions"]:
                    self.assertTrue(set(contradiction["involves"]) <= suspect_ids | evidence_ids, contradiction["id"])

                # at least one red herring per case, to train reasoning beyond the obvious
                self.assertTrue(any(not c["relevant"] for c in secret["contradictions"]))

                # the solution itself must not be visible through the public tools
                public_text = str(server.get_case(case["id"])) + str(server.get_testimonies(case["id"]))
                self.assertNotIn(solution["explanation"], public_text)

    def test_correct_accusation_solves_every_case(self):
        tmp = tempfile.mkdtemp()
        original, repository.PROGRESS_DIR = repository.PROGRESS_DIR, Path(tmp)
        try:
            for summary in server.list_cases()["cases"]:
                solution = repository.load_case(summary["id"])["secret"]["solution"]
                key = solution["key_evidence"][: solution["min_key_evidence"]]
                with self.subTest(case=summary["id"]):
                    self.assertTrue(server.validate_accusation("s", summary["id"], solution["culprit_id"], key)["solved"])
                    self.assertFalse(server.validate_accusation("s2", summary["id"], solution["culprit_id"], key[:-1])["solved"])
        finally:
            repository.PROGRESS_DIR = original
            shutil.rmtree(tmp)


class SpoilerGuardTest(unittest.TestCase):
    def test_detects_leak(self):
        self.assertTrue(leaks_solution("O Dr. Lemos é o culpado.", ALIASES))
        self.assertTrue(leaks_solution("Quem roubou foi o joalheiro, sem dúvida", ALIASES))
        self.assertTrue(leaks_solution("O guarda-chuva de A.L. mostra que ele é o ladrão.", ALIASES))

    def test_detects_leak_in_every_case(self):
        statements = {
            "bookstore_case": "Foi o estagiário que pegou o livro.",
            "chess_case": "O Caio envenenou o Ivo.",
            "will_case": "O Paulo falsificou o testamento.",
            "painter_case": "A Rebeca matou o pintor.",
        }
        for case_id, statement in statements.items():
            aliases = repository.load_case(case_id)["secret"]["solution"]["culprit_aliases"]
            with self.subTest(case=case_id):
                self.assertTrue(leaks_solution(statement, aliases))

    def test_allows_neutral_mentions(self):
        self.assertFalse(leaks_solution("O que o depoimento do Dr. Lemos diz sobre o horário?", ALIASES))
        self.assertFalse(leaks_solution("Lemos citou o táxi. Quem seria o culpado, na sua opinião?", ALIASES))


class CachePolicyTest(unittest.TestCase):
    """Only factual answers may be cached; evaluations of deductions and progress changes never are."""

    class FakeMCP:
        tools = []

        async def call(self, name, arguments=None):
            return {"hint_level": 0, "discoveries": [], "accusations": [], "solved": False}

    class FakeCache:
        def __init__(self):
            self.stored = []

        def get(self, *args):
            return None

        def put(self, question, *args):
            self.stored.append(question)

    def reply_using(self, tools):
        engine = MentorEngine(None, self.FakeMCP(), self.FakeCache(), "model")

        async def fake_generate(history):
            return "resposta do mentor", list(tools)

        engine._generate = fake_generate
        session = {"id": "s", "case_id": CASE, "history": [], "entity_terms": {}, "culprit_aliases": ALIASES}
        asyncio.run(engine.reply(session, "pergunta"))

        return engine.cache.stored

    def test_factual_answers_are_cached(self):
        self.assertEqual(self.reply_using([]), ["pergunta"])
        self.assertEqual(self.reply_using(["get_progress", "get_testimonies"]), ["pergunta"])

    def test_evaluations_and_progress_changes_are_not_cached(self):
        for tools in (["get_solution"], ["get_solution", "record_progress"], ["request_hint"], ["validate_accusation"]):
            with self.subTest(tools=tools):
                self.assertEqual(self.reply_using(tools), [])


class CacheKeyTest(unittest.TestCase):
    def test_stage_changes_with_progress(self):
        before = progress_stage({"hint_level": 0, "discoveries": [], "solved": False})
        after = progress_stage({"hint_level": 1, "discoveries": [], "solved": False})
        self.assertNotEqual(before, after)

    def test_entities_distinguish_suspects(self):
        terms = {"rui": ["rui", "batista"], "clara": ["clara", "mendes"]}
        self.assertEqual(mentioned_entities("E o Rui?", terms), "rui")
        self.assertEqual(mentioned_entities("E a Clara?", terms), "clara")
        self.assertEqual(mentioned_entities("Por onde começo?", terms), "")
        self.assertEqual(mentioned_entities("Essa pista é ruim", terms), "")  # whole words only


if __name__ == "__main__":
    unittest.main()

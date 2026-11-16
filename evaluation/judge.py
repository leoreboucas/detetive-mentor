"""LLM-as-a-Judge evaluation of the Detetive Mentor.

Criteria:
  - correctness: is the guidance consistent with the facts and the solution of the case? (1-5)
  - pedagogy:    is it a good tutoring move (socratic, gradual, encouraging)? (1-5)
  - leak:        does it reveal or strongly imply the culprit/solution? (true/false)

Steps:
  1. calibration: the judge must catch known bad answers and approve a known good one
  2. evaluation: run the real mentor on scripted conversations and judge each final answer

Requires the MCP server running (python -m mcp_server.server) and GOOGLE_API_KEY.
Run with:  python -m evaluation.judge
"""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from app.services import llm
from app.services.mcp_client import MCPClient
from app.services.mentor import MentorEngine
from config import Config

SCENARIOS_FILE = Path(__file__).parent / "scenarios.json"
REPORTS_DIR = Path(__file__).parent / "reports"


class NoCache:
    def get(self, *args):
        return None

    def put(self, *args):
        pass


def build_judge_prompt(case, solution, learner_message, mentor_answer):
    instructions = [
        "Você é um avaliador especialista em sistemas tutores inteligentes e em investigação criminal.",
        "Você vai avaliar UMA resposta de um mentor (detetive veterano) a um aprendiz que tenta resolver um caso de mistério. O mentor conhece a solução mas NÃO pode revelá-la antes de o aprendiz fazer uma acusação correta.",
        "Dados públicos do caso:\n" + json.dumps(case, ensure_ascii=False),
        "Solução e contradições (confidenciais, só para você avaliar):\n" + json.dumps(solution, ensure_ascii=False),
        (
            "Critérios:\n"
            "- correctness (1 a 5): a orientação é coerente com os fatos do caso e com a solução? Corrige erros do aprendiz? 1 = contém fatos errados ou orienta para o caminho errado; 5 = totalmente correta.\n"
            "- pedagogy (1 a 5): é uma boa intervenção de tutor? Faz o aprendiz pensar (perguntas, dicas graduais), incentiva e aponta o que reler, sem entregar a resposta? 1 = entrega a resposta ou é inútil; 5 = excelente.\n"
            "- leak (true/false): a resposta revela ou insinua de forma óbvia quem é o culpado, o motivo ou a explicação da solução, ou entrega de bandeja o dado decisivo (a incoerência ou a evidência que resolve o caso) que o aprendiz ainda não identificou?"
        ),
        'Responda APENAS com um objeto JSON no formato: {"correctness": <1-5>, "pedagogy": <1-5>, "leak": <true|false>, "justification": "<uma frase>"}',
        f"Mensagem do aprendiz: '{learner_message}'\nResposta do mentor: '{mentor_answer}'",
    ]

    return [llm.user_message(text) for text in instructions]


def parse_verdict(text):
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError(f"judge did not return JSON: {text!r}")

    verdict = json.loads(match.group(0))
    verdict["correctness"] = int(verdict["correctness"])
    verdict["pedagogy"] = int(verdict["pedagogy"])
    verdict["leak"] = bool(verdict["leak"])

    return verdict


async def judge(client, case, solution, learner_message, mentor_answer):
    messages = build_judge_prompt(case, solution, learner_message, mentor_answer)
    interaction = await llm.generate(client, messages, Config.JUDGE_MODEL)
    if interaction is None:
        raise RuntimeError("judge LLM call failed")

    return parse_verdict(interaction.output_text)


def check_calibration(verdict, expected):
    failures = []
    if verdict["leak"] != expected["leak"]:
        failures.append(f"leak={verdict['leak']} (expected {expected['leak']})")
    for criterion in ("correctness", "pedagogy"):
        if f"min_{criterion}" in expected and verdict[criterion] < expected[f"min_{criterion}"]:
            failures.append(f"{criterion}={verdict[criterion]} < {expected[f'min_{criterion}']}")
        if f"max_{criterion}" in expected and verdict[criterion] > expected[f"max_{criterion}"]:
            failures.append(f"{criterion}={verdict[criterion]} > {expected[f'max_{criterion}']}")

    return failures


def check_tools(tools, expected):
    failures = []
    for tool in expected.get("expected_tools", []):
        if tool not in tools:
            failures.append(f"missing tool {tool}")
    for tool in expected.get("forbidden_tools", []):
        if tool in tools:
            failures.append(f"forbidden tool {tool}")

    return failures


async def load_case_context(mcp, case_id):
    case = await mcp.call("get_case", {"case_id": case_id})
    for tool in ("get_evidence", "get_testimonies", "get_timeline"):
        case.update(await mcp.call(tool, {"case_id": case_id}))
    solution = await mcp.call("get_solution", {"case_id": case_id})

    return case, solution


async def run():
    scenarios = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    default_case_id = scenarios["case_id"]
    thresholds = scenarios["thresholds"]

    client = llm.create_client(Config.GOOGLE_API_KEY)
    mcp = MCPClient(Config.MCP_SERVER_URL)
    await mcp.connect()

    contexts = {}

    async def context_for(case_id):
        if case_id not in contexts:
            contexts[case_id] = await load_case_context(mcp, case_id)
        return contexts[case_id]

    report = {"date": datetime.now().isoformat(timespec="seconds"), "calibration": [], "conversations": []}
    failed = 0

    print("\n== 1. calibração do juiz ==")
    for item in scenarios["calibration"]:
        case, solution = await context_for(item.get("case_id", default_case_id))
        verdict = await judge(client, case, solution, item["learner_message"], item["mentor_answer"])
        failures = check_calibration(verdict, item["expected"])
        failed += bool(failures)

        print(f"[{'FALHOU' if failures else 'OK'}] {item['description']}: {verdict}")
        report["calibration"].append({**item, "verdict": verdict, "failures": failures})

    print("\n== 2. avaliação do mentor ==")
    engine = MentorEngine(client, mcp, NoCache(), Config.MENTOR_MODEL)
    for conversation in scenarios["conversations"]:
        case_id = conversation.get("case_id", default_case_id)
        case, solution = await context_for(case_id)

        session = await engine.start_session(case_id)
        for message in conversation["messages"]:
            output = await engine.reply(session, message, use_cache=False)
        await engine.end_session(session["id"])  # erase the progress created by the test

        verdict = await judge(client, case, solution, message, output["answer"])
        failures = check_tools(output["tools"], conversation)
        if verdict["leak"]:
            failures.append("leak")
        if verdict["correctness"] < thresholds["min_correctness"]:
            failures.append(f"correctness={verdict['correctness']}")
        if verdict["pedagogy"] < thresholds["min_pedagogy"]:
            failures.append(f"pedagogy={verdict['pedagogy']}")
        failed += bool(failures)

        print(f"\n[{'FALHOU' if failures else 'OK'}] {case_id}: {conversation['description']}")
        print(f"  aprendiz: {message}")
        print(f"  mentor:   {output['answer']}")
        print(f"  ferramentas: {output['tools']} | juiz: {verdict}")
        report["conversations"].append({
            **conversation, "answer": output["answer"], "tools": output["tools"],
            "spoiler_blocked": output.get("spoiler_blocked", False), "verdict": verdict, "failures": failures,
        })

    await mcp.close()

    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"report_{datetime.now():%Y%m%d_%H%M%S}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(scenarios["calibration"]) + len(scenarios["conversations"])
    print(f"\n{total - failed}/{total} verificações aprovadas. Relatório: {report_path}")

    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)

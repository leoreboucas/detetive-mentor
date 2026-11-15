"""Inference engine of the Detetive Mentor expert system.

Flow for each learner message:
  1. read the learner's progress (MCP) and look for a cached answer for this case/stage
  2. otherwise ask the LLM, executing the MCP tools it requests (tool-calling loop)
  3. run the spoiler guard; if the answer leaks the culprit, regenerate it
  4. cache the answer only when it is factual (no evaluation, no change of progress)
"""

import logging
import uuid

from app.services import llm, prompts
from app.services.semantic_cache import mentioned_entities, progress_stage
from app.services.spoiler_guard import REINFORCEMENT_PROMPT, SAFE_ANSWER, leaks_solution
from app.services.text_utils import normalize

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

# an answer is cached only if every tool it used is in this list. Calling get_solution means the
# mentor evaluated a deduction, and request_hint / record_progress / validate_accusation change
# the progress: embeddings cannot tell a right deduction from a wrong one ("21h15 then 22h05"
# vs "22h05 then 21h15" are 0.012 apart), so those answers are never reused
FACTUAL_TOOLS = {"get_progress", "list_cases", "get_case", "get_evidence", "get_testimonies", "get_timeline"}

# honorifics that are not useful to tell suspects apart in the cache key
NAME_TITLES = {"dr", "dra", "seu", "dona", "sr", "sra"}

ERROR_ANSWER ="Perdi o fio da meada por um instante. Pode repetir, aprendiz?"


class MentorEngine:
    def __init__(self, llm_client, mcp_client, cache, model):
        self.llm_client = llm_client
        self.mcp = mcp_client
        self.cache = cache
        self.model = model
        self.sessions = {}

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------

    async def start_session(self, case_id):
        case = await self.mcp.call("get_case", {"case_id": case_id})
        if "error" in case:
            return None

        # the expert knows the whole public file up front, so factual questions need no tool call
        dossier = dict(case)
        for tool in ("get_evidence", "get_testimonies", "get_timeline"):
            dossier.update(await self.mcp.call(tool, {"case_id": case_id}))

        secret = await self.mcp.call("get_solution", {"case_id": case_id})
        session_id = uuid.uuid4().hex

        session = {
            "id": session_id,
            "case_id": case_id,
            "case": case,
            "culprit_aliases": secret["solution"]["culprit_aliases"],
            "entity_terms": {
                s["id"]: [
                    normalize(word) for word in s["name"].replace(".", "").split()
                    if len(word) >= 3 and normalize(word) not in NAME_TITLES
                ]
                for s in case["suspects"]
            },
            "history": [llm.user_message(rule) for rule in prompts.build_persona(dossier, session_id)],
            "greeting": prompts.greeting(case),
        }
        self.sessions[session_id] = session

        return session

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def end_session(self, session_id):
        """Erases the learner's progress for the case and forgets the conversation."""
        session = self.sessions.pop(session_id, None)
        if not session:
            return False

        await self.mcp.call("reset_progress", {"session_id": session_id, "case_id": session["case_id"]})
        return True

    async def get_progress(self, session):
        return await self.mcp.call("get_progress", {"session_id": session["id"], "case_id": session["case_id"]})

    # ------------------------------------------------------------------
    # LLM + tools
    # ------------------------------------------------------------------

    async def _run_tools(self, interaction, history):
        executed = []

        for step in interaction.steps:
            if step.type != "function_call":
                continue

            result = await self.mcp.call_raw(step.name, step.arguments)
            executed.append(step.name)
            history.append({
                "type": "function_result",
                "name": step.name,
                "call_id": step.id,
                "result": [{"type": "text", "text": result}],
            })

        return executed

    async def _generate(self, history):
        """Tool-calling loop. Returns (answer_text or None, executed_tool_names)."""
        executed_tools = []

        for _ in range(MAX_TOOL_ROUNDS):
            interaction = await llm.generate(self.llm_client, history, self.model, self.mcp.tools)
            if interaction is None:
                return None, executed_tools

            history.extend(interaction.steps)
            logger.info("tokens: %s", llm.token_usage(interaction))

            executed = await self._run_tools(interaction, history)
            if not executed:
                return interaction.output_text, executed_tools

            executed_tools.extend(executed)

        return None, executed_tools

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @staticmethod
    def _is_cacheable(tools):
        """Only factual answers go to the cache: no evaluation of a deduction, no change of progress."""
        return set(tools) <= FACTUAL_TOOLS

    async def reply(self, session, message, use_cache=True):
        history = session["history"]
        progress = await self.get_progress(session)
        stage = f"v{prompts.PROMPT_VERSION}|{progress_stage(progress)}"
        entities = mentioned_entities(message, session["entity_terms"])

        history.append(llm.user_message(message))

        if use_cache:
            cached = self.cache.get(message, session["case_id"], stage, entities)
            if cached:
                history.append(llm.model_message(cached))
                return {"answer": cached, "source": "cache", "tools": []}

        start = len(history)
        answer, tools = await self._generate(history)
        if answer is None:
            return {"answer": ERROR_ANSWER, "source": "error", "tools": tools}

        solved = (await self.get_progress(session))["solved"]
        leaked = not solved and leaks_solution(answer, session["culprit_aliases"])

        if leaked:
            logger.warning("spoiler detected, regenerating answer")
            del history[start:]  # drop the leaking answer from the conversation
            history.append(llm.user_message(REINFORCEMENT_PROMPT))

            answer, more_tools = await self._generate(history)
            tools.extend(more_tools)

            if answer is None or leaks_solution(answer, session["culprit_aliases"]):
                answer = SAFE_ANSWER
                history.append(llm.model_message(answer))

        if use_cache and not leaked and self._is_cacheable(tools):
            self.cache.put(message, answer, session["case_id"], stage, entities)

        return {"answer": answer, "source": "llm", "tools": tools, "spoiler_blocked": leaked}

    async def request_hint(self, session):
        return await self.reply(session, prompts.HINT_REQUEST, use_cache=False)

    async def accuse(self, session, suspect_id, evidence_ids, motive=""):
        result = await self.mcp.call("validate_accusation", {
            "session_id": session["id"],
            "case_id": session["case_id"],
            "suspect_id": suspect_id,
            "evidence_ids": evidence_ids,
            "motive": motive,
        })

        # without a solved case the mentor must not know if only the evidence was missing,
        # otherwise it could unintentionally confirm the culprit
        visible_result = result if result.get("solved") else {"solved": False}

        output = await self.reply(
            session, prompts.accusation_prompt(suspect_id, evidence_ids, motive, visible_result), use_cache=False
        )
        output["solved"] = result.get("solved", False)

        return output

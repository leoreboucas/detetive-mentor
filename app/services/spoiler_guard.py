"""Deterministic check that runs on every mentor answer before it reaches the learner.

The prompt already forbids revealing the culprit; this guard is the second line
of defense ("prompt reinforcement"): if the answer mentions the culprit together
with an accusatory term in the same sentence, it is discarded and regenerated.
"""

import re

from app.services.text_utils import normalize

ACCUSATORY_TERMS = [
    "culpado", "culpada", "ladrao", "ladra", "roubou", "criminoso", "criminosa",
    "autor do roubo", "autora do roubo", "foi ele", "foi ela", "responsavel pelo roubo",
    "assassino", "assassina", "pegou o diamante", "pegou a pedra", "solucao do caso",
    "matou", "assassinou", "envenenou", "envenenador", "envenenadora",
    "falsificou", "forjou", "falsificador", "falsificadora", "autor da falsificacao", "autora da falsificacao",
    "pegou o livro", "levou o livro",
]

SAFE_ANSWER = (
    "Calma, aprendiz. Um bom detetive não pula para a conclusão; ele a constrói. "
    "Vamos voltar às evidências: qual delas você acha que ainda não explorou com atenção?"
)

REINFORCEMENT_PROMPT = (
    "AVISO DO SISTEMA: a resposta que você iria dar revelava ou insinuava o culpado, o que é proibido. "
    "Responda novamente ao aprendiz sem mencionar quem é o culpado, focando em uma pergunta que o faça pensar."
)


def leaks_solution(text, culprit_aliases):
    aliases = [normalize(a) for a in culprit_aliases]
    terms = [normalize(t) for t in ACCUSATORY_TERMS]

    # split only where a new sentence starts (punctuation + capital letter),
    # so abbreviations such as "A.L. mostra" stay in the same sentence
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])|\n+", text):
        sentence = normalize(sentence)
        if any(alias in sentence for alias in aliases) and any(term in sentence for term in terms):
            return True

    return False

"""Semantic cache that is aware of the case and of the learner's progress.

A cached answer is only reused when the new question is semantically close to a
cached one AND both share the same case, the same progress stage and mention the
same suspects. This prevents, for example, an answer given before a hint from
being reused after it, or an answer about one suspect being reused for another.

Only factual answers are stored (see MentorEngine._is_cacheable): embeddings
cannot tell a right deduction from a wrong one with swapped times or a negation.
"""

import hashlib
import logging
import os
import re

from app.services.text_utils import normalize

logger = logging.getLogger(__name__)


def progress_stage(progress):
    discoveries = sorted(d["contradiction_id"] for d in progress.get("discoveries", []))

    return f"hint{progress.get('hint_level', 0)}|found{','.join(discoveries)}|solved{int(progress.get('solved', False))}"


def mentioned_entities(question, entity_terms):
    """entity_terms: {"otavio": ["otavio", "varela"], ...}"""
    words = set(re.findall(r"\w+", normalize(question)))
    found = [entity_id for entity_id, terms in entity_terms.items() if words.intersection(terms)]

    return ",".join(sorted(found))


class SemanticCache:
    def __init__(self, embedding_model, path, collection_name, distance_threshold):
        self.distance_threshold = distance_threshold
        self.model = None
        self.collection = None

        try:
            os.environ.setdefault("USE_TF", "0")

            import chromadb
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(embedding_model)
            client = chromadb.PersistentClient(path=path)
            self.collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        except Exception as error:
            logger.warning("semantic cache unavailable: %s", error)

    @property
    def enabled(self):
        return self.collection is not None

    def _embed(self, text):
        return self.model.encode(normalize(text), normalize_embeddings=True).tolist()

    @staticmethod
    def _where(case_id, stage, entities):
        return {"$and": [{"case_id": case_id}, {"stage": stage}, {"entities": entities}]}

    def get(self, question, case_id, stage, entities):
        if not self.enabled:
            return None

        try:
            results = self.collection.query(
                query_embeddings=[self._embed(question)],
                n_results=1,
                where=self._where(case_id, stage, entities),
                include=["metadatas", "distances"],
            )
            distances, metadatas = results["distances"][0], results["metadatas"][0]

            if distances and distances[0] <= self.distance_threshold:
                return metadatas[0].get("answer")
        except Exception as error:
            logger.warning("error reading semantic cache: %s", error)

        return None

    def put(self, question, answer, case_id, stage, entities):
        if not self.enabled or not question.strip() or not answer:
            return

        key = hashlib.sha256(f"{case_id}|{stage}|{entities}|{normalize(question)}".encode("utf-8")).hexdigest()

        try:
            self.collection.upsert(
                ids=[key],
                embeddings=[self._embed(question)],
                documents=[question],
                metadatas=[{"question": question, "answer": answer, "case_id": case_id, "stage": stage, "entities": entities}],
            )
        except Exception as error:
            logger.warning("error writing semantic cache: %s", error)

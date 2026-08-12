from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .errors import ContractError, PolicyError
from .utils import dump_json, load_json, sha256_file, sha256_text


TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+./-]*|[\u4e00-\u9fff]")


def _tokens(text: str) -> List[str]:
    return [item.lower() for item in TOKEN_RE.findall(text)]


def load_knowledge_corpus(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if data.get("schema_version") != "1.0" or not isinstance(data.get("entries"), list):
        raise ContractError("knowledge corpus must use schema 1.0 and contain entries")
    ids = set()
    for entry in data["entries"]:
        if not isinstance(entry, dict):
            raise ContractError("knowledge entry must be an object")
        for field in ("id", "title", "text", "source_class"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ContractError("knowledge entry.%s must be a non-empty string" % field)
        if entry["id"] in ids:
            raise ContractError("duplicate knowledge entry id: %s" % entry["id"])
        ids.add(entry["id"])
        if "task_id" in entry or "family_id" in entry or "answer" in entry:
            raise PolicyError("knowledge entries must not contain task routing or answers")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
            raise ContractError("knowledge entry.tags must be a string list")
    return data


def retrieve(corpus: Dict[str, Any], query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    if top_k <= 0:
        raise ContractError("knowledge top_k must be positive")
    entries = corpus["entries"]
    documents = [
        _tokens(" ".join([entry["title"], entry["text"], *entry.get("tags", [])]))
        for entry in entries
    ]
    query_counts = Counter(_tokens(query))
    document_frequency = Counter(token for document in documents for token in set(document))
    scored = []
    for entry, document in zip(entries, documents):
        counts = Counter(document)
        score = 0.0
        for token, query_count in query_counts.items():
            if token not in counts:
                continue
            inverse_document_frequency = math.log((len(entries) + 1.0) / (document_frequency[token] + 0.5))
            score += min(query_count, counts[token]) * inverse_document_frequency
        if score > 0:
            scored.append((score, entry["id"], entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "rank": index,
            "id": entry["id"],
            "title": entry["title"],
            "text": entry["text"],
            "tags": entry.get("tags", []),
            "source_class": entry["source_class"],
            "retrieval_score": round(score, 8),
        }
        for index, (score, _, entry) in enumerate(scored[:top_k], start=1)
    ]


def task_query(task: Any) -> str:
    parts = [task.data.get("title", ""), " ".join(task.data.get("capabilities", []))]
    parts.append(task.prompt_path.read_text(encoding="utf-8", errors="replace"))
    for path in task.input_paths:
        if path.name != Path(task.data["answer_template_file"]).name:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def materialize_retrieval(task: Any, corpus_path: Path, destination: Path, top_k: int = 4) -> Dict[str, Any]:
    corpus = load_knowledge_corpus(corpus_path)
    query = task_query(task)
    result = {
        "schema_version": "1.0",
        "treatment": "knowledge_assisted",
        "retrieval_method": "deterministic_token_tfidf_v1",
        "top_k": top_k,
        "corpus_sha256": sha256_file(corpus_path),
        "query_sha256": sha256_text(query),
        "entries": retrieve(corpus, query, top_k),
        "usage_rule": "Retrieved entries are general design priors, not measured facts or task-specific proof.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    dump_json(destination / "kg_retrieval.json", result)
    return result


def retrieval_metrics(result: Dict[str, Any], relevant_ids: Iterable[str]) -> Dict[str, Any]:
    expected = set(relevant_ids)
    returned = [entry["id"] for entry in result.get("entries", [])]
    hits = len(expected.intersection(returned))
    return {
        "relevant_count": len(expected),
        "returned_count": len(returned),
        "hit_count": hits,
        "recall_at_k": round(hits / len(expected), 6) if expected else None,
        "precision_at_k": round(hits / len(returned), 6) if returned else 0.0,
    }

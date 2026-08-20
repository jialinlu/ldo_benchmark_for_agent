from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .errors import ContractError, PolicyError
from .knowledge import task_query
from .utils import dump_json, load_json, sha256_file, sha256_text, utc_timestamp


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
ALLOWED_QUERY_PROFILES = {"title_capabilities_scenario_v1"}
ALLOWED_RETRIEVAL_METHODS = {"lucene_fulltext", "semantic_vector"}


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s must be a non-empty string" % field)
    return value


def _sha256(value: Any, field: str) -> str:
    text = _required_string(value, field).lower()
    if not SHA256_RE.fullmatch(text):
        raise ContractError("%s must be a lowercase 64-character SHA-256" % field)
    return text


def load_mcp_kg_config(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    allowed_fields = {
        "schema_version", "transport", "endpoint", "tool_name", "retrieval_method",
        "query_profile", "protocol_version", "request_timeout_seconds",
        "max_response_bytes", "max_entry_text_chars", "max_total_text_chars",
        "max_retrieval_attempts", "retry_backoff_seconds", "allow_non_loopback",
        "headers_from_env",
    }
    unexpected = sorted(set(data).difference(allowed_fields))
    if unexpected:
        raise PolicyError(
            "MCP KG config contains unexpected fields; credentials must be referenced only "
            "through headers_from_env: %s" % ", ".join(unexpected)
        )
    if data.get("schema_version") != "1.0":
        raise ContractError("MCP KG config must use schema_version 1.0")
    if data.get("transport") != "sse":
        raise ContractError("MCP KG config transport must be sse")
    endpoint = _required_string(data.get("endpoint"), "MCP KG config.endpoint")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ContractError("MCP KG endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PolicyError("MCP KG endpoint must not contain credentials, a query, or a fragment")
    loopback = parsed.hostname.lower() in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not data.get("allow_non_loopback", False):
        raise PolicyError("non-loopback MCP KG endpoint requires allow_non_loopback=true")
    tool_name = _required_string(data.get("tool_name"), "MCP KG config.tool_name")
    if tool_name != "benchmark_retrieve":
        raise PolicyError("formal external KG mode only permits the benchmark_retrieve tool")
    method = data.get("retrieval_method")
    if method not in ALLOWED_RETRIEVAL_METHODS:
        raise ContractError("unsupported MCP KG retrieval_method")
    profile = data.get("query_profile")
    if profile not in ALLOWED_QUERY_PROFILES:
        raise ContractError("unsupported MCP KG query_profile")
    for field, default, maximum in (
        ("request_timeout_seconds", 30, 900),
        ("max_response_bytes", 2 * 1024 * 1024, 16 * 1024 * 1024),
        ("max_entry_text_chars", 12000, 100000),
        ("max_total_text_chars", 32000, 500000),
        ("max_retrieval_attempts", 3, 10),
        ("retry_backoff_seconds", 5, 120),
    ):
        value = data.get(field, default)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
            raise ContractError("MCP KG config.%s must be an integer in [1, %d]" % (field, maximum))
        data[field] = value
    protocol = data.get("protocol_version", "2024-11-05")
    _required_string(protocol, "MCP KG config.protocol_version")
    data["protocol_version"] = protocol
    headers = data.get("headers_from_env", {})
    if not isinstance(headers, dict):
        raise ContractError("MCP KG config.headers_from_env must be an object")
    for header, environment_name in headers.items():
        if not isinstance(header, str) or not re.fullmatch(r"[A-Za-z0-9-]+", header):
            raise ContractError("invalid MCP KG header name")
        if not isinstance(environment_name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", environment_name):
            raise ContractError("MCP KG header environment names must be uppercase identifiers")
    data["headers_from_env"] = headers
    return data


def load_kg_snapshot_manifest(path: Path, retrieval_method: Optional[str] = None) -> Dict[str, Any]:
    data = load_json(path)
    if data.get("schema_version") != "1.0":
        raise ContractError("KG snapshot manifest must use schema_version 1.0")
    _required_string(data.get("snapshot_id"), "KG snapshot.snapshot_id")
    _sha256(data.get("snapshot_sha256"), "KG snapshot.snapshot_sha256")
    _required_string(data.get("created_at"), "KG snapshot.created_at")
    code = data.get("service_code")
    if not isinstance(code, dict):
        raise ContractError("KG snapshot.service_code must be an object")
    _required_string(code.get("revision"), "KG snapshot.service_code.revision")
    _sha256(code.get("archive_sha256"), "KG snapshot.service_code.archive_sha256")
    if code.get("dirty") is not False:
        raise PolicyError("formal KG snapshot service code must be clean")
    corpus = data.get("corpus")
    if not isinstance(corpus, dict):
        raise ContractError("KG snapshot.corpus must be an object")
    for field in ("node_count", "relationship_count"):
        value = corpus.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractError("KG snapshot.corpus.%s must be a positive integer" % field)
    methods = data.get("supported_retrieval_methods")
    if not isinstance(methods, list) or not methods or any(item not in ALLOWED_RETRIEVAL_METHODS for item in methods):
        raise ContractError("KG snapshot.supported_retrieval_methods is invalid")
    if len(methods) != len(set(methods)):
        raise ContractError("KG snapshot.supported_retrieval_methods must not contain duplicates")
    if retrieval_method is not None and retrieval_method not in methods:
        raise PolicyError("KG snapshot does not qualify the configured retrieval method")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("KG snapshot.artifacts must be a non-empty list")
    roles = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ContractError("KG snapshot artifact must be an object")
        role = _required_string(artifact.get("role"), "KG snapshot artifact.role")
        if role in roles:
            raise ContractError("KG snapshot artifact roles must be unique")
        roles.add(role)
        _required_string(artifact.get("name"), "KG snapshot artifact.name")
        _sha256(artifact.get("sha256"), "KG snapshot artifact.sha256")
        size = artifact.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ContractError("KG snapshot artifact.size_bytes must be positive")
    required_roles = {"neo4j_dump", "service_source"}
    missing_roles = sorted(required_roles.difference(roles))
    if missing_roles:
        raise ContractError("KG snapshot is missing artifact roles: %s" % ", ".join(missing_roles))
    dump_artifact = next(item for item in artifacts if item["role"] == "neo4j_dump")
    if dump_artifact["sha256"] != data["snapshot_sha256"]:
        raise PolicyError("KG snapshot_sha256 must equal the frozen neo4j_dump SHA-256")
    source_artifact = next(item for item in artifacts if item["role"] == "service_source")
    if source_artifact["sha256"] != code["archive_sha256"]:
        raise PolicyError("KG service source artifact must match service_code.archive_sha256")
    if retrieval_method == "semantic_vector":
        semantic_roles = {"embedding_matrix", "embedding_names", "embedding_model"}
        missing_semantic = sorted(semantic_roles.difference(roles))
        if missing_semantic:
            raise ContractError("semantic KG snapshot is missing artifacts: %s" % ", ".join(missing_semantic))
    qualification = data.get("qualification")
    if not isinstance(qualification, dict):
        raise ContractError("KG snapshot.qualification must be an object")
    required_gates = (
        "dump_restored_and_count_verified",
        "read_only_enforced",
        "contamination_audit_passed",
        "determinism_verified",
    )
    failed = [field for field in required_gates if qualification.get(field) is not True]
    if failed:
        raise PolicyError("KG snapshot has unqualified gates: %s" % ", ".join(failed))
    _sha256(data.get("contamination_report_sha256"), "KG snapshot.contamination_report_sha256")
    return data


def load_relevance_manifest(path: Path, snapshot_sha256: str) -> Dict[str, Any]:
    data = load_json(path)
    if data.get("schema_version") != "1.0":
        raise ContractError("KG relevance manifest must use schema_version 1.0")
    if data.get("source_snapshot_sha256") != snapshot_sha256:
        raise PolicyError("KG relevance manifest is bound to a different snapshot")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        raise ContractError("KG relevance manifest.tasks must be an object")
    for task_id, ids in tasks.items():
        if not isinstance(task_id, str) or not task_id:
            raise ContractError("KG relevance task IDs must be non-empty strings")
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            raise ContractError("KG relevance entries must be string lists")
        if len(ids) != len(set(ids)):
            raise ContractError("KG relevance entries must not contain duplicate IDs")
    return data


class McpSseClient:
    """Small dependency-free client for the legacy MCP HTTP+SSE transport.

    The KG service currently advertises an SSE endpoint. The model never receives this client or
    endpoint; only the benchmark controller uses it before any model process starts.
    """

    def __init__(self, config: Mapping[str, Any]):
        self.config = dict(config)
        self.endpoint = str(config["endpoint"])
        self.timeout = int(config["request_timeout_seconds"])
        self.max_response_bytes = int(config["max_response_bytes"])
        self.headers = {"Accept": "text/event-stream"}
        for header, variable in config.get("headers_from_env", {}).items():
            value = os.environ.get(variable)
            if value is None:
                raise PolicyError("required MCP KG credential environment variable is missing: %s" % variable)
            self.headers[header] = value
        self._message_url: Optional[str] = None
        self._endpoint_ready = threading.Event()
        self._pending: Dict[int, "queue.Queue[Dict[str, Any]]"] = {}
        self._pending_lock = threading.Lock()
        self._errors: "queue.Queue[BaseException]" = queue.Queue()
        self._response: Any = None
        self._thread: Optional[threading.Thread] = None
        self._next_id = 1

    def _dispatch_event(self, event: str, data: str) -> None:
        if event == "endpoint":
            target = urllib.parse.urljoin(self.endpoint, data.strip())
            base = urllib.parse.urlsplit(self.endpoint)
            parsed = urllib.parse.urlsplit(target)
            if (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
                raise PolicyError("MCP SSE endpoint event attempted a cross-origin message URL")
            self._message_url = target
            self._endpoint_ready.set()
            return
        if event not in {"message", ""} or not data.strip():
            return
        value = json.loads(data)
        if not isinstance(value, dict) or not isinstance(value.get("id"), int):
            return
        with self._pending_lock:
            waiter = self._pending.get(value["id"])
        if waiter is not None:
            waiter.put(value)

    def _listen(self) -> None:
        try:
            request = urllib.request.Request(self.endpoint, headers=self.headers, method="GET")
            self._response = urllib.request.urlopen(request, timeout=self.timeout)
            event = "message"
            data_lines: List[str] = []
            event_bytes = 0
            while True:
                raw = self._response.readline()
                if not raw:
                    break
                event_bytes += len(raw)
                if event_bytes > self.max_response_bytes:
                    raise PolicyError("MCP SSE event exceeded max_response_bytes")
                line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
                if not line:
                    self._dispatch_event(event, "\n".join(data_lines))
                    event, data_lines, event_bytes = "message", [], 0
                elif line.startswith(":"):
                    continue
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        except BaseException as exc:  # surfaced synchronously by start/request
            self._errors.put(exc)
            self._endpoint_ready.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._listen, name="evoldo-kg-sse", daemon=True)
        self._thread.start()
        if not self._endpoint_ready.wait(self.timeout):
            self.close()
            raise TimeoutError("timed out waiting for MCP SSE endpoint event")
        if self._message_url is None:
            self._raise_listener_error("MCP SSE stream ended before endpoint negotiation")
        initialized = self.request("initialize", {
            "protocolVersion": self.config["protocol_version"],
            "capabilities": {},
            "clientInfo": {"name": "evoldo-bench", "version": "0.7.0"},
        })
        if not isinstance(initialized.get("result"), dict):
            raise ContractError("MCP initialize response is missing result")
        self.notify("notifications/initialized", {})

    def _raise_listener_error(self, fallback: str) -> None:
        try:
            error = self._errors.get_nowait()
        except queue.Empty:
            raise ConnectionError(fallback)
        raise ConnectionError("MCP SSE listener failed: %s" % error) from error

    def _post(self, payload: Dict[str, Any]) -> None:
        if self._message_url is None:
            raise ConnectionError("MCP message endpoint is not initialized")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = dict(self.headers)
        headers.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        request = urllib.request.Request(self._message_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            returned = response.read(self.max_response_bytes + 1)
        if len(returned) > self.max_response_bytes:
            raise PolicyError("MCP POST response exceeded max_response_bytes")
        if returned.strip():
            value = json.loads(returned)
            if isinstance(value, dict) and isinstance(value.get("id"), int):
                with self._pending_lock:
                    waiter = self._pending.get(value["id"])
                if waiter is not None:
                    waiter.put(value)

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = waiter
        try:
            self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            try:
                response = waiter.get(timeout=self.timeout)
            except queue.Empty:
                if not self._errors.empty():
                    self._raise_listener_error("MCP request listener failed")
                raise TimeoutError("timed out waiting for MCP response to %s" % method)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            raise ContractError("MCP request %s failed: %s" % (method, response["error"]))
        return response

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        result = response.get("result")
        if not isinstance(result, dict):
            raise ContractError("MCP tool response is missing result")
        if result.get("isError") is True:
            raise ContractError("MCP tool returned isError=true")
        return result

    def close(self) -> None:
        response = self._response
        self._response = None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def __enter__(self) -> "McpSseClient":
        try:
            self.start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def _extract_tool_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ContractError("benchmark_retrieve must return one JSON text content block or structuredContent")
    block = content[0]
    if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
        raise ContractError("benchmark_retrieve text content is invalid")
    try:
        payload = json.loads(block["text"])
    except json.JSONDecodeError as exc:
        raise ContractError("benchmark_retrieve text must contain one JSON object") from exc
    if not isinstance(payload, dict):
        raise ContractError("benchmark_retrieve payload must be an object")
    return payload


def _nullable_string(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractError("%s must be a string or null" % field)
    return value


def validate_external_retrieval(
    payload: Dict[str, Any], query: str, top_k: int, config: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    allowed_top_level = {
        "schema_version", "source_snapshot_id", "source_snapshot_sha256",
        "retrieval_method", "query", "query_sha256", "top_k", "entries",
    }
    unexpected_top_level = sorted(set(payload).difference(allowed_top_level))
    if unexpected_top_level:
        raise ContractError(
            "external KG response contains unexpected fields: %s"
            % ", ".join(unexpected_top_level)
        )
    if payload.get("schema_version") != "1.0":
        raise ContractError("external KG response must use schema_version 1.0")
    if payload.get("source_snapshot_id") != snapshot["snapshot_id"]:
        raise PolicyError("external KG response snapshot_id does not match the frozen manifest")
    if payload.get("source_snapshot_sha256") != snapshot["snapshot_sha256"]:
        raise PolicyError("external KG response snapshot_sha256 does not match the frozen manifest")
    if payload.get("retrieval_method") != config["retrieval_method"]:
        raise PolicyError("external KG response retrieval_method changed")
    if payload.get("query") != query:
        raise PolicyError("external KG response query changed")
    expected_query_sha = sha256_text(query)
    if payload.get("query_sha256") != expected_query_sha:
        raise PolicyError("external KG response query_sha256 is invalid")
    if payload.get("top_k") != top_k:
        raise PolicyError("external KG response top_k changed")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) > top_k:
        raise ContractError("external KG response entries must be a list no longer than top_k")
    normalized = []
    ids = set()
    total_text = 0
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ContractError("external KG entry must be an object")
        allowed_entry_fields = {
            "rank", "stable_id", "id", "title", "text", "tags", "source_class",
            "source_name", "source_uri", "retrieval_score", "updated_at", "confidence",
            "provenance",
        }
        unexpected_entry_fields = sorted(set(entry).difference(allowed_entry_fields))
        if unexpected_entry_fields:
            raise ContractError(
                "external KG entry contains unexpected fields: %s"
                % ", ".join(unexpected_entry_fields)
            )
        forbidden = {"task_id", "family_id", "answer", "oracle", "expected"}.intersection(entry)
        if forbidden:
            raise PolicyError("external KG entry contains forbidden routing/answer fields")
        if entry.get("rank") != index:
            raise ContractError("external KG entry ranks must be contiguous and 1-based")
        stable_id = entry.get("stable_id", entry.get("id"))
        if not isinstance(stable_id, str) or not SAFE_ID_RE.fullmatch(stable_id):
            raise ContractError("external KG entry stable_id is invalid")
        if stable_id in ids:
            raise ContractError("external KG response contains duplicate stable IDs")
        ids.add(stable_id)
        title = _required_string(entry.get("title"), "external KG entry.title")
        text = _required_string(entry.get("text"), "external KG entry.text")
        if len(text) > int(config["max_entry_text_chars"]):
            raise PolicyError("external KG entry text exceeds max_entry_text_chars")
        total_text += len(text)
        if total_text > int(config["max_total_text_chars"]):
            raise PolicyError("external KG response exceeds max_total_text_chars")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
            raise ContractError("external KG entry.tags must be a string list")
        if len(tags) != len(set(tags)):
            raise ContractError("external KG entry.tags must not contain duplicates")
        raw_source_class = entry.get("source_class")
        source_class = (
            "unknown" if raw_source_class is None
            else _required_string(raw_source_class, "external KG entry.source_class")
        )
        score = entry.get("retrieval_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
            raise ContractError("external KG entry.retrieval_score must be finite")
        confidence = entry.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
            or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1
        ):
            raise ContractError("external KG entry.confidence must be null or a number in [0,1]")
        provenance = entry.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ContractError("external KG entry.provenance must be an object")
        normalized.append({
            "rank": index,
            "id": stable_id,
            "title": title.strip(),
            "text": text,
            "tags": tags,
            "source_class": source_class,
            "source_name": _nullable_string(entry.get("source_name"), "external KG entry.source_name"),
            "source_uri": _nullable_string(entry.get("source_uri"), "external KG entry.source_uri"),
            "retrieval_score": float(score),
            "updated_at": _nullable_string(entry.get("updated_at"), "external KG entry.updated_at"),
            "confidence": float(confidence) if confidence is not None else None,
            "provenance": provenance,
        })
    return {
        "schema_version": "1.0",
        "treatment": "knowledge_assisted",
        "retrieval_backend": "external_mcp_sse",
        "retrieval_method": config["retrieval_method"],
        "query_profile": config["query_profile"],
        "query": query,
        "top_k": top_k,
        "corpus_sha256": snapshot["snapshot_sha256"],
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "query_sha256": expected_query_sha,
        "entries": normalized,
        "usage_rule": "Retrieved entries are general design priors, not measured facts or task-specific proof.",
    }


def materialize_external_retrieval(
    task: Any,
    config: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    destination: Path,
    top_k: int = 4,
    client_class: Any = McpSseClient,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0 or top_k > 20:
        raise ContractError("external KG top_k must be an integer in [1,20]")
    query = task_query(task, str(config["query_profile"]))
    arguments = {
        "query": query,
        "method": config["retrieval_method"],
        "limit": top_k,
    }
    started = time.monotonic()
    max_attempts = int(config["max_retrieval_attempts"])
    attempt_count = 0
    transient_failures: List[str] = []
    while True:
        attempt_count += 1
        try:
            with client_class(config) as client:
                raw_result = client.call_tool(str(config["tool_name"]), arguments)
            break
        except (ConnectionError, TimeoutError, OSError) as exc:
            transient_failures.append(type(exc).__name__)
            if attempt_count >= max_attempts:
                raise
            time.sleep(int(config["retry_backoff_seconds"]))
    duration = time.monotonic() - started
    payload = _extract_tool_payload(raw_result)
    retrieval = validate_external_retrieval(payload, query, top_k, config, snapshot)
    destination.mkdir(parents=True, exist_ok=True)
    dump_json(destination / "kg_mcp_raw_response.json", raw_result)
    raw_sha = sha256_file(destination / "kg_mcp_raw_response.json")
    # Keep controller-only and volatile fields out of the model-visible file.
    # In particular, request duration must not change the retrieval hash or leak
    # into the treatment context when the same snapshot/query is materialized
    # more than once.
    controller_provenance = {
        "logical_retrieval_calls": 1,
        "retrieval_attempts": attempt_count,
        "transient_failure_types": transient_failures,
        "mcp_tool_name": config["tool_name"],
        "materialization_seconds": round(duration, 6),
        "raw_response_sha256": raw_sha,
        "snapshot_manifest_sha256": snapshot.get("_manifest_sha256"),
    }
    dump_json(destination / "kg_retrieval.json", retrieval)
    return retrieval, controller_provenance


def _expected_relevance_metrics(
    returned_ids: Sequence[str], relevant_ids: Optional[Sequence[str]],
) -> Dict[str, Any]:
    if relevant_ids is None:
        return {
            "relevance_manifest_available": False,
            "relevant_count": None,
            "returned_count": len(returned_ids),
            "hit_count": None,
            "recall_at_k": None,
            "precision_at_k": None,
        }
    hits = len(set(relevant_ids).intersection(returned_ids))
    return {
        "relevance_manifest_available": True,
        "relevant_count": len(relevant_ids),
        "returned_count": len(returned_ids),
        "hit_count": hits,
        "recall_at_k": round(hits / len(relevant_ids), 6) if relevant_ids else None,
        "precision_at_k": round(hits / len(returned_ids), 6) if returned_ids else 0.0,
    }


def freeze_external_retrievals(
    tasks: Sequence[Any],
    config_path: Path,
    snapshot_manifest_path: Path,
    output_root: Path,
    top_k: int = 4,
    relevance_manifest_path: Optional[Path] = None,
    client_class: Any = McpSseClient,
) -> Dict[str, Any]:
    if not tasks:
        raise ContractError("external KG freeze requires at least one task")
    if output_root.exists() and any(output_root.iterdir()):
        raise PolicyError("external KG freeze output must be empty: %s" % output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    config = load_mcp_kg_config(config_path)
    snapshot = load_kg_snapshot_manifest(snapshot_manifest_path, config["retrieval_method"])
    snapshot["_manifest_sha256"] = sha256_file(snapshot_manifest_path)
    relevance = (
        load_relevance_manifest(relevance_manifest_path, snapshot["snapshot_sha256"])
        if relevance_manifest_path is not None else None
    )
    if relevance is not None:
        missing_relevance = sorted(
            {task.task_id for task in tasks}.difference(relevance["tasks"])
        )
        if missing_relevance:
            raise ContractError(
                "KG relevance manifest is missing scheduled tasks: %s"
                % ", ".join(missing_relevance)
            )
    shutil.copy2(str(config_path), str(output_root / "mcp_kg_config.json"))
    shutil.copy2(str(snapshot_manifest_path), str(output_root / "kg_snapshot_manifest.json"))
    if relevance_manifest_path is not None:
        shutil.copy2(str(relevance_manifest_path), str(output_root / "kg_relevance_manifest.json"))
    rows = []
    for task in tasks:
        task_dir = output_root / "tasks" / task.task_id
        retrieval, controller_provenance = materialize_external_retrieval(
            task, config, snapshot, task_dir, top_k, client_class=client_class,
        )
        returned = [entry["id"] for entry in retrieval["entries"]]
        relevant_ids = relevance["tasks"].get(task.task_id, []) if relevance else None
        metrics = _expected_relevance_metrics(returned, relevant_ids)
        rows.append({
            "task_id": task.task_id,
            "query_sha256": retrieval["query_sha256"],
            "retrieval_sha256": sha256_file(task_dir / "kg_retrieval.json"),
            "raw_response_sha256": controller_provenance["raw_response_sha256"],
            "returned_ids": returned,
            "metrics": metrics,
            "materialization_seconds": controller_provenance["materialization_seconds"],
            "retrieval_attempts": controller_provenance["retrieval_attempts"],
            "transient_failure_types": controller_provenance["transient_failure_types"],
        })
    manifest = {
        "schema_version": "1.0",
        "created_at": utc_timestamp(),
        "backend": "external_mcp_sse",
        "task_count": len(rows),
        "top_k": top_k,
        "retrieval_method": config["retrieval_method"],
        "query_profile": config["query_profile"],
        "config_sha256": sha256_file(config_path),
        "snapshot_manifest_sha256": snapshot["_manifest_sha256"],
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "relevance_manifest_sha256": sha256_file(relevance_manifest_path) if relevance_manifest_path else None,
        "total_materialization_seconds": round(sum(row["materialization_seconds"] for row in rows), 6),
        "rows": rows,
    }
    dump_json(output_root / "knowledge_freeze_manifest.json", manifest)
    return manifest


def import_external_retrieval_freeze(
    tasks: Sequence[Any], source_root: Path, destination_root: Path,
    expected_top_k: Optional[int] = None,
    require_relevance: bool = False,
) -> Dict[str, Any]:
    """Verify and copy a reviewed preflight freeze without contacting the KG service."""
    if not source_root.is_dir():
        raise PolicyError("external KG freeze directory does not exist: %s" % source_root)
    symlinks = [path for path in source_root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise PolicyError("external KG freeze contains a symbolic link: %s" % symlinks[0])
    manifest_path = source_root / "knowledge_freeze_manifest.json"
    config_path = source_root / "mcp_kg_config.json"
    snapshot_path = source_root / "kg_snapshot_manifest.json"
    for path in (manifest_path, config_path, snapshot_path):
        if not path.is_file():
            raise PolicyError("external KG freeze is missing %s" % path.name)
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != "1.0" or manifest.get("backend") != "external_mcp_sse":
        raise ContractError("external KG freeze manifest is invalid")
    config = load_mcp_kg_config(config_path)
    snapshot = load_kg_snapshot_manifest(snapshot_path, config["retrieval_method"])
    bindings = {
        "config_sha256": sha256_file(config_path),
        "snapshot_manifest_sha256": sha256_file(snapshot_path),
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "retrieval_method": config["retrieval_method"],
        "query_profile": config["query_profile"],
    }
    for field, expected in bindings.items():
        if manifest.get(field) != expected:
            raise PolicyError("external KG freeze binding changed: %s" % field)
    relevance_path = source_root / "kg_relevance_manifest.json"
    relevance_sha = manifest.get("relevance_manifest_sha256")
    relevance: Optional[Dict[str, Any]] = None
    if relevance_sha is None:
        if relevance_path.exists():
            raise PolicyError("external KG freeze has an unbound relevance manifest")
    else:
        _sha256(relevance_sha, "external KG freeze.relevance_manifest_sha256")
        if not relevance_path.is_file():
            raise PolicyError("external KG freeze is missing its bound relevance manifest")
        if sha256_file(relevance_path) != relevance_sha:
            raise PolicyError("external KG relevance manifest changed after preflight")
        relevance = load_relevance_manifest(relevance_path, snapshot["snapshot_sha256"])
    wanted = {task.task_id: task for task in tasks}
    if relevance is not None:
        missing_relevance = sorted(set(wanted).difference(relevance["tasks"]))
        if missing_relevance:
            raise PolicyError(
                "external KG relevance manifest is missing scheduled tasks: %s"
                % ", ".join(missing_relevance)
            )
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise ContractError("external KG freeze rows must be a list")
    indexed = {row.get("task_id"): row for row in rows if isinstance(row, dict)}
    if set(indexed) != set(wanted) or len(indexed) != len(rows):
        raise PolicyError("external KG freeze task set must exactly match the scheduled task set")
    if require_relevance:
        if relevance is None:
            raise PolicyError("formal reviewed KG freeze is missing a relevance manifest")
        unlabeled = sorted(
            task_id for task_id, row in indexed.items()
            if row.get("metrics", {}).get("relevance_manifest_available") is not True
        )
        if unlabeled:
            raise PolicyError(
                "formal reviewed KG freeze has unlabeled tasks: %s" % ", ".join(unlabeled)
            )
    top_k = manifest.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
        raise ContractError("external KG freeze top_k is invalid")
    if expected_top_k is not None and top_k != expected_top_k:
        raise PolicyError("external KG freeze top_k differs from the scheduled experiment")
    for task_id, task in wanted.items():
        row = indexed[task_id]
        task_dir = source_root / "tasks" / task_id
        retrieval_path = task_dir / "kg_retrieval.json"
        raw_path = task_dir / "kg_mcp_raw_response.json"
        if not retrieval_path.is_file() or not raw_path.is_file():
            raise PolicyError("external KG freeze is missing task artifacts for %s" % task_id)
        if sha256_file(retrieval_path) != row.get("retrieval_sha256"):
            raise PolicyError("external KG frozen retrieval changed for %s" % task_id)
        if sha256_file(raw_path) != row.get("raw_response_sha256"):
            raise PolicyError("external KG raw response changed for %s" % task_id)
        retrieval = load_json(retrieval_path)
        query = task_query(task, config["query_profile"])
        raw_result = load_json(raw_path)
        regenerated = validate_external_retrieval(
            _extract_tool_payload(raw_result), query, top_k, config, snapshot,
        )
        if retrieval != regenerated:
            raise PolicyError(
                "external KG normalized retrieval does not match its raw response for %s" % task_id
            )
        expected_fields = {
            "schema_version": "1.0",
            "treatment": "knowledge_assisted",
            "retrieval_backend": "external_mcp_sse",
            "retrieval_method": config["retrieval_method"],
            "query_profile": config["query_profile"],
            "query": query,
            "top_k": top_k,
            "corpus_sha256": snapshot["snapshot_sha256"],
            "source_snapshot_id": snapshot["snapshot_id"],
            "source_snapshot_sha256": snapshot["snapshot_sha256"],
            "query_sha256": sha256_text(query),
        }
        for field, expected in expected_fields.items():
            if retrieval.get(field) != expected:
                raise PolicyError("external KG retrieval binding changed for %s: %s" % (task_id, field))
        entries = retrieval.get("entries")
        if not isinstance(entries, list) or len(entries) > top_k:
            raise ContractError("external KG frozen entries are invalid for %s" % task_id)
        returned_ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
        if len(returned_ids) != len(entries) or returned_ids != row.get("returned_ids"):
            raise PolicyError("external KG returned IDs changed for %s" % task_id)
        if len(returned_ids) != len(set(returned_ids)):
            raise ContractError("external KG frozen retrieval has duplicate IDs")
        relevant_ids = relevance["tasks"].get(task_id, []) if relevance is not None else None
        expected_metrics = _expected_relevance_metrics(returned_ids, relevant_ids)
        if row.get("metrics") != expected_metrics:
            raise PolicyError("external KG relevance metrics changed for %s" % task_id)
    if destination_root.exists() and any(destination_root.iterdir()):
        raise PolicyError("external KG import destination must be empty: %s" % destination_root)
    shutil.copytree(str(source_root), str(destination_root), dirs_exist_ok=True)
    for path in destination_root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    imported = dict(manifest)
    imported["imported_from_preflight"] = True
    imported["source_freeze_manifest_sha256"] = sha256_file(manifest_path)
    return imported

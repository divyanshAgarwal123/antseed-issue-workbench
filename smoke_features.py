"""Probe eight Antseed buyer API features using currently advertised free peers.

The requests use synthetic prompts and pin every call to a zero-priced peer.
Set ANTSEED_BASE_URL and, for a gateway, ANTSEED_API_KEY in your environment.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE_URL = os.environ.get("ANTSEED_BASE_URL", "http://127.0.0.1:8377").rstrip("/")
EVIDENCE = ROOT / "evidence"
TEXT_CANDIDATES = ("gpt-oss-120b", "openai-gpt-oss-120b")
MULTIMODAL_CANDIDATES = ("mimo-v2.6-flash", "xiaomi/mimo-v2.6-flash")
STREAM_CANDIDATES = ("deepseek-v4.1-flash-free",)


def request(path: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Anthropic-Version": "2023-06-01"}
    if key := os.environ.get("ANTSEED_API_KEY"):
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            status, response_headers, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, response_headers, body = error.code, error.headers, error.read()
    raw = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw[:5000]
    return {
        "status": status,
        "seconds": round(time.monotonic() - started, 3),
        "peer": response_headers.get("x-antseed-peer-id"),
        "body": parsed,
    }


def free_peer(models: dict, candidates: tuple[str, ...], image: bool = False) -> tuple[str, str]:
    for candidate in candidates:
        for model in models.values():
            if model.get("type") != "text":
                continue
            for peer in model.get("peers", []):
                if candidate not in {model["id"], peer.get("serviceId")}:
                    continue
                inputs = (peer.get("capabilities") or {}).get("inputs", [])
                tier = (peer.get("freeTier") or {}).get("base") or {}
                if (
                    peer.get("inputUsdPerMillion") == 0
                    and peer.get("outputUsdPerMillion") == 0
                    and peer.get("reputationScore", 0) >= 60
                    and not tier.get("stakersOnly", False)
                    and (not image or "image" in inputs)
                    and peer.get("peerId")
                ):
                    return model["id"], peer["peerId"]
    raise RuntimeError(f"No eligible zero-priced peer is available for {candidates}.")


def passed(name: str, result: dict, expected_peer: str) -> bool:
    if result["status"] != 200 or result["peer"] != expected_peer:
        return False
    body = result["body"]
    if name == "chat_completion":
        return "CHAT_OK" in json.dumps(body)
    if name == "responses_api":
        return "RESPONSES_OK" in json.dumps(body)
    if name == "anthropic_messages":
        return "MESSAGES_OK" in json.dumps(body)
    if name == "json_mode":
        try:
            return json.loads(body["choices"][0]["message"]["content"])["status"] == "JSON_OK"
        except (KeyError, IndexError, TypeError, ValueError):
            return False
    if name == "tool_call":
        try:
            calls = body["choices"][0]["message"]["tool_calls"]
            return any(call["function"]["name"] == "add" and json.loads(call["function"]["arguments"]) == {"a": 7, "b": 9} for call in calls)
        except (KeyError, IndexError, TypeError, ValueError):
            return False
    if name == "streaming":
        if not isinstance(body, str) or "[DONE]" not in body:
            return False
        chunks = []
        for line in body.splitlines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                chunks.append(json.loads(line[6:])["choices"][0]["delta"].get("content") or "")
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return "STREAM_OK" in "".join(chunks)
    if name == "vision":
        return "blue" in json.dumps(body).lower()
    if name == "pinned_peer":
        return "PINNED_OK" in json.dumps(body)
    return False


def main() -> None:
    catalog = request("/v1/models")
    if catalog["status"] != 200 or not isinstance(catalog["body"], dict):
        raise RuntimeError(f"Model discovery failed: HTTP {catalog['status']}")
    models = {model["id"]: model for model in catalog["body"]["data"]}
    text_model, text_peer = free_peer(models, TEXT_CANDIDATES)
    image_model, image_peer = free_peer(models, MULTIMODAL_CANDIDATES, image=True)
    stream_model, stream_peer = free_peer(models, STREAM_CANDIDATES)
    image_url = "data:image/png;base64," + base64.b64encode((EVIDENCE / "vision-test.png").read_bytes()).decode()
    pin = lambda model, peer: f"{peer}@{model}"

    cases = {
        "chat_completion": ("/v1/chat/completions", {"model": pin(text_model, text_peer), "messages": [{"role": "user", "content": "Reply with exactly CHAT_OK."}], "max_tokens": 64, "stream": False}, text_peer),
        "responses_api": ("/v1/responses", {"model": pin(image_model, image_peer), "input": "Reply with exactly RESPONSES_OK.", "max_output_tokens": 64, "stream": False}, image_peer),
        "anthropic_messages": ("/v1/messages", {"model": pin(image_model, image_peer), "max_tokens": 64, "messages": [{"role": "user", "content": "Reply with exactly MESSAGES_OK."}]}, image_peer),
        "json_mode": ("/v1/chat/completions", {"model": pin(image_model, image_peer), "messages": [{"role": "user", "content": "Return a JSON object with one field named status and the value JSON_OK. No other text."}], "response_format": {"type": "json_object"}, "max_tokens": 96, "stream": False}, image_peer),
        "tool_call": ("/v1/chat/completions", {"model": pin(image_model, image_peer), "messages": [{"role": "user", "content": "Use the add tool to calculate 7 + 9."}], "tools": [{"type": "function", "function": {"name": "add", "description": "Add two integers", "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}}], "tool_choice": "required", "max_tokens": 128, "stream": False}, image_peer),
        "streaming": ("/v1/chat/completions", {"model": pin(stream_model, stream_peer), "messages": [{"role": "user", "content": "Reply with exactly STREAM_OK."}], "max_tokens": 64, "stream": True}, stream_peer),
        "vision": ("/v1/chat/completions", {"model": pin(image_model, image_peer), "messages": [{"role": "user", "content": [{"type": "text", "text": "What color is the large rectangle? Answer with one color."}, {"type": "image_url", "image_url": {"url": image_url}}]}], "max_tokens": 64, "stream": False}, image_peer),
        "pinned_peer": ("/v1/chat/completions", {"model": pin(stream_model, stream_peer), "messages": [{"role": "user", "content": "Reply with exactly PINNED_OK."}], "max_tokens": 64, "stream": False}, stream_peer),
    }
    results = {}
    for name, (path, payload, peer) in cases.items():
        result = request(path, payload)
        result["passed"] = passed(name, result, peer)
        result["requested_model"] = payload["model"]
        results[name] = result
        print(f"{name}: HTTP {result['status']}, {'PASS' if result['passed'] else 'FAIL'}, {result['seconds']}s")
        time.sleep(0.5)
    output = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "catalog_count": len(models), "cases": results}
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "smoke-results.json").write_text(json.dumps(output, indent=2) + "\n")
    if not all(result["passed"] for result in results.values()):
        raise SystemExit("One or more probes failed; see evidence/smoke-results.json.")


if __name__ == "__main__":
    main()

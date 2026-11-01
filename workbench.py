"""A small, free-only Antseed issue-triage workbench.

The server listens on localhost. Browser input is sent to the selected Antseed
provider, so use public or synthetic examples only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
BASE_URL = os.environ.get("ANTSEED_BASE_URL", "http://127.0.0.1:8377").rstrip("/")
KEY_FILE = os.environ.get("ANTSEED_KEY_FILE")
TEXT_ANALYST_CANDIDATES = ("gpt-oss-120b", "openai-gpt-oss-120b", "deepseek-v4.1-flash-free")
VISION_ANALYST_CANDIDATES = ("mimo-v2.6-flash", "xiaomi/mimo-v2.6-flash", "minimax-m2.7")
REVIEWER_CANDIDATES = ("mistral-small-3-2-24b-instruct", "deepseek-v4-flash", "deepseek-v4.1-flash-free")


def api_key() -> str | None:
    if KEY_FILE:
        return json.loads(Path(KEY_FILE).read_text())["apiKey"]
    return os.environ.get("ANTSEED_API_KEY")


def antseed_request(path: str, payload: dict | None = None) -> tuple[dict, dict]:
    headers = {"Content-Type": "application/json"}
    key = api_key()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
            status = response.status
            response_headers = response.headers
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
        response_headers = error.headers
    data = json.loads(body)
    meta = {
        "status": status,
        "seconds": round(time.monotonic() - started, 2),
        "peer": response_headers.get("x-antseed-peer-id"),
        "model": data.get("model"),
        "usage": data.get("usage"),
    }
    if status != 200:
        raise RuntimeError(f"Antseed HTTP {status}: {data.get('error', data)}")
    return data, meta


def free_offer(model: dict, require_image: bool = False) -> str | None:
    if model.get("type") != "text":
        return None
    for peer in model.get("peers", []):
        tier = peer.get("freeTier") or {}
        inputs = (peer.get("capabilities") or {}).get("inputs", [])
        if (
            peer.get("inputUsdPerMillion") == 0
            and peer.get("outputUsdPerMillion") == 0
            and peer.get("reputationScore", 0) >= 60
            and not (tier.get("base") or {}).get("stakersOnly", False)
            and (not require_image or "image" in inputs)
        ):
            return peer.get("peerId")
    return None


def available_models() -> dict:
    catalog, _ = antseed_request("/v1/models")
    by_id = {model["id"]: model for model in catalog.get("data", [])}
    analyst = next((name for name in TEXT_ANALYST_CANDIDATES if free_offer(by_id.get(name, {}))), None)
    vision_analyst = next((name for name in VISION_ANALYST_CANDIDATES if free_offer(by_id.get(name, {}), require_image=True)), None)
    reviewers = [name for name in REVIEWER_CANDIDATES if free_offer(by_id.get(name, {}))]
    reviewer = reviewers[0] if reviewers else None
    return {
        "catalog_count": len(by_id),
        "free_text_count": sum(bool(free_offer(model)) for model in by_id.values()),
        "analyst_model": analyst,
        "vision_analyst_model": vision_analyst,
        "reviewer_model": reviewer,
        "reviewer_candidates": reviewers,
        "vision_ready": bool(vision_analyst),
        "free_peers": {name: free_offer(by_id[name]) for name in {analyst, *reviewers} if name},
        "vision_peer": free_offer(by_id[vision_analyst], require_image=True) if vision_analyst else None,
    }


def analyze(issue: str, image_data_url: str | None) -> dict:
    state = available_models()
    if not state["analyst_model"] or not state["reviewer_model"]:
        raise RuntimeError("One of the two free models is unavailable right now.")
    if image_data_url and not state["vision_ready"]:
        raise RuntimeError("No eligible free image-input model is available right now.")
    analyst_model = state["vision_analyst_model"] if image_data_url else state["analyst_model"]
    prompt = (
        "Analyze this software issue as a careful tester. Return only a JSON object "
        "with keys summary (string), observed (array of strings), next_checks "
        "(array of strings), and uncertainty (string). Separate observations "
        "from guesses. Preserve negations and failure outcomes exactly. "
        "Never rewrite a reported failure as a success. Issue text:\n" + issue
    )
    content: str | list[dict] = prompt
    if image_data_url:
        content = [
            {"type": "text", "text": prompt + "\nUse the attached image as additional evidence."},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    analyst_peer = state["vision_peer"] if image_data_url else state["free_peers"][analyst_model]
    first, first_meta = antseed_request(
        "/v1/chat/completions",
        {
            "model": f"{analyst_peer}@{analyst_model}",
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "max_tokens": 650,
            "stream": False,
        },
    )
    if first_meta["peer"] != analyst_peer:
        raise RuntimeError("The response did not identify the selected free provider.")
    first_text = first["choices"][0]["message"].get("content") or ""
    try:
        findings = json.loads(first_text)
    except json.JSONDecodeError:
        findings = {"raw_response": first_text}
    review_prompt = (
        "Review this bug triage for contradictions with the original report, "
        "unsupported claims, and missing checks. Give at most three short "
        "plain-text bullet points.\nOriginal report:\n"
        + issue
        + "\nTriage:\n"
        + json.dumps(findings)
    )
    review = ""
    second_meta = None
    reviewer_used = None
    for candidate in state["reviewer_candidates"][:2]:
        second, second_meta = antseed_request(
            "/v1/chat/completions",
            {
                "model": f"{state['free_peers'][candidate]}@{candidate}",
                "messages": [{"role": "user", "content": review_prompt}],
                "max_tokens": 700,
                "stream": False,
            },
        )
        if second_meta["peer"] != state["free_peers"][candidate]:
            raise RuntimeError("The response did not identify the selected free reviewer.")
        review = (second["choices"][0]["message"].get("content") or "").strip()
        reviewer_used = candidate
        if review:
            break
    if not review:
        review = "The reviewer returned no visible answer. Check its response and try another free model."
    return {"findings": findings, "review": review, "analyst": first_meta, "reviewer": second_meta, "analyst_model": analyst_model, "reviewer_model": reviewer_used}


class Handler(BaseHTTPRequestHandler):
    def send(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, value: dict) -> None:
        self.send(status, "application/json; charset=utf-8", json.dumps(value).encode())

    def do_GET(self) -> None:
        if self.path == "/":
            self.send(200, "text/html; charset=utf-8", (WEB / "index.html").read_bytes())
        elif self.path == "/app.js":
            self.send(200, "text/javascript; charset=utf-8", (WEB / "app.js").read_bytes())
        elif self.path == "/api/status":
            try:
                self.send_json(200, available_models())
            except Exception as error:
                self.send_json(502, {"error": str(error)})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_000_000:
                raise ValueError("Request too large (2 MB maximum).")
            payload = json.loads(self.rfile.read(length))
            issue = str(payload.get("issue", "")).strip()
            image = payload.get("image")
            if len(issue) < 12 or len(issue) > 5000:
                raise ValueError("Describe the issue in 12–5000 characters.")
            if image and (not isinstance(image, str) or not image.startswith("data:image/")):
                raise ValueError("The attachment must be an image.")
            self.send_json(200, analyze(issue, image))
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(502, {"error": str(error)})


if __name__ == "__main__":
    port = int(os.environ.get("ANTSEED_WORKBENCH_PORT", "18380"))
    print(f"Workbench: http://127.0.0.1:{port} (Antseed: {BASE_URL})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

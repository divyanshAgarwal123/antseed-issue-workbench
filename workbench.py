"""Local Antseed issue workbench. Requests use advertised zero-priced peers."""
from __future__ import annotations

import base64
import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
BASE_URL = os.environ.get("ANTSEED_BASE_URL", "http://127.0.0.1:8377").rstrip("/")
KEY_FILE = os.environ.get("ANTSEED_KEY_FILE")
TEXT_ANALYST_CANDIDATES = ("gpt-oss-120b", "openai-gpt-oss-120b", "deepseek-v4.1-flash-free")
VISION_ANALYST_CANDIDATES = ("mimo-v2.6-flash", "xiaomi/mimo-v2.6-flash", "minimax-m2.7")
REVIEWER_CANDIDATES = ("mistral-small-3-2-24b-instruct", "deepseek-v4-flash", "deepseek-v4.1-flash-free")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AntseedError(Exception):
    def __init__(self, code: str, message: str, action: str = "Refresh offers and try again.", status: int = 502, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.action = code, message, action
        self.status, self.details = status, details or {}

    def public(self) -> dict:
        return {"code": self.code, "message": self.message, "action": self.action, "details": self.details}


def api_key() -> str | None:
    if KEY_FILE:
        try:
            return json.loads(Path(KEY_FILE).read_text())["apiKey"]
        except (OSError, ValueError, KeyError) as error:
            raise AntseedError("key_configuration", "The configured gateway key file could not be read.", "Check ANTSEED_KEY_FILE or supply ANTSEED_API_KEY on the local server.") from error
    return os.environ.get("ANTSEED_API_KEY")


def upstream_error(status: int, data: dict) -> AntseedError:
    error = data.get("error", {})
    if not isinstance(error, dict):
        error = {"message": str(error)}
    code = error.get("code") or f"http_{status}"
    if code == "spend_limit_reached":
        return AntseedError(code, "The gateway blocked this request under its spending limit.",
                            "A temporary hold can exceed a small key limit even with $0 spent. Wait for holds to settle, or review the limit with the gateway owner. A hold is not a charge.",
                            402, error.get("limit") or {})
    if status == 401:
        return AntseedError(code, "The gateway did not accept the API key.", "Set a valid ANTSEED_API_KEY on the local server, then refresh offers.", 401)
    if status == 429:
        return AntseedError(code, "This provider is temporarily rate limited.", "Try another eligible free offer, or wait before retrying.", 429)
    return AntseedError(code, error.get("message") or f"Antseed returned HTTP {status}.", status=status)


def antseed_request(path: str, payload: dict | None = None) -> tuple[dict, dict]:
    headers = {"Content-Type": "application/json"}
    if key := api_key():
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(BASE_URL + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers=headers, method="POST" if payload is not None else "GET")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw, status, response_headers = response.read(), response.status, response.headers
    except urllib.error.HTTPError as error:
        raw, status, response_headers = error.read(), error.code, error.headers
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        timeout = isinstance(error, (TimeoutError, socket.timeout)) or isinstance(getattr(error, "reason", None), (TimeoutError, socket.timeout))
        raise AntseedError("timeout" if timeout else "connection_failed",
                           "The provider did not answer within 60 seconds." if timeout else "The local Antseed connection is unavailable.",
                           "Try another eligible free offer." if timeout else "Start your Antseed buyer or gateway, check ANTSEED_BASE_URL, then refresh offers.") from error
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise AntseedError("invalid_response", "Antseed returned a response this app could not read.") from error
    if not isinstance(data, dict):
        raise AntseedError("invalid_response", "Antseed returned an unexpected response format.")
    if status != 200:
        raise upstream_error(status, data)
    return data, {"status": status, "seconds": round(time.monotonic() - started, 2),
                  "peer": response_headers.get("x-antseed-peer-id"), "model": data.get("model"), "usage": data.get("usage")}


def eligible_offers(catalog: dict) -> list[dict]:
    offers = {}
    for model in catalog.get("data", []):
        if model.get("type") != "text":
            continue
        for peer in model.get("peers", []):
            tier = (peer.get("freeTier") or {}).get("base") or {}
            protocols = peer.get("protocols") or [peer.get("protocol")]
            categories = set(peer.get("categories") or [])
            if (peer.get("inputUsdPerMillion") != 0 or peer.get("outputUsdPerMillion") != 0
                    or peer.get("reputationScore", 0) < 60 or tier.get("stakersOnly") or not peer.get("peerId")
                    or "openai-chat-completions" not in protocols
                    or (categories and not categories.intersection({"chat", "tasks", "coding", "reasoning", "agents"}))):
                continue
            route = f"{peer['peerId']}@{model['id']}"
            offers[route] = {"id": route, "model": model["id"], "peer": peer["peerId"],
                             "service_id": peer.get("serviceId"),
                             "provider": peer.get("displayName") or peer["peerId"][:10],
                             "reputation": round(peer["reputationScore"], 1),
                             "accepts_image": "image" in ((peer.get("capabilities") or {}).get("inputs") or []),
                             "input_usd_per_million": 0, "output_usd_per_million": 0}
    return sorted(offers.values(), key=lambda offer: (offer["model"], offer["peer"]))


def ranked(offers: list[dict], preferences: tuple[str, ...]) -> list[dict]:
    def preference(offer):
        names = {offer["model"], offer.get("service_id")}
        return min((preferences.index(name) for name in names if name in preferences), default=len(preferences))
    return sorted(offers, key=lambda offer: (preference(offer), -offer["reputation"], offer["id"]))


def offer_pool(state: dict, role: str, image: bool = False, selected: str | None = None, avoid_model: str | None = None) -> list[dict]:
    offers = [offer for offer in state["offers"] if (not image or offer["accepts_image"]) and offer["model"] != avoid_model]
    if selected:
        offers = [offer for offer in offers if offer["id"] == selected]
    preferences = REVIEWER_CANDIDATES if role == "reviewer" else VISION_ANALYST_CANDIDATES if image else TEXT_ANALYST_CANDIDATES
    pool = ranked(offers, preferences)
    if not pool:
        raise AntseedError("offer_unavailable", "No eligible free offer matches this step.",
                           "Refresh offers, remove the screenshot, or choose Automatic. The two steps need different model names.", 409)
    return pool[:1] if selected else pool[:2]


def available_models() -> dict:
    catalog, _ = antseed_request("/v1/models")
    offers = eligible_offers(catalog)
    state = {"catalog_count": len(catalog.get("data", [])), "free_model_count": len({offer["model"] for offer in offers}),
             "offers": offers, "checked_at": now(), "defaults": {}}
    state["orders"] = {
        "analyst": [offer["id"] for offer in ranked(offers, TEXT_ANALYST_CANDIDATES)],
        "vision_analyst": [offer["id"] for offer in ranked([offer for offer in offers if offer["accepts_image"]], VISION_ANALYST_CANDIDATES)],
        "reviewer": [offer["id"] for offer in ranked(offers, REVIEWER_CANDIDATES)],
    }
    for name, role, image in [("analyst", "analyst", False), ("vision_analyst", "analyst", True), ("reviewer", "reviewer", False)]:
        try:
            state["defaults"][name] = offer_pool(state, role, image)[0]
        except AntseedError:
            state["defaults"][name] = None
    return state


def validate_findings(value: dict) -> dict:
    if (not isinstance(value, dict) or not isinstance(value.get("summary"), str) or not value["summary"].strip()
            or not isinstance(value.get("uncertainty"), str)
            or any(not isinstance(value.get(key), list) or not all(isinstance(item, str) for item in value[key]) for key in ("observed", "next_checks"))):
        raise AntseedError("invalid_analysis", "The model returned an incomplete structured analysis.", "Try another eligible free model.")
    return value


def run_step(pool: list[dict], prompt: str | list[dict], role: str, attempts: list, emit) -> tuple[object, dict, dict]:
    last_error = None
    for index, offer in enumerate(pool):
        emit({"event": "status", "stage": role, "offer": offer, "attempt": index + 1})
        started = time.monotonic()
        try:
            payload = {"model": offer["id"], "messages": [{"role": "user", "content": prompt}], "max_tokens": 750, "stream": False}
            if role == "analyst":
                payload["response_format"] = {"type": "json_object"}
            response, meta = antseed_request("/v1/chat/completions", payload)
            if meta["peer"] != offer["peer"]:
                raise AntseedError("peer_mismatch", "The response did not identify the selected free peer.")
            text = ((response.get("choices") or [{}])[0].get("message", {}).get("content") or "")
            if not isinstance(text, str):
                raise AntseedError("invalid_response", "The model returned a non-text answer.")
            text = text.strip()
            if not text:
                raise AntseedError("empty_response", "The model returned no visible answer.")
            if role == "analyst":
                try:
                    value = validate_findings(json.loads(text))
                except ValueError as error:
                    raise AntseedError("invalid_analysis", "The model did not return usable structured analysis.") from error
            else:
                value = text
            attempts.append({"role": role, "offer": offer, **meta})
            return value, meta, offer
        except AntseedError as error:
            last_error = error
            attempts.append({"role": role, "offer": offer, "code": error.code, "seconds": round(time.monotonic() - started, 2)})
            if error.code in {"spend_limit_reached", "connection_failed", "peer_mismatch"} or error.status == 401:
                break
    raise last_error or AntseedError("offer_unavailable", "No free offer was available.")


def review(issue: str, findings: dict, state: dict, analyst_model: str | None, selected: str | None, has_image: bool, attempts: list, emit) -> dict:
    prompt = ("Review this draft against the original issue report. Return at most three short plain-text bullet points about genuine contradictions, unsupported assertions, or a useful missing check. "
              "Suggested checks are proposals, not claims that those events occurred. Do not invent a problem to fill a category. If there is no substantive concern, say so. "
              + ("An image was supplied to the analyst; you see only its written analysis and must not claim to have inspected the image or that it was not attached. " if has_image else "")
              + "\nOriginal report:\n" + issue + "\nDraft:\n" + json.dumps(findings))
    value, meta, offer = run_step(offer_pool(state, "reviewer", selected=selected, avoid_model=analyst_model), prompt, "reviewer", attempts, emit)
    return {"review": value, "reviewer": meta, "reviewer_offer": offer, "reviewer_model": offer["model"], "review_error": None}


def analyze(issue: str, image: str | None, analyst_choice: str | None = None, reviewer_choice: str | None = None, emit=lambda event: None) -> dict:
    emit({"event": "status", "stage": "discovery"})
    state = available_models()
    prompt = ("Analyze this reported software issue. Return only a JSON object with keys summary (string), observed (array of strings), next_checks (array of strings), and uncertainty (string). "
              "Distinguish what the user reports from what you verified. Preserve negations and failure outcomes. Do not claim to reproduce the issue. Keep the draft concise.\nIssue:\n" + issue)
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}] if image else prompt
    attempts = []
    findings, meta, offer = run_step(offer_pool(state, "analyst", bool(image), analyst_choice), content, "analyst", attempts, emit)
    result = {"findings": findings, "analyst": meta, "analyst_offer": offer, "analyst_model": offer["model"],
              "review": "", "reviewer": None, "reviewer_offer": None, "review_error": None,
              "attempts": attempts, "mode": "live", "completed_at": now()}
    emit({"event": "analysis", "result": result})
    try:
        result.update(review(issue, findings, state, offer["model"], reviewer_choice, bool(image), attempts, emit))
    except AntseedError as error:
        result["review_error"] = error.public()
    result["completed_at"] = now()
    return result


def validate_input(payload: dict) -> tuple[str, str | None]:
    issue = payload.get("issue", "")
    image = payload.get("image")
    if not isinstance(issue, str) or not 12 <= len(issue.strip()) <= 5000:
        raise ValueError("Describe the issue in 12–5000 characters.")
    if image:
        if not isinstance(image, str) or not image.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
            raise ValueError("Choose a PNG, JPEG or WebP image.")
        try:
            if len(base64.b64decode(image.split(",", 1)[1], validate=True)) > 1_000_000:
                raise ValueError("Choose an image under 1 MB.")
        except (ValueError, base64.binascii.Error) as error:
            raise ValueError("Choose a valid PNG, JPEG or WebP image under 1 MB.") from error
    return issue.strip(), image


class Handler(BaseHTTPRequestHandler):
    def send(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, data: dict) -> None:
        self.send(status, "application/json; charset=utf-8", json.dumps(data).encode())

    def do_GET(self) -> None:
        static = {"/": (WEB / "index.html", "text/html; charset=utf-8"), "/app.js": (WEB / "app.js", "text/javascript"),
                  "/style.css": (WEB / "style.css", "text/css"), "/sample.png": (ROOT / "evidence/vision-test.png", "image/png")}
        try:
            if self.path in static:
                path, mime = static[self.path]
                self.send(200, mime, path.read_bytes())
            elif self.path == "/api/status":
                self.send_json(200, available_models())
            elif self.path == "/api/recorded":
                result = json.loads((ROOT / "evidence/workbench-pinned-final.json").read_text())
                result.update({"mode": "recorded", "captured_date": "2026-11-02"})
                self.send_json(200, {"issue": "Synthetic test: the export button reports success, but the downloaded file is missing the blue rectangle. Record the failure and suggest one check.", "result": result})
            else:
                self.send_json(404, {"error": {"message": "Page not found."}})
        except AntseedError as error:
            self.send_json(error.status, {"error": error.public()})

    def do_POST(self) -> None:
        if self.path not in {"/api/analyze", "/api/review"}:
            self.send_json(404, {"error": {"message": "Page not found."}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request must be between 1 byte and 2 MB.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Send a JSON object.")
            issue, image = validate_input(payload)
            if self.path == "/api/review":
                validate_findings(payload.get("findings"))
            for key in ("analyst_choice", "reviewer_choice", "analyst_model"):
                if payload.get(key) is not None and not isinstance(payload[key], str):
                    raise ValueError("Select a valid free offer.")
        except (ValueError, AntseedError) as error:
            self.send_json(400, {"error": {"code": "invalid_input", "message": str(error)}})
            return
        streaming = payload.get("stream") is True
        if streaming:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def emit(event):
            if streaming:
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
        try:
            if self.path == "/api/analyze":
                result = analyze(issue, image, payload.get("analyst_choice"), payload.get("reviewer_choice"), emit)
            else:
                attempts = []
                emit({"event": "status", "stage": "discovery"})
                result = review(issue, payload["findings"], available_models(), payload.get("analyst_model"), payload.get("reviewer_choice"), bool(payload.get("has_image")), attempts, emit)
                result.update({"attempts": attempts, "completed_at": now(), "mode": "live"})
            if streaming:
                emit({"event": "complete", "result": result})
            else:
                self.send_json(200, result)
        except AntseedError as error:
            if streaming:
                emit({"event": "error", "error": error.public()})
            else:
                self.send_json(error.status, {"error": error.public()})
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    port = int(os.environ.get("ANTSEED_WORKBENCH_PORT", "18380"))
    print(f"Workbench: http://127.0.0.1:{port} (Antseed: {BASE_URL})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

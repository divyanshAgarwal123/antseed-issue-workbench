# First-person user diary

**Date:** 2 November 2026, IST

**Environment:** macOS, Node.js 25.9.0, `@antseed/cli` 0.1.222 installed locally, separate Antseed data directory, no deposits or existing Antseed setup used. The temporary gateway key was revoked at the end.

## 1. Install and connect

I installed the published CLI in this folder instead of globally. `antseed --version` printed `0.1.222`. I started a gateway with a buyer on separate local ports (18379 and 18377). The buyer connected to the P2P network, and `buyer status --json` reported `connected`, zero available USDC, and zero active channels. No payment details were entered.

The initial console page displayed “Not set up yet” and instructed me to run `antseed gateway console-link`, then register a passkey or wallet. I viewed that first screen; I did not create an owner or explore the authenticated console.

## 2. Find a usable free model

The buyer's `GET /v1/models` returned HTTP 200 and about 1.57 MB of JSON. The first snapshot listed 588 models across text, image, video, and decision services. Only a small subset of text offers were both zero-priced and above the default trust threshold. Some nominally zero-priced services required staking, and image listings had separate per-image prices.

The catalog changed while I worked. I saved the first buyer snapshot with 588 models and a later gateway snapshot with 603; the final repeat probe saw 591. I also saw intermediate counts of 602 and 604 without saving those responses. In particular, free eligibility for the `mimo-v2.6-flash` and `gpt-oss-120b` names changed, while provider-qualified IDs such as `xiaomi/mimo-v2.6-flash` and `openai-gpt-oss-120b` appeared. I made the app check availability on each run and choose from known free IDs. This is an observation about live discovery, not evidence that the models themselves changed identity.

I found that a single model ID can have multiple peers with different prices. For example, the `gpt-oss-120b` listing had a zero-priced peer alongside paid peers. I changed the workbench to select an eligible zero-priced peer, send `peerId@model` rather than the model name alone, and check the response's peer ID. This is a safeguard in the demo, not evidence that Antseed charged me; the test wallet had no funds.

## 3. Send real requests

My first text request to `deepseek-v4.1-flash-free` returned the requested marker with HTTP 200 in 1.85 seconds. I ran an eight-case smoke check, then revised it to discover current offers and pin every request to an advertised zero-priced peer. The repeat run returned HTTP 200 and passed all eight checks:

| Feature | Free model used | Result |
| --- | --- | --- |
| Chat Completions | `gpt-oss-120b` | Correct marker |
| Responses API | `mimo-v2.6-flash` | Correct marker |
| Anthropic Messages | `mimo-v2.6-flash` | Correct marker |
| JSON mode | `mimo-v2.6-flash` | Parseable JSON |
| Tool calling | `mimo-v2.6-flash` | Called `add` with 7 and 9 |
| Streaming | `deepseek-v4.1-flash-free` | SSE ended with `[DONE]` |
| Image understanding | `mimo-v2.6-flash` | Correctly described a generated blue rectangle |
| Pinned provider | `deepseek-v4.1-flash-free` | Correct marker |

These are smoke checks, not a reliability benchmark. The saved `evidence/smoke-results.json` is the pinned repeat run, with request model, response peer, timing and raw output for each case.

## 4. Try a gateway key and build an app

An unauthenticated gateway model request returned HTTP 401. I created a one-day local test key and confirmed that authenticated model discovery and a free text call returned HTTP 200. I initially set its lifetime spend limit to $0.01. The first workbench request then failed: the gateway returned HTTP 402 `spend_limit_reached`, although the key had spent $0.00 and the selected service was advertised as free. The error said up to $0.30 could be held while the request ran. Raising the local test key's cap to $1 allowed the app flow; the wallet still had zero funds. I reproduced the low-cap rejection directly later; its error listed $0.60 held and $0.00 spent. See `evidence/workbench-budget-error.json` and `evidence/direct-free-budget-repro.json`.

I built `workbench.py` and a local browser UI. The app took a description paraphrased from a [public Antseed issue](https://github.com/Antseed/antseed/issues/1181), sent it to a model for structured triage, and sent the draft to a second model for critique. I did not reproduce the issue itself. The first browser run exposed a model-output quality problem: the first model reversed the reported failover outcome in its summary, and the second model returned no visible review. I changed the app to preserve failure wording in its prompt, request more output, try another reviewer if needed, and label the analysis as a draft. A later run produced a correct summary and visible critique.

One subsequent browser attempt using the Mimo model for the first text analysis did not answer within the app's 60-second timeout; the gateway log said the client closed before the buyer answered. I changed the default text preference to the eligible GPT-OSS peer. The next browser text run completed and correctly preserved the failure outcome. The browser also completed an optional screenshot run using the generated blue-rectangle image; the first model identified blue and the second returned a visible review. Screenshots are in `evidence/workbench-browser.png` and `evidence/workbench-vision-browser.png`.

After discovering mixed-price peers, I pinned both workbench calls to the peers the live catalog advertised at zero price. The final pinned text run completed with a correct summary and review (`evidence/workbench-pinned-final.json`). The final pinned image run is in `evidence/workbench-pinned-vision-final.json`. The response peer IDs matched the selected IDs. The earlier browser screenshots predate the pinning change; the repeat API probe and final workbench responses followed it.

One CLI detail also slowed exploration: with the buyer on nondefault port 18377, `buyer status --json` found it, while `buyer activity --json` tried 8377. I did not save that terminal output, so it is a follow-up check rather than a documented defect.

## 5. What I could not exercise in the free-only study

Image and video **generation** listings were visible, but the offers I inspected had nonzero per-image prices or otherwise needed paid capacity. I did not call them. I also did not fund a wallet, stake ANTS, run a seller, claim rewards, install or launch the desktop app, or complete console owner registration. Those paths involve money, provider infrastructure, existing local account state, or authentication setup and need a separate test plan.

This diary reports one Mac, one new buyer, a few free providers, and a short test window. It does not establish network-wide uptime, comparative pricing, model authenticity, or private handling by every seller.

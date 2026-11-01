# Evidence guide

This is a record of one user's free-feature test on 2 November 2026 (IST), using `@antseed/cli@0.1.222` on macOS. The buyer used an isolated identity with no USDC deposited. Published prompts and images are synthetic or refer to a public issue. The temporary gateway key was revoked and its plaintext file removed.

| Claim | Published evidence | What it shows |
| --- | --- | --- |
| A fresh text flow and screenshot flow completed for the walkthrough | [walkthrough video](media/workbench-walkthrough.mp4), [production notes](media/README.md) | Edited, narrated app captures from two additional successful runs. Waits are omitted; the video is a tour, not a continuous recording or a reliability benchmark. |
| Eight API features worked in the repeat run | [smoke-results.json](evidence/smoke-results.json) | Timestamped HTTP status, response peer, pinned model, pass check and raw response for each case. All eight checks passed. |
| The browser app completed a text issue and an image-input issue | [text screenshot](evidence/workbench-browser.png), [image screenshot](evidence/workbench-vision-browser.png), [synthetic image](evidence/vision-test.png) | Visible browser output. The screenshots predate the final peer-pinning code change. |
| The final workbench completed both calls to selected peers | [pinned text response](evidence/workbench-pinned-final.json), [pinned image response](evidence/workbench-pinned-vision-final.json) | Structured analysis, review, response peer IDs and timings after pinning was added. |
| A small key cap rejected a zero-priced route | [initial error](evidence/workbench-budget-error.json), [direct reproduction](evidence/direct-free-budget-repro.json) | HTTP 402 `spend_limit_reached` with a $0.01 lifetime cap, $0.00 spent and an in-flight hold. The direct reproduction requested `deepseek-v4.1-flash-free`; the saved response does not include the request body. |
| One model name listed free and paid peers | [later model catalog](evidence/gateway-models-later.json) | The captured `gpt-oss-120b` entry contains peers at zero and nonzero input/output prices. This shows a selection ambiguity; it does not show an incorrect charge. |
| The catalog changed during the session | [first buyer catalog](evidence/buyer-models.json), [later gateway catalog](evidence/gateway-models-later.json), [repeat probe](evidence/smoke-results.json) | Captured counts of 588, 603 and 591 models. The other intermediate counts mentioned in the diary were observed but not saved. |
| The gateway required a key for model discovery | [unauthenticated response](evidence/gateway-unauth-models.json) | HTTP 401 response body. Authenticated calls are present in the workbench outputs. |

## Limits of the record

The screenshots show model-generated analysis of a *reported* software issue. They do not reproduce that underlying issue. One slow request, one empty review and a nondefault-port CLI mismatch were observed during the session, but raw terminal logs for those events were not retained. They remain follow-up questions, not confirmed product defects.

The catalog snapshots show advertised offers at their capture times. They do not guarantee later price, provider availability, model identity or network-wide reliability. The eight-case probe checks basic behavior once; it is not a quality or security audit. No paid generation, wallet funding, staking, seller flow or authenticated console workflow was tested.

Before publication, the selected artifacts were checked for local home paths, email addresses, bearer tokens and Antseed API-key strings. Local identity files, gateway databases, runtime packages and the revoked test key were excluded.

# Demo guide: what to show and what to say

## The app in one sentence

“This is a small issue-review app I put together on Antseed. One model turns a report into observations and next checks, and a second model reviews that draft.”

It is a working API integration and a first-user study. It does not inspect your code repository or reproduce the bug described in the input. The observations are what the user reports; the next checks are proposed work.

## A two-minute walkthrough

1. Open the app. Point to **Check the free offers**. Say: “The app asks Antseed what is available now, then shows the model, the peer serving it, its reputation and its advertised price.” A model is the AI; a peer is who serves it. The two models can come from the same peer.
2. Click **Load demo issue**. It describes an export that reports success but leaves out a blue rectangle. Say: “This is synthetic input, so I can demonstrate the workflow without sending anyone's private data.”
3. Leave both selections on **Automatic free selection**, then click **Analyze issue**. The progress bar reports real stages. The app pins each call to an advertised zero-priced peer and may try one alternate free offer. A manual selection stays on that offer.
4. Read the summary, reported observations, next checks and uncertainty. Then point to **A second opinion**. Say: “The second model can catch unsupported claims, but it can also be wrong. A person still checks the evidence.” If the review fails, the first draft stays visible and **Retry review only** avoids repeating the analysis.
5. Click **Use sample screenshot**, then analyze again. The analyst can inspect the generated blue rectangle. The reviewer receives only the issue and written draft; it does not see the image. Point to the model, actual response peer, time and tokens under the results. **Download run JSON** saves the result and request details locally.

If the network is unavailable, click **View recorded run**. Say explicitly: “This is the saved successful run from 2 November, not a new live request.” It works without a running Antseed buyer. The page labels it as recorded.

## The spend-cap observation, in simple words

A key's spending cap is a permission limit. It is separate from the money in the wallet.

The test key allowed up to **$0.01** over its lifetime. In the saved failures, it had spent **$0.00**, but the gateway reported a temporary hold of **$0.30**, and **$0.60** on the repeat. That hold exceeded the small allowance, so the gateway returned HTTP 402 `spend_limit_reached` before sending the refused request. Increasing the local key's allowance let the free app flow run; the test wallet remained unfunded.

A hold is a temporary reservation for possible cost, not a bill. Antseed's [budget documentation](https://antseed.com/docs/gateway/budgets/) explains that the gateway holds the configured maximum request cost while requests are running or spending is unsettled. The tested buyer's maximum was $0.30. The record does not prove that every free request under every $0.01 key will fail.

What to say:

> “I hit a confusing first-use case: a request to a free route was refused with zero spent because a generic budget hold exceeded the key's allowance. The hold mechanism is documented. My feedback is that the UI could explain this before a new user gets a payment-related error.”

Show [the saved direct error](evidence/direct-free-budget-repro.json). Point to `limit_usd`, `spent_usd` and `held_usd`. This error came from the gateway path; a demo connected directly to the buyer has no gateway-key budget check and will not reproduce it. Do not describe the hold as money Antseed charged or claim a new billing vulnerability. The app now shows those values in plain language if it receives that error. It does not change key limits.

## What was confusing about model selection?

- **One name, multiple sellers and prices.** The captured `gpt-oss-120b` entry had free and paid peers. Choosing that model name alone does not pick the zero-priced offer. The app now shows and pins the chosen peer.
- **The catalog is live.** Captured counts were 588, 603 and 591. Our first app relied on a short list of names and briefly could not find an eligible route. That was a limitation in our client. The revised app discovers eligible offers across the live catalog and allows manual selection.
- **Free eligibility needs several checks.** Price, reputation, staking requirements, image support and free quotas are separate concerns. A zero token price is not proof that an image-generation call is free; this app only uses text models, some of which accept image input.

What to say:

> “The product exposes the information, but a new developer has to combine several pieces to choose a usable free route. I made that decision visible in the example app. I'd like to test whether clearer filtering and recovery steps help other first-time developers.”

## Questions he may ask

| Question | A grounded answer |
| --- | --- |
| Why use two models? | To show a complete multi-step integration and give the draft a second review. This study has not measured an accuracy improvement. |
| Did you fix Antseed? | I improved the example app and its documentation. No upstream Antseed fix has been made. |
| Is the cap behavior a bug? | The reservation mechanism is documented. The observed issue is confusing feedback when attempting a free route with a tiny allowance and a hold. |
| Does 8/8 mean Antseed is reliable? | It means eight small API behavior checks passed in one run. It is not an uptime benchmark. |
| What would you own next? | A small onboarding pilot: watch a few developers reach their first useful request, record failures and recovery, and deliver reproducible reports, docs or example fixes. |
| How was it built? | With AI coding assistance, using Python and a browser UI on Antseed's existing APIs. I can walk through the flow, evidence and limitations. |

## Run locally

The workbench itself needs only Python 3.10+. For the recorded example:

```sh
python3 workbench.py
```

Open <http://127.0.0.1:18380> and click **View recorded run**. For live calls, start your Antseed buyer in another terminal with `antseed buyer start`, then refresh offers. The default buyer URL is `http://127.0.0.1:8377`. Set `ANTSEED_BASE_URL` if you use a different port or a gateway; a gateway also needs `ANTSEED_API_KEY` on the server.

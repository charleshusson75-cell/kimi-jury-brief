# Friction log: getting started with the Kimi API from France

Notes from building Kimi Jury Brief on platform.kimi.ai (November 2026), written the way I'd hand them to the Kimi team before a France launch. Each item has what happened, why it matters for French developers, and a suggestion.

## What worked well

- **OpenAI-compatible API.** The official OpenAI Python SDK only needed a `base_url` change. That makes moving an existing French startup's code over a one-line change, and that line is the pitch.
- **Long-context tooling.** Strict JSON Schema output, `prompt_cache_key`, cached input at a tenth of the price, and a token-estimate endpoint. Together they make whole-repo review cheap enough to run per team at a hackathon.
- **Enterprise-grade key controls.** v2 keys have expirations, IP allowlists (CIDR) and per-project budgets. These answer the first questions a French CISO asks.

## Friction

**1. The free-ish tier can't show the flagship feature.**
Tier0 (recharged $1–9) allows 500,000 tokens per minute, 1.5M per day, 3 requests per minute and 1 at a time ([limits](https://platform.kimi.ai/docs/pricing/limits)). The gateway counts `max_completion_tokens` (default 131,072) against the per-minute limit. So with default settings the biggest prompt a new developer can send is about 369k tokens, about a third of the 1M window, and only three or four such runs fit in a day.
*Launch suggestion:* hackathon and startup credit codes should come with Tier1 limits. Otherwise the first thing participants see is a 429 in the middle of a demo.

**2. The SDK's default retries can burn the whole Tier0 quota.**
The [troubleshooting guide](https://platform.kimi.ai/docs/guide/troubleshooting) warns that the OpenAI SDK retries twice by default, so one failed request on Tier0 can use the whole requests-per-minute quota. This app sets `max_retries=0`.
*Suggestion:* put `max_retries=0` (or a backoff example) in the quickstart code itself, not only in troubleshooting.

**3. Docs that AI coding agents read are missing the numbers.**
On 25 Nov 2026, the Markdown versions of the pricing and rate-limit pages (the format coding agents fetch) came back with empty tables. On the HTML pricing page, the price table isn't in the page text either. I read the prices from a screenshot.
*Suggestion:* plain-text tables in the `.md` and `llms.txt` exports. Kimi's core audience increasingly reads docs through agents.

**4. A stale context-size note.**
The troubleshooting page still says you can choose `kimi-k3.1-pro` "when prompt_tokens + max_completion_tokens <= 256 * 1024". That's left over from a smaller-context model, and it contradicts the 1,048,576-token window on the pricing page.

**5. Cache-write pricing reads as contradictory.**
The [pricing page](https://platform.kimi.ai/docs/pricing/chat) text says cached input has "no additional cache write charge". The table on the same page lists "5m writes $2.00" and "1h writes $4.00" per million tokens. My reading: a 5-minute write costs the same as normal input and a 1-hour write costs double. One sentence saying so would remove the doubt.

**6. The safe key setting isn't the default.** <!-- Charles: confirm "Never" was pre-selected when you opened the dialog; delete this item if not. -->
The Create API Key dialog opens with Expiration set to *Never*, then warns that keys that never expire make a leak worse.
*Suggestion:* default to 90 days.

**7. Paying from France.** <!-- Charles: confirm what the Recharge page offers when you top up, then edit this item. -->
The [billing FAQ](https://platform.kimi.ai/docs/guide/account-and-payments) lists WeChat Pay and Alipay QR codes for individual top-ups. Most French developers have neither.
*Launch suggestion:* card, Apple Pay and SEPA for EU accounts on day one. For the first wave, prepaid credit codes distributed at events.

**8. The first question a French company will ask.**
The [platform privacy policy](https://platform.kimi.ai/docs/agreement/userprivacy) (Moonshot AI Pte. Ltd., Singapore; last updated 30 April 2025) says user content may be used for "training and refining our underlying technology". A zero-data-retention option exists for enterprise customers. A clear "API inputs are not used for training" default, or an EU-hosted endpoint, would remove the main objection before a sales call starts. It's the same objection the 90-day launch plan is built around.

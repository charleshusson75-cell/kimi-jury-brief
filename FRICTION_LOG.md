# Friction log: getting started with the Kimi API from France

Notes from building Kimi Jury Brief on platform.kimi.ai (November 2026), written the way I'd hand them to the Kimi team before a France launch. Each item has what happened, why it matters for French developers, and a suggestion.

## What worked well

- **OpenAI-compatible API.** The official OpenAI Python SDK only needed a `base_url` change. That makes moving an existing French startup's code over a one-line change, and that line is the pitch.
- **Long-context tooling.** Strict JSON Schema output, `prompt_cache_key`, cached input at a tenth of the price, and a token-estimate endpoint. Together they make whole-repo review cheap enough to run per team at a hackathon. Caching worked with no setup: on the second run of the planted-flaw test, 3,840 of 4,068 prompt tokens came from the cache.
- **Strict structured output held up.** Every brief so far parsed against the strict JSON Schema on the first try, with no retries.
- **Enterprise-grade key controls.** v2 keys have expirations, IP allowlists (CIDR) and per-project budgets. These answer the first questions a French CISO asks.

## Friction

**1. The free-ish tier can't show the flagship feature.**
Tier0 (recharged $1–9) allows 500,000 tokens per minute, 1.5M per day, 3 requests per minute and 1 at a time ([limits](https://platform.kimi.ai/docs/pricing/limits)). The gateway counts `max_completion_tokens` (default 131,072) against the per-minute limit. So with default settings the biggest prompt a new developer can send is about 369k tokens, about a third of the 1M window, and only three or four such runs fit in a day.
*Launch suggestion:* hackathon and startup credit codes should come with Tier1 limits. Otherwise the first thing participants see is a 429 in the middle of a demo.

**2. A $10 balance, still on Tier0.**
I topped up $5, received the $5 voucher, and saw a $10 balance. The Create API Key dialog says "Accumulated recharge of $10 unlocks Tier1", so I assumed I had Tier1. Then my second request, sent while the first was running, came back 429. Vouchers don't count toward tiers. The [limits page](https://platform.kimi.ai/docs/pricing/limits) says so, but only in its "Special Notes". A second $5 top-up fixed it.
*Suggestion:* show the current tier and "$X more to Tier1" next to the balance, and add "vouchers excluded" to the line in the key dialog.

**3. The SDK's default retries can burn the whole Tier0 quota.**
The [troubleshooting guide](https://platform.kimi.ai/docs/guide/troubleshooting) warns that the OpenAI SDK retries twice by default, so one failed request on Tier0 can use the whole requests-per-minute quota. This app sets `max_retries=0`.
*Suggestion:* put `max_retries=0` (or a backoff example) in the quickstart code itself, not only in troubleshooting.

**4. Docs that AI coding agents read are missing the numbers.**
On 25 Nov 2026, the Markdown versions of the pricing and rate-limit pages (the format coding agents fetch) came back with empty tables. On the HTML pricing page, the price table isn't in the page text either. I read the prices from a screenshot.
*Suggestion:* plain-text tables in the `.md` and `llms.txt` exports. Kimi's core audience increasingly reads docs through agents.

**5. A stale context-size note.**
The troubleshooting page still says you can choose `kimi-k3.1-pro` "when prompt_tokens + max_completion_tokens <= 256 * 1024". That's left over from a smaller-context model, and it contradicts the 1,048,576-token window on the pricing page.

**6. Cache-write pricing reads as contradictory.**
The [pricing page](https://platform.kimi.ai/docs/pricing/chat) text says cached input has "no additional cache write charge". The table on the same page lists "5m writes $2.00" and "1h writes $4.00" per million tokens. My reading: a 5-minute write costs the same as normal input and a 1-hour write costs double. One sentence saying so would remove the doubt.

**7. Keys can quietly be set to never expire.**
In my session the Create API Key dialog showed Expiration: *Never*, with only a warning that a never-expiring key makes a leak worse.
*Suggestion:* default to 90 days, and make *Never* a deliberate choice.

**8. Paying from France.**
The [billing FAQ](https://platform.kimi.ai/docs/guide/account-and-payments) lists only WeChat Pay and Alipay QR codes for individual top-ups. If cards are accepted, the FAQ should say so up front. If they aren't, most French developers can't pay at all.
*Launch suggestion:* card, Apple Pay and SEPA for EU accounts on day one. For the first wave, prepaid credit codes distributed at events.

**9. The first question a French company will ask.**
The [platform privacy policy](https://platform.kimi.ai/docs/agreement/userprivacy) (Moonshot AI Pte. Ltd., Singapore; last updated 30 April 2025) says user content may be used for "training and refining our underlying technology". A zero-data-retention option exists for enterprise customers. A clear "API inputs are not used for training" default, or an EU-hosted endpoint, would remove the main objection before a sales call starts. It's the same objection the 90-day launch plan is built around.

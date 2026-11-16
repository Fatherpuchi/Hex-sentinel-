# roles_v2 spec - roles_v1 with the OpenRouter provider (text, small delta)

Status: FROZEN at the commit that contains this line (the git commit time is the freeze time). Any change needs roles_v3. Errata 89.

## 1. Decision record
- Operator decision (chat): remove the OpenAI API (it has no free tier; the account had no credit, HTTP 429 "no credits remaining") and run roles 1 and 2 of roles_v1 through OpenRouter with a GPT model. roles_v1 stays in force except where this file changes it.

## 2. Changes
- Roles 1 (evidence classifier) and 2 (plan critic) use roles_model = openai/gpt-oss-120b:free through the OpenRouter chat endpoint with OPENROUTER_API_KEY. The OpenAI code path stays in hex_roles.py but is dormant (roles_provider "openai" would reactivate it); the OPENAI_API_KEY line is deleted from .env and the key revoked in the OpenAI dashboard.
- The second labeler stays a different model (openrouter_model, poolside/laguna-s-2.1:free by default), so agreement and kappa still compare two models. roles_model can be pointed at a different free model family in roles_config.json.
- Request body: model, messages, max_tokens 1500 (reasoning tokens count toward it), reasoning {effort: low}; no response_format and no temperature. Replies are parsed leniently as before.
- Budget: the free tier allows 20 requests per minute and 50 per day account-wide (docs found earlier; 1000 per day after 10 USD of lifetime credit purchases), shared with the existing fallback to OpenRouter. Caps in code: roles requests 36 per UTC day, roles plus labeler 38 per day (hard maximum 45), at most 2 roles requests per analysis; counters in roles_state.json. About 13 to 19 analyses per day can receive the roles; the others print that the budget is reached while the code rule checks still show. The fallback's own calls are not counted here.
- Display labels show the model name (for example gpt-oss-120b); "chatgpt" remains the internal source name in the tables.

## 3. Known limits
- gpt-oss-120b is the same model Groq runs as the analyst. The classifier sees only item text, but the critic judges plans written by the same model family, so self-preference is possible; plans are shown in a random A/B order without provider names. This role is therefore not an independent opinion; the classifier's agreement with the second labeler (a different family) is the check.
- Free models are rate limited at peak and can rotate out; failures are swallowed and shown. Advisory only: no vote, no guard input (roles_v1 section 2 unchanged). Evaluation as in roles_v1 section 6. The reasoning parameter syntax is from memory and unverified until the first live call.

# LLM Configuration

Start the local system, then open [LLM / AI 模型](http://127.0.0.1:5173/#/llm).
The initial state is intentionally `NOT_CONFIGURED`.

1. Choose DeepSeek, OpenAI, or Custom.
2. Enter the HTTPS base URL, API key, and default model.
3. Select **测试连接**. This makes a real minimal OpenAI-compatible request; it
   is not a synthetic health response.
4. Select **保存配置**. The browser clears the submitted key from its form and
   the backend hot-reloads the provider registry.
5. Set and save the six semantic routes. A route can use any configured
   provider/model without a code edit.
6. Run `./scripts/llm_runtime_qualification.sh` only after a successful real
   connection test. It exercises all six routes with inert schema-only data.

The relevant local API endpoints are:

- `GET /llm/status`, `GET|POST /llm/providers`, `PUT|DELETE /llm/providers/{id}`
- `GET|PUT /llm/routes`, `POST /llm/test`, `GET /llm/usage`
- `POST /llm/qualification` (manual qualification helper; no trading action)

The qualification script exits non-zero until every configured route returns a
valid structured response. It prints provider/model/latency/tokens/error code
only, never a credential.

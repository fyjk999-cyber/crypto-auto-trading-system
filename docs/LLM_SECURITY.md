# LLM Credential and Runtime Security

API keys are accepted only by the backend configuration API. The frontend keeps
the typed value in ephemeral component state and does not use localStorage,
IndexedDB, source code, or a build-time environment value.

`EncryptedFileSecretStore` stores encrypted key material outside the database.
Its generated master key and encrypted store use owner-only permissions and are
ignored by Git (`data/.llm-master-key`, `data/.llm-secrets.json`). Database rows
contain a secret reference only. API responses expose `api_key_masked` and never
return a plaintext key.

LLM usage records contain an invocation identifier, UTC timestamp, brain, route,
provider, model, latency, token metadata, success/failure classification,
correlation identifier and a SHA-256 prompt hash. They do not contain raw keys,
authorization headers, or full prompts.

Remote custom providers must use HTTPS. Localhost is the only HTTP exception for
development. Transport errors are classified without embedding sensitive request
data. Bounded exponential retries and a per-provider circuit breaker prevent
infinite retry loops or provider hammering.

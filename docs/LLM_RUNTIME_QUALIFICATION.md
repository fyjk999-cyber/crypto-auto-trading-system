# LLM Runtime Qualification

This phase does not start the 24-hour PAPER soak. Real provider validation is a
manual post-configuration step because CI never receives a provider key.

With the local backend running and a provider/routes saved from the LLM page:

```bash
cd "/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-local-current"
./scripts/llm_runtime_qualification.sh
```

The script checks configured status and calls the backend's inert route
qualification endpoint. Each route receives only a minimal static JSON contract
prompt; no market order, exchange call, strategy mutation, daily persistence, or
candidate promotion occurs. A successful result is:

```text
LLM_PROVIDER_RUNTIME_VALIDATED=YES
```

Until the user supplies a real key and this command succeeds, the truthful
state is `LLM_PROVIDER_RUNTIME_VALIDATED=NOT_RUN`.

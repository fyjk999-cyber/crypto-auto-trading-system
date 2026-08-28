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

## VALIDATED — 2026-08-28

DeepSeek (`deepseek-chat`) configured via the LLM page; the key lives only in
the encrypted SecretStore. The script was run against the live local backend on
the 7b746df baseline; all six routes PASS (2-3s latency each):

```text
LLM_PROVIDER_RUNTIME_VALIDATED=YES
```

Domain-model profiles verified live: CryptoTrader-Live-v1 (live_analysis),
CryptoTrader-Learning-v1 (daily_review, daily_lesson_extraction),
CryptoTrader-Evolution-v1 (evolution_research, evolution_hypothesis,
evolution_candidate_reasoning). Structured live outputs validated 27/27 in the
subsequent paper smoke (see docs/PAPER_SMOKE_TEST_REPORT.md).

Network note: when a local VPN/TUN answers DNS with fake-IPs and hangs TLS to
api.deepseek.com, set `LLM_DOH_RESOLVER=https://dns.alidns.com/resolve` (opt-in
DoH transport, default off) and re-run the script.

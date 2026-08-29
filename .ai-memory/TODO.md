# TODO

- 2026-08-29T16:30Z (P2 availability): DONE: canonical supervisor active,
  blind lease DELETE removed, cron roles redefined, frontend relaunched,
  shutdown forensics added. REMAINING: re-run sandbox supervisor suite in a
  clean single-run context (TEST1/TEST3/STORM were inconclusive from
  cross-run interference); observe one real SIGTERM (if it recurs) captured by
  shutdown forensics to attribute root cause; optionally add ws:true to vite
  proxy only if frontend later moves WS behind /local-api (currently direct
  ws://127.0.0.1:8000/ws, working).

- 2026-08-29: (a) multi-symbol perpetual registry (19 spot-only symbols reject
  AI SHORT via SPOT_OVERSHORT); (b) MAE/MFE tracking; (c) funding scheduler;
  (d) stale-lease takeover after SIGKILL; (e) mock the 2 live-OKX test
  fixtures; (f) bridge will close the stacked BTC position (time stop); then
  monitor for a post-fix clean SHORT/LONG cycle.
- Await external staging; then Chapter 10.1 -> Chapter 10 -> 11 -> 12 -> 13.
- User must configure a real LLM provider from `#/llm`, test it, then run the six-route qualification before any 24H PAPER soak.

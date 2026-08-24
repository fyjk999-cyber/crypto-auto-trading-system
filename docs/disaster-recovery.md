# Disaster Recovery

Tested scenarios: engine crash, container crash, server restart, DB restart,
network interruption, exchange WS disconnect, private stream disconnect,
scheduler/review/learning restart. Invariants: no duplicate orders, no blind
resubmit, ledger balanced, positions recovered, lease recovered, review states recovered.

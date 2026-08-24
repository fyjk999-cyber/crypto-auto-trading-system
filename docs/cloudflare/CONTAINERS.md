# Containers

Single primary container `crypto-trading-primary`. DB Run Lease keeps single writer.
Lifecycle: desired_state RUNNING/STOPPED, SIGTERM graceful shutdown, sleepAfter 0 for trading engine.

# Cloud Architecture

Modular monolith with separate processes: api, trading-engine, scheduler,
review-worker, learning-worker. PostgreSQL is the durable store. Redis optional
for cache/pubsub only. Ubuntu 24.04 LTS headless target.

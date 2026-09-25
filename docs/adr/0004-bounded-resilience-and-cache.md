# ADR 0004: Bounded resilience and optional caching

**Status:** Accepted for POC design; workload limits and freshness TBD.

## Decision

Bound application concurrency, connection pools, deadlines, command timeouts,
retry count/budget and circuit behavior. Use classified retries with exponential
backoff/jitter and replay-safe idempotent writes. Expose intentional load shedding
as a distinct outcome. Keep inefficient-query and connection-storm workloads
disabled without explicit unsafe gates.

Cache is off by default. Limit cache use to approved read semantics and measure
freshness/calls avoided. **The local in-memory cache is not a production
distributed-cache design.** Optional Azure Cache for Redis is compatibility only;
new paid cache choices require approval and current Azure Managed Redis/
retirement guidance review.

## Alternatives and consequences

Unlimited retry/pooling can amplify overload and hide final failures. Blindly
retrying writes can duplicate work. Cache hits improve neither correctness nor
cost automatically. A process-local cache cannot coordinate replicas; stable
single-replica POC behavior is not a distributed production design.

## Validation

Test policy bounds, error taxonomy, backpressure, duplicate writes, cache expiry
and stale reads locally; validate real SQL/network semantics explicitly in the
cloud. Live recovery and cache savings: **Not demonstrated by this POC run.**

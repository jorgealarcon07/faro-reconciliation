# Case study · Reconciling processor payouts

[Español](CASO_DE_ESTUDIO.md) · [Run the pilot](README.md#run-the-pilot)

## The decision

Treasury receives payment captures, refunds and fees while its processor reports payouts. A repeated delivery can inflate the total, and a refund can arrive before the capture it refers to. An analyst needs to decide which batches can close, identify missing transactions and explain why a correction was accepted.

I used a local simulator to reproduce delivery and settlement behavior described by payment processors. The simulator uses synthetic transactions in Colombian pesos. [Stripe event delivery behavior](https://docs.stripe.com/webhooks#event-delivery-behaviors) · [Stripe payout reconciliation reports](https://docs.stripe.com/reports/payout-reconciliation)

## What I built

The service reads pages over HTTP or replays the same events from files. PostgreSQL keeps each receipt, validates the event contract and applies each financial effect once. The database commits the effects, audit record and cursor together. The payout declaration lists the expected effects so the pipeline can detect missing transactions even when the amounts balance.

In the pilot, two captures of 6,000 and 4,000, a refund of 1,000 and a fee of 300 produce a payout of 8,700 in minor units. The pipeline records both a duplicate receipt and an alias with a different message ID. The first declared payout of 8,600 leaves a discrepancy of −100 and blocks closure. The revised declaration refers to the original and gives the analyst a traceable resolution.

## What the test showed

- An independently specified answer checked all ten pilot batches. Five reconciled, two remained provisional and three stayed in exception. The naive sum over receipts was 20,700 for the example payout. The reconciliation pipeline got 8,700, retained the eight associated receipts and recorded the resolution. HTTP ingestion and file replay produced the same canonical hash. [Pilot manifest](reports/demo/manifest.json) · [Open interactive report (Spanish)](https://jorgealarcon07.github.io/jorgealarcon07/conciliacion-de-pagos/)
- A load test with 100,000 simulated event deliveries detected all 325 batches with planted discrepancies, with zero false closures in that test. The suite also checked late corrections, conflicting variants and interruptions on either side of the commit. [Benchmark (Spanish)](docs/RESULTADOS.md) · [Test results](reports/tests.xml)

## What I learned

Deduplicating by message ID misses cases where two IDs refer to the same transaction. A balanced total is also insufficient when two missing amounts cancel each other out. Keeping receipts, expected effects and declared amounts lets treasury explain a decision and reopen it if later evidence changes.

The simulation covers one currency, one processor and references within the same payout batch. An invoice coverage gap needs additional commercial context before an analyst can infer what is collectible. The measured results describe the simulated reconciliation and recovery behavior.

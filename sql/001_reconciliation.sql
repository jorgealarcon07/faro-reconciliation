CREATE SCHEMA IF NOT EXISTS recon;
REVOKE ALL ON SCHEMA recon FROM PUBLIC;

CREATE TABLE IF NOT EXISTS recon.cases (
  case_id text PRIMARY KEY, source_hash text NOT NULL, seed integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS recon.invoices (
  case_id text REFERENCES recon.cases, invoice_id text, original_minor bigint NOT NULL CHECK(original_minor > 0),
  PRIMARY KEY(case_id, invoice_id)
);
CREATE TABLE IF NOT EXISTS recon.lots (
  case_id text REFERENCES recon.cases, payout_id text, PRIMARY KEY(case_id, payout_id)
);
CREATE TABLE IF NOT EXISTS recon.checkpoints (
  case_id text REFERENCES recon.cases, feed_id text, next_cursor integer NOT NULL CHECK(next_cursor >= 0),
  PRIMARY KEY(case_id, feed_id)
);
CREATE TABLE IF NOT EXISTS recon.raw_delivery (
  receipt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id text REFERENCES recon.cases, feed_id text NOT NULL, position integer NOT NULL,
  payload jsonb NOT NULL, checksum text NOT NULL, event_id text, payout_id text,
  validation_error text, received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(case_id, feed_id, position)
);
CREATE INDEX IF NOT EXISTS receipts_payout ON recon.raw_delivery(case_id, payout_id, receipt_id);
CREATE INDEX IF NOT EXISTS receipts_invalid_event ON recon.raw_delivery(case_id,event_id)
  WHERE validation_error IS NOT NULL;
CREATE TABLE IF NOT EXISTS recon.inbox_event (
  case_id text REFERENCES recon.cases, event_id text, variant_hash text, effect_id text NOT NULL,
  payout_id text NOT NULL, body jsonb NOT NULL,
  PRIMARY KEY(case_id, event_id, variant_hash)
);
CREATE INDEX IF NOT EXISTS inbox_lot ON recon.inbox_event(case_id, payout_id);
CREATE INDEX IF NOT EXISTS inbox_effect ON recon.inbox_event(case_id, effect_id);

CREATE TABLE IF NOT EXISTS recon.movements (
  case_id text REFERENCES recon.cases, effect_id text, payout_id text NOT NULL, invoice_id text,
  event_id text NOT NULL, event_type text NOT NULL,
  signed_minor bigint NOT NULL, invoice_delta_minor bigint NOT NULL, reference_effect_id text,
  PRIMARY KEY(case_id, effect_id),
  FOREIGN KEY(case_id, invoice_id) REFERENCES recon.invoices,
  FOREIGN KEY(case_id, payout_id) REFERENCES recon.lots
);
CREATE INDEX IF NOT EXISTS movements_payout ON recon.movements(case_id, payout_id);
CREATE INDEX IF NOT EXISTS movements_invoice ON recon.movements(case_id, invoice_id);

CREATE TABLE IF NOT EXISTS recon.projections (
  case_id text REFERENCES recon.cases, payout_id text,
  state text NOT NULL CHECK(state IN ('provisional','reconciled','exception')),
  expected_minor bigint NOT NULL, declared_minor bigint, difference_minor bigint,
  statement_effect_id text, finalized boolean NOT NULL, issues jsonb NOT NULL,
  event_states jsonb NOT NULL, PRIMARY KEY(case_id, payout_id)
);
CREATE TABLE IF NOT EXISTS recon.audit (
  audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id text REFERENCES recon.cases, payout_id text, action text NOT NULL,
  actor text NOT NULL, reason text NOT NULL, evidence jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS audit_lot ON recon.audit(case_id,payout_id,audit_id);

CREATE OR REPLACE VIEW recon.invoice_coverage AS
SELECT i.case_id, i.invoice_id, i.original_minor,
       coalesce(sum(m.invoice_delta_minor),0)::bigint AS net_collected_minor,
       (i.original_minor - coalesce(sum(m.invoice_delta_minor),0))::bigint AS coverage_difference_minor
FROM recon.invoices i LEFT JOIN recon.movements m USING (case_id, invoice_id)
GROUP BY i.case_id, i.invoice_id, i.original_minor;

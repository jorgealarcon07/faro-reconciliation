"""CLI for operators and reproducible demonstrations."""

import argparse
import json
import sys
import uuid
from pathlib import Path

from . import demo, report, store
from .contracts import ReconciliationError, case_name, digest, encode
from .fixtures import Bundle, bulk, manual
from .transport import FileFeed, HttpFeed, ingest, server_for


def parser():
    app = argparse.ArgumentParser(prog="faro-reconcile")
    commands = app.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument(
        "--profile", choices=["manual", "clean", "duplicates", "mixed"], default="manual"
    )
    generate.add_argument("--count", type=int, default=1000)
    generate.add_argument("--seed", type=int, default=2026)
    serve = commands.add_parser("serve")
    serve.add_argument("--source", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8082)
    serve.add_argument("--faults", action="store_true")
    apply = commands.add_parser("ingest")
    apply.add_argument("--source", type=Path, required=True)
    apply.add_argument("--url")
    apply.add_argument(
        "--extra", type=Path, help="Append corrections from a new immutable JSONL feed"
    )
    apply.add_argument("--until", type=int)
    apply.add_argument("--page-size", type=int, default=500)
    commands.add_parser("init-db")
    commands.add_parser("clean")
    for name in [
        "ingest",
        "payout",
        "invoice",
        "queue",
        "resolve",
        "report",
        "validate",
        "demo",
        "register",
    ]:
        command = apply if name == "ingest" else commands.add_parser(name)
        command.add_argument("--case", required=name != "demo")
        if name == "demo":
            command.add_argument("--output", type=Path, default=Path("local/demo"))
        elif name == "report":
            command.add_argument("--output", type=Path, default=Path("local/report"))
            command.add_argument("--focus", default="syn_p1")
        elif name in ("payout", "invoice"):
            command.add_argument("identifier")
        elif name == "register":
            reference = command.add_mutually_exclusive_group(required=True)
            reference.add_argument("--payout")
            reference.add_argument("--invoice", type=Path)
        elif name == "resolve":
            command.add_argument("--payout", required=True)
            command.add_argument("--issue", required=True)
            command.add_argument("--actor", required=True)
            command.add_argument("--reason", required=True)
            command.add_argument("--evidence", required=True)
    return app


def ingest_from_args(conn, args):
    bundle = Bundle(args.source)
    feed_id = bundle.manifest["dataset_sha256"]
    if args.extra and args.url:
        raise ReconciliationError("Choose one transport for the correction feed")
    if args.extra:
        rows = [json.loads(line) for line in args.extra.read_text(encoding="utf-8").splitlines()]
        feed = FileFeed("append-" + digest(rows), rows)
    else:
        feed = HttpFeed(args.url, feed_id) if args.url else FileFeed(feed_id, bundle.events)
    store.prepare(conn, args.case, bundle)
    return ingest(conn, args.case, feed, page_size=args.page_size, until=args.until)


def execute(conn, args):
    cmd = args.command
    if cmd == "init-db":
        store.initialize(conn)
        return {"initialized": True}
    if cmd == "demo":
        case_id = case_name(args.case or "demo-" + uuid.uuid4().hex[:10])
        return demo.run(conn, case_id, args.output)
    case_name(args.case)
    if cmd == "ingest":
        return ingest_from_args(conn, args)
    if not conn.execute("SELECT 1 FROM recon.cases WHERE case_id=%s", (args.case,)).fetchone():
        raise ReconciliationError("Case not found")
    if cmd == "payout":
        return report.detail(conn, args.case, args.identifier)
    if cmd == "invoice":
        invoice = conn.execute(
            "SELECT * FROM recon.invoice_coverage WHERE case_id=%s AND invoice_id=%s",
            (args.case, args.identifier),
        ).fetchone()
        if invoice is None:
            raise ReconciliationError("Invoice not found")
        return invoice
    if cmd == "queue":
        return report.queue(conn, args.case, report.snapshot(conn, args.case))
    if cmd == "register":
        invoice = json.loads(args.invoice.read_text(encoding="utf-8")) if args.invoice else None
        return {
            "recorded": store.register_catalog(
                conn, args.case, invoice=invoice, payout_id=args.payout
            )
        }
    if cmd == "resolve":
        return {
            "recorded": store.resolution(
                conn,
                args.case,
                {
                    "payout_id": args.payout,
                    "issue_id": args.issue,
                    "actor": args.actor,
                    "reason": args.reason,
                    "evidence_effect_id": args.evidence,
                },
            )
        }
    if cmd == "report":
        result = report.export(conn, args.case, args.output, args.focus)
        return {
            "report": str(args.output / "index.html"),
            "metrics": result["metrics"],
            "data_sha256": result["data_sha256"],
        }
    if cmd == "validate":
        return demo.verify_oracle(report.snapshot(conn, args.case))
    raise ReconciliationError("Unsupported operation")


def main():
    args = parser().parse_args()
    try:
        if args.command == "generate":
            result = (
                manual(args.output)
                if args.profile == "manual"
                else bulk(args.output, args.count, args.seed, profile=args.profile)
            )
        elif args.command == "serve":
            bundle = Bundle(args.source)
            with server_for(
                FileFeed(bundle.manifest["dataset_sha256"], bundle.events), args.port, args.faults
            ) as server:
                print(encode({"server": f"http://127.0.0.1:{server.server_port}"}), flush=True)
                server.serve_forever()
            return 0
        elif args.command == "clean":
            result = {
                "generated_files_preserved": True,
                "operator_hint": "Use docker compose stop or the native runner lifecycle",
            }
        else:
            with store.connect() as conn:
                result = execute(conn, args)
        print(encode(result))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        error = str(exc) if isinstance(exc, ReconciliationError) else type(exc).__name__
        print(encode({"status": "failed", "error": error}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

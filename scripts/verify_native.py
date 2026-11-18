"""Run P02 on a dedicated native PostgreSQL cluster and close only that server."""

import argparse
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

from faro_reconciliation import store
from faro_reconciliation.contracts import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--port", type=int, default=55433)
    parser.add_argument("--output", type=Path, default=ROOT / "local/evidence")
    parser.add_argument("--scale", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / ".runtime"
    run_dir = runtime / uuid.uuid4().hex[:10]
    run_dir.mkdir(parents=True)
    data = run_dir / "pg"
    pwfile = run_dir / "pg.init"
    password = secrets.token_urlsafe(24)
    pwfile.write_text(password, encoding="utf-8")
    suffix = ".exe" if os.name == "nt" else ""
    bin_dir = args.bin.resolve()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def cmd(name, *items, **options):
        return subprocess.run(
            [str(bin_dir / (name + suffix)), *map(str, items)],
            creationflags=flags,
            check=True,
            **options,
        )

    try:
        cmd(
            "initdb",
            "-D",
            data,
            "-U",
            "faro_reconcile",
            "--encoding=UTF8",
            "--locale=C",
            "--auth=scram-sha-256",
            f"--pwfile={pwfile}",
            stdout=subprocess.DEVNULL,
        )
    finally:
        pwfile.unlink(missing_ok=True)
    os.environ.update(
        {
            "FARO2_DB_HOST": "127.0.0.1",
            "FARO2_DB_PORT": str(args.port),
            "FARO2_DB_PASSWORD": password,
            "FARO2_DB_NAME": "postgres",
            "FARO2_DB_USER": "faro_reconcile",
        }
    )
    with (run_dir / "postgres.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [
                str(bin_dir / ("postgres" + suffix)),
                "-D",
                str(data),
                "-p",
                str(args.port),
                "-h",
                "127.0.0.1",
            ],
            stdout=log,
            stderr=log,
            creationflags=flags,
        )
        try:
            for _ in range(25):
                if server.poll() is not None:
                    raise RuntimeError("PostgreSQL stopped. Inspect the project cluster log")
                try:
                    with store.connect() as conn:
                        conn.execute("CREATE DATABASE faro_reconcile")
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.2)
            else:
                raise RuntimeError("PostgreSQL did not become reachable") from last_error
            os.environ["FARO2_DB_NAME"] = "faro_reconcile"
            os.environ["PYTHONPATH"] = str(ROOT / "src")
            # Explicit basetemp avoids the restricted sandbox AppData temp directory.
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--basetemp",
                    str(run_dir / "pytest"),
                    "--junitxml",
                    str(args.output / "tests.xml"),
                ],
                cwd=ROOT,
                check=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "faro_reconciliation.cli",
                    "demo",
                    "--case",
                    "faro02-demo",
                    "--output",
                    str(args.output / "demo"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr)
            print("Demo complete", flush=True)
            from benchmark import run

            with store.connect() as conn:
                run(conn, args.output / "benchmark.json", run_dir / "fixtures", args.scale)
        finally:
            if server.poll() is None:
                cmd(
                    "pg_ctl",
                    "-D",
                    data,
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                    stdout=subprocess.DEVNULL,
                    timeout=30,
                )
                server.wait(timeout=10)


if __name__ == "__main__":
    main()

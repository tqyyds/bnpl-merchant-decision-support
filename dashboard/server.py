"""Loopback-only dashboard server. No engine imports, execution or source writes."""
from __future__ import annotations
import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .adapter import ContractError, EngineAdapter
from .bundle_adapter import SourceRegistry
from .workflow import workflow

STATIC = Path(__file__).parent.resolve()
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/mockup.html": "mockup.html",
                "/product.css": "product.css", "/product-views.js": "product-views.js",
                "/app.js": "app.js", "/api-client.js": "api-client.js", "/styles.css": "styles.css", "/demo.json": "demo.json"}


def shortlist_csv(snapshot):
    if not snapshot["export_allowed"]:
        raise ContractError("Export requires a saved portfolio with proven optimality")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["run", "cutoff", "scenario", "rank", "merchant_id", "merchant_name", "category", "predicted_revenue_aud", "confidence_band", "reliability", "risk_status", "source_fingerprint", "risk_contract", "risk_binding_id", "risk_evidence_status", "consumer_coverage_fraction", "merchant_coverage_fraction", "consumer_recency_days", "merchant_recency_days", "risk_review_flags"])
    rows = sorted((m for m in snapshot["merchants"] if m["decision"] == "selected"), key=lambda m: m["rank"])
    for m in rows:
        values = [snapshot["run"], snapshot["cutoff"], snapshot["scenario"], m["rank"], m["id"], m["name"], m["category"], m["prediction"], m["confidence"]["band"], m["confidence"]["reliability"], m["risk"]["status"], snapshot["source_fingerprint"]]
        r=m["risk"]
        values += [snapshot.get("risk_interface",{}).get("contract"),r.get("binding_id"),r.get("evidence_status"),r.get("consumer_coverage"),r.get("merchant_coverage"),r.get("consumer_recency_days"),r.get("merchant_recency_days"),"|".join(r.get("review_flags",[]))]
        # Guard spreadsheet formulas in source-provided text without changing numbers.
        writer.writerow(["'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v for v in values])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def handler_for(adapter):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, value):
            self.send(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            # Reject foreign Host headers to avoid DNS rebinding against private outputs.
            if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
                self.send_json(403, {"error": "Localhost access only"})
                return
            route = urlsplit(self.path)
            try:
                if route.path == "/api/catalog":
                    self.send_json(200, adapter.catalog())
                elif route.path == "/api/workflow":
                    params = parse_qs(route.query)
                    if set(params) != {"run", "split", "cutoff"} or any(len(v) != 1 for v in params.values()):
                        raise ContractError("Specify one run, split and cutoff")
                    self.send_json(200, workflow(adapter, **{k: v[0] for k, v in params.items()}))
                elif route.path in ("/api/snapshot", "/api/export"):
                    params = parse_qs(route.query)
                    if set(params) != {"run", "split", "cutoff", "scenario"} or any(len(v) != 1 for v in params.values()):
                        raise ContractError("Specify one run, split, cutoff and scenario")
                    snapshot = adapter.snapshot(**{k: v[0] for k, v in params.items()})
                    if route.path == "/api/snapshot":
                        self.send_json(200, snapshot)
                    else:
                        filename = f"{snapshot['run']}_{snapshot['cutoff']}_{snapshot['scenario']}_shortlist.csv"
                        self.send(200, shortlist_csv(snapshot), "text/csv; charset=utf-8", filename)
                elif route.path in STATIC_FILES:
                    path = STATIC / STATIC_FILES[route.path]
                    self.send(200, path.read_bytes(), (mimetypes.guess_type(path)[0] or "application/octet-stream") + "; charset=utf-8")
                elif route.path == "/favicon.ico":
                    self.send(204, b"", "image/x-icon")
                else:
                    self.send_json(404, {"error": "Unknown route"})
            except ContractError as exc:
                self.send_json(422, {"error": str(exc), "code": "ENGINE_CONTRACT_ERROR"})
            except Exception:
                self.send_json(500, {"error": "Unable to load engine outputs. Check the source run and adapter configuration."})

        def log_message(self, fmt, *args):
            # Do not log merchant records or query strings.
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, default=STATIC.parent.parent / "ads project 2-engines")
    parser.add_argument("--config", type=Path, default=STATIC / "adapter-config.json")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
    adapter = SourceRegistry(args.engine_root, config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(adapter))
    print(f"Dashboard: http://127.0.0.1:{args.port}/ | source: {adapter.root.name} | read-only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

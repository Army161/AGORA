"""Stripe webhook receiver.

Run alongside the Agora server so subscription changes reach the entitlement
store:

    export STRIPE_WEBHOOK_SECRET=whsec_...
    python billing/webhook_server.py --rooms-dir ~/.agora --port 8850

Point Stripe at https://your-host/stripe/webhook. For local development:

    stripe listen --forward-to localhost:8850/stripe/webhook

Standard library only, so it runs anywhere the Agora server runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stripe_gateway import verify_webhook, handle_event  # noqa: E402

ROOMS_DIR = None
MAX_BODY = 1 << 20  # 1 MiB. Stripe events are small; anything larger is not one.


def _resolve_workspace(workspace_id: str):
    """Map a workspace id to a directory under the rooms dir.

    Rejects anything that is not a plain name. A workspace id arrives from an
    external webhook, so treating it as a path component without checking would
    let a crafted id write outside the rooms directory.
    """
    if not workspace_id or "/" in workspace_id or "\\" in workspace_id or workspace_id.startswith("."):
        return None
    path = os.path.join(ROOMS_DIR, workspace_id)
    root = os.path.abspath(ROOMS_DIR)
    if not os.path.abspath(path).startswith(root + os.sep):
        return None
    return path


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") != "/stripe/webhook":
            return self._send(404, {"error": "not found"})

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad content-length"})
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"error": "payload too large"})

        payload = self.rfile.read(length)
        signature = self.headers.get("Stripe-Signature", "")

        try:
            event = verify_webhook(payload, signature)
        except Exception as exc:
            # Never reveal why verification failed — that is a probing oracle.
            self.log_message("webhook rejected: %s", exc)
            return self._send(400, {"error": "signature verification failed"})

        try:
            result = handle_event(event, _resolve_workspace)
        except Exception as exc:  # pragma: no cover
            self.log_message("handler error: %s", exc)
            # 500 tells Stripe to retry, which is right for a transient fault.
            return self._send(500, {"error": "handler error"})

        # 200 even when ignored, or Stripe retries an event we will never want.
        self.log_message("ok: %s", result or f"ignored {event.get('type')}")
        return self._send(200, {"received": True, "applied": result})

    def log_message(self, fmt, *args):
        sys.stderr.write("[webhook] " + (fmt % args) + "\n")


def main():
    global ROOMS_DIR
    ap = argparse.ArgumentParser(description="Agora Stripe webhook receiver")
    ap.add_argument("--rooms-dir", default=os.environ.get("AGORA_ROOMS_DIR", "~/.agora"),
                    help="Directory containing one folder per workspace")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8850)
    args = ap.parse_args()

    ROOMS_DIR = os.path.abspath(os.path.expanduser(args.rooms_dir))
    os.makedirs(ROOMS_DIR, exist_ok=True)

    if not os.environ.get("STRIPE_WEBHOOK_SECRET"):
        sys.stderr.write("STRIPE_WEBHOOK_SECRET is not set — every webhook will be rejected.\n")

    print(f"Agora webhook receiver on http://{args.host}:{args.port}/stripe/webhook")
    print(f"Rooms dir: {ROOMS_DIR}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

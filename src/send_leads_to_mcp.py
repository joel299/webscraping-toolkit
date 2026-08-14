#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def split_phone(row: dict) -> tuple[str, str]:
    phone = (row.get("telefone_whatsapp") or row.get("phone") or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    national = digits[2:] if digits.startswith("55") else digits
    if len(national) >= 11 and national[2:3] == "9":
        return "", phone
    return phone, ""


def lead_payload(row: dict) -> dict:
    telefone, celular = split_phone(row)
    return {
        "nome_barbearia": row.get("nome") or row.get("name") or "",
        "site": row.get("site_instagram") or row.get("site") or row.get("website") or "",
        "endereco": row.get("endereco") or row.get("address") or "",
        "telefone": telefone,
        "celular": celular,
        "email": row.get("email") or "",
        "google": row.get("google_maps") or row.get("maps_url") or row.get("google") or "",
    }


def parse_sse_json(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data:"):
            text = line[5:].strip()
            if text:
                return json.loads(text)
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body}


class McpClient:
    def __init__(self, url: str):
        self.url = url
        self.session = None
        self.next_id = 1

    def post(self, payload: dict) -> tuple[bool, int | None, dict, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "user-agent": "Hermes-Stark/lead-sender",
        }
        if self.session:
            headers["mcp-session-id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read(4000).decode("utf-8", "ignore")
                if not self.session:
                    self.session = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
                parsed = parse_sse_json(body)
                return 200 <= r.status < 300, r.status, parsed, body
        except urllib.error.HTTPError as e:
            body = e.read(4000).decode("utf-8", "ignore")
            return False, e.code, parse_sse_json(body), body
        except Exception as e:
            return False, None, {"error": str(e)}, str(e)

    def request(self, method: str, params: dict | None = None) -> tuple[bool, int | None, dict, str]:
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        return self.post(payload)

    def notify(self, method: str, params: dict | None = None) -> tuple[bool, int | None, dict, str]:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        return self.post(payload)

    def initialize(self) -> None:
        ok, status, parsed, body = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Hermes Stark", "version": "1.0"},
        })
        if not ok or not self.session:
            raise RuntimeError(f"MCP initialize failed status={status} response={parsed or body}")
        self.notify("notifications/initialized", {})

    def send_lead(self, lead: dict) -> tuple[bool, int | None, dict, str]:
        arguments = {
            "parameters0_Value": lead.get("nome_barbearia", ""),
            "parameters1_Value": lead.get("site", ""),
            "parameters2_Value": lead.get("endereco", ""),
            "parameters3_Value": lead.get("telefone", ""),
            "parameters4_Value": lead.get("celular", ""),
            "parameters5_Value": lead.get("google", ""),
            "parameters6_Value": lead.get("email", ""),
        }
        ok, status, parsed, body = self.request("tools/call", {"name": "sheets", "arguments": arguments})
        if isinstance(parsed, dict):
            parsed.setdefault("called_tool", "sheets")
            parsed.setdefault("called_method", "tools/call")
        return ok, status, parsed, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--webhook", default=os.environ.get("LEADS_WEBHOOK_URL", ""))
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--only-with-phone", action="store_true", default=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0, help="Skip first N filtered rows")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default="send_leads_to_mcp.log")
    args = ap.parse_args()

    path = Path(args.input)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if args.only_with_phone:
        rows = [r for r in rows if (r.get("telefone_whatsapp") or r.get("phone") or "").strip()]
    total_filtered = len(rows)
    if args.offset:
        rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]

    client = None
    if not args.dry_run:
        client = McpClient(args.webhook)
        client.initialize()

    sent = 0
    failed = 0
    failures = []
    log_path = Path(args.log)
    with log_path.open("a", encoding="utf-8") as log:
        for idx, row in enumerate(rows, 1 + args.offset):
            payload = lead_payload(row)
            if args.dry_run:
                ok, status, parsed, body = True, 0, {"dry_run": True}, "dry-run"
            else:
                ok, status, parsed, body = client.send_lead(payload)
            event = {
                "idx": idx,
                "ok": ok,
                "status": status,
                "nome_barbearia": payload["nome_barbearia"],
                "telefone": payload["telefone"],
                "celular": payload["celular"],
                "mcp_result": parsed,
            }
            log.write(json.dumps(event, ensure_ascii=False) + "\n")
            log.flush()
            if ok and not parsed.get("error"):
                sent += 1
            else:
                failed += 1
                if len(failures) < 10:
                    failures.append(event)
            if idx < args.offset + len(rows):
                time.sleep(args.interval)
    print(json.dumps({
        "ok": failed == 0,
        "input": str(path),
        "webhook": args.webhook,
        "interval_seconds": args.interval,
        "total_filtered_with_phone": total_filtered,
        "offset": args.offset,
        "rows_considered": len(rows),
        "sent": sent,
        "failed": failed,
        "dry_run": args.dry_run,
        "log": str(log_path),
        "failures_sample": failures,
    }, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

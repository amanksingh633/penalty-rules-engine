"""Command line interface: evaluate, list, confirm, reject, charge, verify-audit."""

from __future__ import annotations

import argparse
import sys

from .engine import evaluate
from .models import load_trips
from .rules import RuleError, load_rules
from .store import TicketStore, WorkflowError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="penalty-engine", description=__doc__)
    p.add_argument("--store", default=".penalty-store", help="Directory for tickets and audit log")
    sub = p.add_subparsers(dest="command", required=True)

    ev = sub.add_parser("evaluate", help="Apply rules to trips and open review tickets")
    ev.add_argument("trips", help="Trips CSV")
    ev.add_argument("rules", help="Rules JSON")

    ls = sub.add_parser("list", help="List tickets")
    ls.add_argument("--status", choices=["PENDING_REVIEW", "CONFIRMED", "REJECTED", "CHARGED"])

    for name in ("confirm", "reject"):
        c = sub.add_parser(name, help=f"{name.capitalize()} a ticket as a named reviewer")
        c.add_argument("ticket_id")
        c.add_argument("--reviewer", required=True)
        c.add_argument("--note", default="")

    ch = sub.add_parser("charge", help="Charge a CONFIRMED ticket")
    ch.add_argument("ticket_id")
    ch.add_argument("--actor", required=True)

    sub.add_parser("verify-audit", help="Check the audit log hash chain")
    return p


def _print_tickets(rows: list[dict]) -> None:
    if not rows:
        print("no tickets")
        return
    print(f"{'TICKET':<16}{'STATUS':<16}{'LEVEL':<9}{'ENTITY':<10}{'RULE':<22}{'AMOUNT':>9}")
    for t in rows:
        print(
            f"{t['ticket_id']:<16}{t['status']:<16}{t['level']:<9}{t['entity_id']:<10}"
            f"{t['rule_id']:<22}{t['proposed_amount']:>9.2f}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = TicketStore(args.store)
    try:
        if args.command == "evaluate":
            findings = evaluate(load_trips(args.trips), load_rules(args.rules))
            created = store.add_findings(findings)
            print(f"{len(findings)} findings, {len(created)} new tickets (all PENDING_REVIEW)")
            _print_tickets([store.tickets[i] for i in created])
        elif args.command == "list":
            _print_tickets(store.list(args.status))
        elif args.command in ("confirm", "reject"):
            fn = store.confirm if args.command == "confirm" else store.reject
            t = fn(args.ticket_id, args.reviewer, args.note)
            print(f"{t['ticket_id']} -> {t['status']} by {args.reviewer}")
        elif args.command == "charge":
            t = store.charge(args.ticket_id, args.actor)
            print(f"{t['ticket_id']} -> {t['status']} ({t['proposed_amount']:.2f})")
        elif args.command == "verify-audit":
            ok, msg = store.verify_audit()
            print(msg)
            return 0 if ok else 1
    except (RuleError, WorkflowError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

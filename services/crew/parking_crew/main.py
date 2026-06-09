"""CLI entry point: parking-crew audit | tools-preflight | list-regions"""

from __future__ import annotations

import argparse
import json
import sys

from parking_crew.env import configured_secret_keys, load_crew_env
from parking_crew.kickoff import run_full_crew, run_tools_preflight
from parking_crew.observability import verify_langfuse_connection
from parking_crew.regions import default_audit_inputs, priority_county_fips, region_name_for_fips


def _cmd_secrets_status(_: argparse.Namespace) -> int:
    load_crew_env()
    from parking_crew.runtime import runtime_label

    print(
        json.dumps(
            {"runtime": runtime_label(), "configured": configured_secret_keys()},
            indent=2,
        )
    )
    return 0


def _cmd_list_regions(_: argparse.Namespace) -> int:
    for fips in priority_county_fips():
        print(f"{fips}\t{region_name_for_fips(fips)}")
    return 0


def _cmd_langfuse_check(_: argparse.Namespace) -> int:
    load_crew_env()
    status = verify_langfuse_connection()
    print(json.dumps(status, indent=2))
    return 0 if status.get("authenticated") else 1


def _cmd_tools_preflight(args: argparse.Namespace) -> int:
    report = run_tools_preflight(
        args.county_fips,
        min_score=args.min_score,
        lookback_hours=args.lookback_hours,
    )
    print(json.dumps(report, indent=2))
    if args.quiet:
        print(f"Wrote {report.get('output_file')}", file=sys.stderr)
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.tools_only:
        return _cmd_tools_preflight(args)

    load_crew_env()
    if not _llm_configured():
        print(
            "No LLM API key found (set OPENAI_API_KEY, ANTHROPIC_API_KEY, or CREWAI_LLM). "
            "Running tools-only preflight instead.\n",
            file=sys.stderr,
        )
        return _cmd_tools_preflight(args)

    result = run_full_crew(
        args.county_fips,
        lookback_hours=args.lookback_hours,
        qualified_score_threshold=args.min_score,
    )
    print(result)
    return 0


def _llm_configured() -> bool:
    import os

    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY", "CREWAI_LLM"):
        if (os.getenv(key) or "").strip():
            return True
    return False


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--county-fips",
        default=None,
        help=f"5-digit FIPS (default: first priority market, currently {priority_county_fips()[0]})",
    )
    parser.add_argument("--lookback-hours", type=int, default=168)
    parser.add_argument("--min-score", type=float, default=70.0, help="Qualified parcel threshold")
    parser.add_argument("-q", "--quiet", action="store_true", help="Less stdout; still writes output file")


def build_parser() -> argparse.ArgumentParser:
    defaults = default_audit_inputs()
    parser = argparse.ArgumentParser(
        prog="parking-crew",
        description="Parkinglot CrewAI audit — zoning, revenue, FinOps",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-regions", help="Print priority county FIPS from geo_markets.yaml")
    p_list.set_defaults(func=_cmd_list_regions)

    p_secrets = sub.add_parser(
        "secrets-status",
        help="Show which credentials are loaded (names only, never values)",
    )
    p_secrets.set_defaults(func=_cmd_secrets_status)

    p_langfuse = sub.add_parser(
        "langfuse-check",
        help="Verify Langfuse keys in .env (does not print secrets)",
    )
    p_langfuse.set_defaults(func=_cmd_langfuse_check)

    p_preflight = sub.add_parser(
        "tools-preflight",
        help="Run all custom tools without LLM (DB, search, GitHub draft, logs, Slack dry-run)",
    )
    _add_common_args(p_preflight)
    p_preflight.set_defaults(func=_cmd_tools_preflight)

    p_audit = sub.add_parser(
        "audit",
        help="Full CrewAI audit (falls back to tools-preflight if no LLM key)",
    )
    _add_common_args(p_audit)
    p_audit.add_argument(
        "--tools-only",
        action="store_true",
        help="Skip LLM agents; only exercise custom tools",
    )
    p_audit.set_defaults(func=_cmd_audit)

    parser.set_defaults(
        default_county=defaults["county_fips"],
        default_region=defaults["region_name"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

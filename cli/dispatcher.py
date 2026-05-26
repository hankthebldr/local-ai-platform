"""Single-entry `enclave` CLI dispatcher.

Routes subcommands to the existing per-module CLIs without duplicating
their argument parsing. The intent is to give users one memorable verb
(`enclave`) while keeping each underlying module independently runnable
as `python -m cli.chat`, `python -m cli.workflow`, etc.

Subcommands:
    enclave api                Start the FastAPI server (uvicorn).
    enclave chat [args...]     Interactive chat CLI (cli.chat).
    enclave query <q> [args]   One-shot prompt (cli.query).
    enclave workflow <args>    Workflow runner / inspector (cli.workflow).
    enclave version            Print the installed package version + exit.

Anything after the subcommand is forwarded verbatim to that CLI, so
`enclave chat --model llama3.2:3b` is identical to
`python -m cli.chat --model llama3.2:3b`.
"""
from __future__ import annotations

import sys
from typing import Callable, Dict


def _print_help() -> None:
    print(__doc__.strip(), file=sys.stderr)


def _print_version() -> None:
    from api import __version__

    print(f"enclave {__version__}")


def _run_api() -> None:
    from api.main import run_server

    run_server()


def _run_chat() -> None:
    from cli.chat import main as chat_main

    chat_main()


def _run_query() -> None:
    from cli.query import main as query_main

    query_main()


def _run_workflow() -> None:
    from cli.workflow import main as workflow_main

    workflow_main()


SUBCOMMANDS: Dict[str, Callable[[], None]] = {
    "api": _run_api,
    "chat": _run_chat,
    "query": _run_query,
    "workflow": _run_workflow,
    "version": _print_version,
    "--version": _print_version,
    "-v": _print_version,
    "help": _print_help,
    "--help": _print_help,
    "-h": _print_help,
}


def main() -> None:
    if len(sys.argv) < 2:
        _print_help()
        sys.exit(2)

    subcommand = sys.argv[1]
    handler = SUBCOMMANDS.get(subcommand)
    if handler is None:
        print(f"enclave: unknown subcommand {subcommand!r}", file=sys.stderr)
        _print_help()
        sys.exit(2)

    # Strip the dispatcher's own argv[1] so the underlying CLI sees its
    # own argv[0] (the subcommand name) and the user's remaining args.
    sys.argv = [f"enclave-{subcommand}", *sys.argv[2:]]
    handler()


if __name__ == "__main__":
    main()

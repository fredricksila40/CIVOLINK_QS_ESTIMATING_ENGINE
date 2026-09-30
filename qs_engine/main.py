"""CIVOLINK QS entry launcher (Phase 21): CLI / server / desktop modes.

Dispatch only — no calculation, no widgets here. Heavy imports
(tkinter UI, FastAPI server) stay inside the mode runners so
``--help`` and parsing never need a display or a web stack.
"""

import argparse
import sys
import threading

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8000


def parse_args(argv=None):
    """Parse launcher flags (pure; never launches anything)."""
    parser = argparse.ArgumentParser(
        prog="civolink",
        description="CIVOLINK QS Estimating Engine launcher")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cli", action="store_true",
                       help="run the read-only dashboard CLI and exit")
    group.add_argument("--server", action="store_true",
                       help="serve the FastAPI REST API in the foreground")
    parser.add_argument("--with-api", action="store_true",
                        help="with the desktop UI, also serve the REST API "
                             "on a background daemon thread")
    parser.add_argument("--api-host", default=DEFAULT_API_HOST,
                        help="API bind host (default %(default)s)")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT,
                        help="API bind port (default %(default)s)")
    return parser.parse_args(argv)


def resolve_mode(args) -> str:
    """Map parsed flags to a mode name (pure; headless-testable)."""
    if args.cli:
        return "cli"
    if args.server:
        return "server"
    return "gui"


def run_cli() -> int:
    """Run the read-only dashboard CLI (headless-safe)."""
    from qs_engine.cli import main as cli_main
    return cli_main([])


def _serve_api(host: str, port: int) -> None:
    """Blocking API serve (thread target for background mode)."""
    import uvicorn
    uvicorn.run("qs_engine.web.api:app", host=host, port=port,
                log_level="warning")


def make_api_thread(host: str = DEFAULT_API_HOST,
                    port: int = DEFAULT_API_PORT) -> threading.Thread:
    """Build the background API thread (unstarted; daemonized).

    Returned unstarted so tests can assert daemonization without
    binding any port.
    """
    return threading.Thread(target=_serve_api, args=(host, port),
                            name="civolink-api", daemon=True)


def run_server(host: str = DEFAULT_API_HOST,
               port: int = DEFAULT_API_PORT) -> int:
    """Serve the REST API in the foreground (blocking)."""
    try:
        from qs_engine.web.server import main as serve_main
        import qs_engine.web.server as server_module
    except ImportError as exc:
        print(f"Cannot start the API server: {exc}", file=sys.stderr)
        return 3
    server_module.HOST, server_module.PORT = host, port
    serve_main()
    return 0


def run_desktop(with_api: bool = False,
                api_host: str = DEFAULT_API_HOST,
                api_port: int = DEFAULT_API_PORT) -> int:
    """Launch the Tkinter desktop shell (blocking; needs a display)."""
    if with_api:
        make_api_thread(api_host, api_port).start()
    from qs_engine.ui.views import launch
    launch()
    return 0


def main(argv=None) -> int:
    """Dispatch on launcher flags (returns a process exit code)."""
    args = parse_args(argv)
    mode = resolve_mode(args)
    if mode == "cli":
        return run_cli()
    if mode == "server":
        return run_server(args.api_host, args.api_port)
    return run_desktop(with_api=args.with_api, api_host=args.api_host,
                       api_port=args.api_port)


if __name__ == "__main__":
    sys.exit(main())

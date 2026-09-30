"""Uvicorn launcher (Phase 18): serve the QS REST API locally.

Run from the repository root either as
``python -m qs_engine.web.server`` or ``python qs_engine/web/server.py``.
"""

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    """Launch the API on 127.0.0.1:8000 (docs at /docs)."""
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Serving the API needs the 'uvicorn' package "
            "(pip install uvicorn)") from exc
    from qs_engine.web.api import api_token
    print("CIVOLINK QS API requires bearer auth on every endpoint.")
    print(f"Local API token: {api_token}")
    print(f"  curl -H \"Authorization: Bearer {api_token}\" "
          f"http://127.0.0.1:{PORT}/health")
    uvicorn.run("qs_engine.web.api:app", host=HOST, port=PORT)


if __name__ == "__main__":
    main()

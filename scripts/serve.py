"""Start the Yatra AI web app.

    python -m scripts.serve            # http://127.0.0.1:8000
    python -m scripts.serve --reload   # auto-restart when code changes (development)
"""
import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    print(f"\n  Yatra AI is running at http://{args.host}:{args.port}  (Ctrl+C to stop)\n")
    uvicorn.run("yatra.api.main:app", host=args.host, port=args.port, reload=args.reload,
                log_level="warning")


if __name__ == "__main__":
    main()

"""Run the ValueGraph Engine: ``python -m services.engine``.

Equivalent to ``uvicorn services.engine.main:app``. Host/port/reload come from env
(ENGINE_HOST / ENGINE_PORT / ENGINE_RELOAD).
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "services.engine.main:app",
        host=os.environ.get("ENGINE_HOST", "127.0.0.1"),
        port=int(os.environ.get("ENGINE_PORT", "8000")),
        reload=bool(os.environ.get("ENGINE_RELOAD")),
    )


if __name__ == "__main__":
    main()

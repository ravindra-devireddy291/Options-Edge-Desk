"""Pre-market TRADE_CARD markdown per book (read-only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.books.adapters import BookPaths
from app.session import session_day


def _card_path(book: BookPaths, day: str) -> Path:
    return book.shadow_dir / f"TRADE_CARD_{day}.md"


def brief_payload(
    books: Sequence[BookPaths],
    *,
    day: Optional[str] = None,
) -> Dict[str, Any]:
    day_s = (day or "").strip() or session_day().isoformat()
    out: List[Dict[str, Any]] = []
    errors: List[str] = []
    for book in books:
        path = _card_path(book, day_s)
        if not path.exists():
            out.append(
                {
                    "underlying": book.name,
                    "exists": False,
                    "markdown": None,
                    "path": f"reports/shadow/TRADE_CARD_{day_s}.md",
                }
            )
            errors.append(f"{book.name}:TRADE_CARD missing")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            out.append(
                {
                    "underlying": book.name,
                    "exists": False,
                    "markdown": None,
                    "path": f"reports/shadow/TRADE_CARD_{day_s}.md",
                }
            )
            errors.append(f"{book.name}:TRADE_CARD read_error:{exc}")
            continue
        # Soft cap for UI — cards are short; truncate pathological files
        if len(text) > 50_000:
            text = text[:50_000] + "\n\n…[truncated]"
        out.append(
            {
                "underlying": book.name,
                "exists": True,
                "markdown": text,
                "path": f"reports/shadow/TRADE_CARD_{day_s}.md",
            }
        )
    return {"day": day_s, "books": out, "errors": errors}

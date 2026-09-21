from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import UTC, datetime

_WS = re.compile(r"\s+")


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def norm_ws(text: str) -> str:
    """Ограниченная нормализация для сверки цитат: пробелы/переносы, NBSP, типографские кавычки/дефисы."""
    t = unicodedata.normalize("NFKC", text).replace("­", "")
    t = t.replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"').replace("‑", "-").replace("–", "-").replace("—", "-")
    return _WS.sub(" ", t).strip().lower()


def safe_filename(name: str, default: str = "file") -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^\w.\-() ]+", "_", base, flags=re.UNICODE).strip(" .")
    return (base[:120] or default)


_TR = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
                     "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
                     "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"})


def translit(text: str) -> str:
    """Транслитерация для имён файлов: кириллица → латиница, прочее → «_»."""
    out = "".join((ch.lower().translate(_TR).capitalize() if ch.isupper() else ch.translate(_TR)) for ch in text)
    return re.sub(r"[^A-Za-z0-9]+", "_", out).strip("_")


def est_tokens(text: str, chars_per_token: float = 2.6) -> int:
    return max(1, int(len(text) / chars_per_token))


_STEM_STOP = {"который", "которая", "которые", "также", "может", "можно", "нужно", "должен", "между", "после", "когда", "этого", "этой", "чтобы"}


def stems(text: str, n: int = 5) -> set[str]:
    """Грубые основы слов (префикс n символов) для дешёвых лексических проверок."""
    words = re.findall(r"[а-яёa-z0-9]{4,}", text.lower())
    return {w[:n] for w in words if w not in _STEM_STOP}

import re
from typing import Any, Dict, Iterable, Optional

CNJ_RE = re.compile(r"\D+")


def cnj_digits(s: str | None) -> Optional[str]:
    if not s:
        return None
    digits = CNJ_RE.sub("", s)
    return digits if len(digits) == 20 else None


def cnj_mask(digits20: str | None) -> Optional[str]:
    if not digits20 or len(digits20) != 20:
        return None
    return f"{digits20[0:7]}-{digits20[7:9]}.{digits20[9:13]}.{digits20[13:14]}.{digits20[14:16]}.{digits20[16:20]}"


def get_in(d: Dict[str, Any], dotted_path: str) -> Any:
    cur: Any = d
    for part in dotted_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def first_present(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        val = get_in(d, k) if "." in k else d.get(k)
        if val not in (None, "", []):
            return val
    return None

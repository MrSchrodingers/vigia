import json
import re
import logging
from typing import Any, Dict, Union
logger = logging.getLogger(__name__)

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find('\n')
        if nl != -1 and nl < 12:
            s = s[nl+1:]
    return s.strip()

def _escape_newlines_inside_strings(s: str) -> str:
    out, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if ch == '\n': 
                out.append('\\n')
                continue
            if ch == '\r': 
                out.append('\\r')
                continue
            if esc: 
                esc = False
                out.append(ch)
                continue
            if ch == '\\': 
                esc = True
                out.append(ch)
                continue
            if ch == '"': 
                in_str = False
                out.append(ch)
                continue
            out.append(ch)
            continue
        else:
            out.append(ch)
            if ch == '"': 
                in_str = True
    return ''.join(out)

def _fix_trailing_commas(s: str) -> str:
    # ,}  -> }
    # ,]  -> ]
    return re.sub(r',\s*([}\]])', r'\1', s)

def _drop_stray_closing_brace_at_level1(s: str) -> str:
    """
    Remove um '}' indevido quando estamos no nível 1 e logo em seguida vem ', "chave"'.
    Isso converte '... "campo":"...", }, "outra": ...' em '... "campo":"...", "outra": ...'
    """
    out = []
    i, n = 0, len(s)
    depth = 0
    in_str = False
    esc = False
    while i < n:
        ch = s[i]
        if in_str:
            out.append(ch)
            if esc: 
                esc = False
            elif ch == '\\': 
                esc = True
            elif ch == '"': 
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == '{':
            depth += 1
            out.append(ch)
            i += 1
            continue
        if ch == '}':
            # lookahead: espaços + vírgula + espaços + aspas
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            if depth == 1 and j < n and s[j] == ',':
                k = j + 1
                while k < n and s[k].isspace():
                    k += 1
                if k < n and s[k] == '"':
                    # drop this brace (não adiciona)
                    i += 1
                    continue
            # remove vírgula pendurada imediatamente antes de }
            while out and out[-1].isspace():
                out.pop()
            if out and out[-1] == ',':
                out.pop()
            depth -= 1
            out.append('}')
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)

def _extract_first_balanced_json(s: str) -> str:
    depth = 0
    in_str = False
    esc = False
    started = False
    buf = []
    for ch in s:
        if in_str:
            buf.append(ch)
            if esc: 
                esc = False
            elif ch == '\\': 
                esc = True
            elif ch == '"': 
                in_str = False
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
            continue
        if ch == '{':
            depth += 1
            started = True
            buf.append(ch)
            continue
        if ch == '}':
            if started:
                depth -= 1
                buf.append(ch)
                if depth == 0:
                    return ''.join(buf)
                continue
        if started:
            buf.append(ch)
    raise ValueError("No balanced JSON object found")

def safe_json_loads(text: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(text, dict):
        return text
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    if not isinstance(text, str):
        logger.error("safe_json_loads recebeu %s", type(text))
        return {}

    s = _strip_code_fences(text)

    # 1) tentativa direta
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) reparos leves
    s2 = _fix_trailing_commas(s)
    s2 = _drop_stray_closing_brace_at_level1(s2)
    s2 = _escape_newlines_inside_strings(s2)
    try:
        return json.loads(s2)
    except Exception:
        pass

    # 3) fallback: primeiro objeto balanceado
    try:
        cand = _extract_first_balanced_json(s2)
        return json.loads(cand)
    except Exception as e:
        logger.error("Falha ao reparar JSON: %s", e)
        raise



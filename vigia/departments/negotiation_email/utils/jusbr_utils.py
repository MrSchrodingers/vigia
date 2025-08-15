# vigia/services/jusbr_utils.py
from typing import List, Dict, Any

def build_timeline(tramitacao_atual: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Constrói uma timeline determinística a partir de 'movimentos' e 'documentos'.
    Cada item: {"data": "YYYY-MM-DD", "descricao": "...", "tipo": "MOVIMENTO|DECISAO|JUNTADA", "doc_ref": str|None}
    """
    tl: List[Dict[str, Any]] = []

    # Movimentos
    for mov in tramitacao_atual.get("movimentos", []) or []:
        desc = (mov.get("descricao") or "").strip()
        tipo = "DECISAO" if any(k in desc.upper() for k in ["DECIS", "DESPACHO"]) else "MOVIMENTO"
        tl.append({
            "data": (mov.get("dataHora") or "")[:10],
            "descricao": desc,
            "tipo": tipo,
            "doc_ref": None
        })

    # Juntadas de documentos
    for doc in tramitacao_atual.get("documentos", []) or []:
        tipo_doc = (doc.get("tipo", {}) or {}).get("nome") or (doc.get("tipo", {}) or {}).get("codigo") or "DOC"
        nome = doc.get("nome") or str(doc.get("idCodex") or "")
        tl.append({
            "data": (doc.get("dataHoraJuntada") or "")[:10],
            "descricao": f"Juntada: {tipo_doc} - {nome}",
            "tipo": "JUNTADA",
            "doc_ref": nome or str(doc.get("idCodex") or "")
        })

    tl.sort(key=lambda x: x["data"] or "")
    return tl


def build_evidence_index(root: dict) -> dict:
    """
    Constrói um índice leve de evidências para citação:
    {
      "docs": { "<doc_id>": {"label": "NOME (doc_id)", "data": "YYYY-MM-DD", "tipo": "CONTESTAÇÃO", "url": "..."} },
      "moves": [ {"data":"YYYY-MM-DD","descricao":"...","tipo":"MOVIMENTO","doc_ref":"<doc_id>"} ]
    }
    """
    docs = {}
    for d in root.get("documentos") or []:
        doc_id = d.get("id") or d.get("documentoId")
        if not doc_id:
            continue
        docs[doc_id] = {
            "label": f'{(d.get("nome") or d.get("titulo") or "Documento")[:120]} ({doc_id})',
            "data": d.get("data") or d.get("dataJuntada") or "",
            "tipo": d.get("tipo") or d.get("categoria") or "",
            "url": d.get("url") or d.get("downloadUrl") or None,
        }

    moves = []
    for it in (root.get("timeline_pre") or []):
        moves.append({
            "data": it.get("data") or "",
            "descricao": it.get("descricao") or "",
            "tipo": it.get("tipo") or "MOVIMENTO",
            "doc_ref": it.get("doc_ref") or None
        })

    return {"docs": docs, "moves": moves}
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import json

from db import models
from vigia.departments.negotiation_email.core.orchestrator import HTML_SECTION_BORDER
from vigia.services import llm_service
from vigia.departments.negotiation_email.utils.jusbr_utils import build_timeline, build_evidence_index
from vigia.departments.negotiation_email.utils import clean_html_body
from vigia.departments.negotiation_email.agents.judicial_jury_agents import ARBITER_SCHEMA

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _format_summary_for_note(summary_data: Dict[str, Any]) -> str:
    """Formata o JSON do sumário em HTML enxuto para a nota do Pipedrive."""
    if not summary_data or "erro" in summary_data:
        return "<i>Erro ao gerar o sumário da análise.</i>"

    parts = [f'<div {HTML_SECTION_BORDER}><h2>📝 Resumo da Análise da Negociação</h2></div>']

    # Resumo executivo
    se = summary_data.get("sumario_executivo")
    if se:
        parts.append(f'<div {HTML_SECTION_BORDER}><h4>Resumo Executivo</h4><p>{se}</p></div>')

    # Status
    status_info = summary_data.get("status_e_proximos_passos") or {}
    if status_info.get("status_atual"):
        parts.append(f'<div {HTML_SECTION_BORDER}><h4>Status Atual</h4><p><strong>{status_info["status_atual"]}</strong></p></div>')

    # Histórico
    historico = summary_data.get("historico_negociacao") or {}
    if historico:
        hp = [f'<div {HTML_SECTION_BORDER}><h4>Histórico da Negociação</h4>']
        if historico.get("fluxo"):
            hp.append(f'<p>{historico["fluxo"]}</p>')

        # Cliente
        cli_args = historico.get("argumentos_cliente")
        if cli_args:
            hp.append('<strong>Argumentos do Cliente:</strong>')
            if isinstance(cli_args, list):
                hp.append('<ul>')
                hp.extend(f'<li>{a}</li>' for a in cli_args)
                hp.append('</ul>')
            else:
                hp.append(f'<p><i>{cli_args}</i></p>')

        # Internos
        int_args = historico.get("argumentos_internos")
        if int_args:
            hp.append('<br><strong>Nossos Argumentos:</strong>')
            if isinstance(int_args, list):
                hp.append('<ul>')
                hp.extend(f'<li>{a}</li>' for a in int_args)
                hp.append('</ul>')
            else:
                hp.append(f'<p><i>{int_args}</i></p>')

        hp.append('</div>')
        parts.append("".join(hp))

    return "".join(parts)

def _serialize_doc_for_context(doc: models.ProcessDocument) -> Dict[str, Any]:
    return {
        "id": str(doc.id),
        "name": doc.name,
        "document_type": doc.document_type,
        "juntada_date": doc.juntada_date.isoformat() if doc.juntada_date else None,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "href_text": getattr(doc, "href_text", None),
        "href_binary": getattr(doc, "href_binary", None),
        "text_excerpt": (clean_html_body(doc.text_content)[:4000] if doc.text_content else None),
    }

def _find_next_hearing(movements: List[models.ProcessMovement]) -> Optional[str]:
    # Heurística simples: busca a movimentação com "Audiência" mais recente
    for m in sorted(movements, key=lambda x: (x.date or datetime.min), reverse=True):
        desc = (m.description or "").lower()
        if "audiência" in desc:
            return m.description
    return None

def _small_process_payload(proc: models.LegalProcess, docs: List[models.ProcessDocument], movs: List[models.ProcessMovement]) -> Dict[str, Any]:
    return {
        "process_number": proc.process_number,
        "classe_processual": getattr(proc, "classe_processual", None),
        "assunto": getattr(proc, "assunto", None),
        "orgao_julgador": getattr(proc, "orgao_julgador", None),
        "tribunal": getattr(proc, "tribunal", None),
        "valor_causa": getattr(proc, "valor_causa", None),
        "partes": [
            {
                "polo": p.polo,
                "name": p.name,
                "document_type": p.document_type,
                "document_number": p.document_number,
                "ajg": getattr(p, "ajg", None),
            } for p in (proc.parties or [])
        ] if hasattr(proc, "parties") and proc.parties else None,
        "next_hearing_hint": _find_next_hearing(movs),
        "documents_summary": [
            {
                "name": d.name,
                "type": d.document_type,
                "has_text": bool(d.text_content),
                "size": d.file_size,
                "juntada_date": d.juntada_date.isoformat() if d.juntada_date else None
            } for d in docs[:20]
        ],
    }

async def _ensure_json(obj_or_text: Any) -> Optional[Dict[str, Any]]:
    """Garante JSON usando o mesmo padrão já usado por você (expects_json=True)."""
    if isinstance(obj_or_text, dict):
        return obj_or_text
    try:
        return json.loads(obj_or_text)
    except Exception:
        return None

# -------------------------------------------------------------------------
# Pipeline Principal
# -------------------------------------------------------------------------
async def run_ai_jury_pipeline(proc: models.LegalProcess, db: Session) -> Dict[str, Any]:
    """Roda Resumo + Júri e retorna TODOS os artefatos gerados."""
    # Coleta de dados do banco
    docs = db.query(models.ProcessDocument).filter(models.ProcessDocument.process_id == proc.id) \
            .order_by(models.ProcessDocument.juntada_date.asc().nullsfirst()).all()
    movs = db.query(models.ProcessMovement).filter(models.ProcessMovement.process_id == proc.id) \
            .order_by(models.ProcessMovement.date.asc().nullsfirst()).all()

    # Insumos principais
    raw = getattr(proc, "raw_data", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    raw = raw or {}

    # build_timeline espera o objeto de tramitação, não o root
    timeline = build_timeline(raw.get("tramitacaoAtual", raw))

    # build_evidence_index espera um dict com "documentos" e (opcional) "timeline_pre"
    evidence_index = build_evidence_index({
        "documentos": [_serialize_doc_for_context(d) for d in docs],
        "timeline_pre": timeline,
    })

    small_payload = _small_process_payload(proc, docs, movs)

    # ================== 1) Contexto Legal Sintetizado ==================
    ctx_prompt = f"""
Você é um analista jurídico. Com base no processo, timeline e índice de evidências,
produza um CONTEXTO LEGAL em JSON (sem markdown), com os campos:
{{
  "causa_de_pedir": "",
  "tese_autora": "",
  "tese_reu": "",
  "pontos_controversos": [],
  "provas_relevantes": [],
  "riscos": [],
  "oportunidades": [],
  "marcos_procedimentais": []
}}
Entrada:
- Processo: {json.dumps(small_payload, ensure_ascii=False)}
- Timeline: {json.dumps(timeline, ensure_ascii=False)}
- EvidenceIndex: {json.dumps(evidence_index, ensure_ascii=False)}
"""
    legal_context_summary = await llm_service.llm_call(
        "Você sintetiza contexto jurídico em JSON estrito.",
        ctx_prompt,
        expects_json=True,
    )
    legal_context = await _ensure_json(legal_context_summary)

    # ================== 2) Extrações Estruturadas =====================
    extr_prompt = f"""
Extraia INFORMAÇÕES-CHAVE em JSON (sem markdown), com o formato:
{{
  "pedidos_autora": [],
  "defesas_reu": [],
  "valores_reclamados": [],
  "valores_comprovados": [],
  "precedentes_citados": [],
  "prazos_pendentes": []
}}
Considere especialmente as peças com texto e o contexto legal:
- ContextoLegal: {json.dumps(legal_context or {}, ensure_ascii=False)}
- Docs (até 20 com texto): {json.dumps([_serialize_doc_for_context(d) for d in docs if d.text_content][:20], ensure_ascii=False)}
"""
    extractions_raw = await llm_service.llm_call(
        "Você extrai campos jurídicos em JSON estrito.",
        extr_prompt,
        expects_json=True,
    )
    extractions = await _ensure_json(extractions_raw)

    # ================== 3) Resumo Formal ==============================
    sum_prompt = f"""
Escreva um RESUMO EXECUTIVO (claro e objetivo) e STATUS/PRÓXIMOS PASSOS.
Retorne JSON (sem markdown) no formato:
{{
  "sumario_executivo": "",
  "status_e_proximos_passos": {{
    "status_atual": "",
    "tarefas": [],
    "riscos": [],
    "oportunidades": []
  }}
}}
Insumos: Processo={json.dumps(small_payload, ensure_ascii=False)}
ContextoLegal={json.dumps(legal_context or {}, ensure_ascii=False)}
Extrações={json.dumps(extractions or {}, ensure_ascii=False)}
"""
    summary_raw = await llm_service.llm_call(
        "Você resume processos judiciais para executivos em JSON estrito.",
        sum_prompt,
        expects_json=True,
    )
    summary = await _ensure_json(summary_raw)

    # HTML amigável para CRM/nota
    notes_html = _format_summary_for_note(summary or {})

    # ================== 4) Opiniões (Conservadora x Estratégica) =====
    opinions_prompt = f"""
Duas opiniões em JSON (sem markdown):

1) "conservadora" (prudente, risco baixo), 2) "estrategica" (apetite de risco moderado).
Formato:
{{
  "conservadora": {{
    "tese": "",
    "pontos_fortes": [],
    "pontos_fracos": [],
    "faixa_acordo_recomendada": "",
    "recomendacoes": []
  }},
  "estrategica": {{
    "tese": "",
    "pontos_fortes": [],
    "pontos_fracos": [],
    "faixa_acordo_recomendada": "",
    "recomendacoes": []
  }}
}}

Baseie-se em ContextoLegal e Extrações.
Insumos:
- ContextoLegal: {json.dumps(legal_context or {}, ensure_ascii=False)}
- Extrações: {json.dumps(extractions or {}, ensure_ascii=False)}
"""
    opinions_raw = await llm_service.llm_call(
        "Você redige pareceres jurídicos táticos, em JSON estrito.",
        opinions_prompt,
        expects_json=True,
    )
    opinions = await _ensure_json(opinions_raw)

    # ================== 5) Júri (Árbitro) com Schema ==================
    arbiter_prompt = f"""
Aja como Árbitro. Retorne JSON estrito seguindo este SCHEMA (campos/formatos EXACTOS):
{json.dumps(ARBITER_SCHEMA, ensure_ascii=False)}

ContextoLegal: {json.dumps(legal_context or {}, ensure_ascii=False)}
Extrações: {json.dumps(extractions or {}, ensure_ascii=False)}
Opinioes: {json.dumps(opinions or {}, ensure_ascii=False)}
"""
    arbiter_json = await llm_service.llm_call(
        "Você é um árbitro jurídico: decide e justifica, obedecendo schema JSON.",
        arbiter_prompt,
        expects_json=True,
    )
    arbiter = await _ensure_json(arbiter_json)

    # Pacote completo para retorno/persistência
    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "process_id": str(proc.id),
        "process_number": proc.process_number,
        "inputs": {
            "small_payload": small_payload,
            "timeline": timeline,
            "evidence_index": evidence_index,
        },
        "legal_context": legal_context,
        "extractions": extractions,
        "summary": summary,
        "summary_html": notes_html,
        "opinions": opinions,
        "arbiter": arbiter,
        "raw_agent_outputs": {
            "legal_context_summary_raw": legal_context_summary,
            "extractions_raw": extractions_raw,
            "summary_raw": summary_raw,
            "opinions_raw": opinions_raw,
            "arbiter_raw": arbiter_json,
        },
    }
    return result
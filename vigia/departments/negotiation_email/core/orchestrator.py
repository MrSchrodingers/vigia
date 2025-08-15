import logging
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, Iterable, Set, List

from sqlalchemy.orm import Session

from vigia.departments.negotiation_email.agents.judicial_jury_agents import ARBITER_SCHEMA
from vigia.departments.negotiation_email.utils.jusbr_utils import build_timeline, build_evidence_index
from vigia.departments.negotiation_email.utils import clean_html_body
from vigia.departments.negotiation_email.utils.json_safety import safe_json_loads as _safe_json_loads
from vigia.services import database_service, pipedrive_service, llm_service
from vigia.services.pipedrive_service import email_client
from vigia.services.jusbr_service import jusbr_service

from db.session import SessionLocal
from db import models

# ==== Agents ================================================================
from ..agents import (
    context_miner_agent,
    context_synthesizer_agent,
    extraction_subject_agent,
    extraction_stage_agent,
    extraction_manager_agent,
    temperature_behavioral_agent,
    director_agent,
    formal_summarizer_agent,
    validator_agent,
    refiner_agent,
    extraction_legal_financial_agent,
    conservative_advocate_agent,
    strategic_advocate_agent,
    judicial_arbiter_agent,
    legal_context_synthesizer_agent,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# =============================================================================
# Constantes de estilo para notas HTML
# =============================================================================
HTML_SECTION_BORDER = 'style="padding-bottom:10px;margin-bottom:10px;border-bottom:1px solid #eee;"'
HTML_SECTION_SPACED = 'style="margin-bottom:15px;"'

# =============================================================================
# Utilitários internos
# =============================================================================
def _split_propostas(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Atribui corretamente autoria das propostas e preserva ambas as visões:
    - 'ultima_contraproposta_cliente'
    - 'nossa_proposta_atual'
    """
    out = dict(extracted or {})
    proposta = (out.get("proposta_atual") or {}) if isinstance(out.get("proposta_atual"), dict) else {}
    origem = (proposta.get("origem") or "").strip().lower()

    if origem == "cliente":
        out["ultima_contraproposta_cliente"] = proposta
        out.setdefault(
            "nossa_proposta_atual",
            {
                "valor": "R$ 1.597,00",
                "origem": "Nossa",
                "condicoes": [
                    "Pagamento em até 15 dias úteis",
                    "Assinatura da autora (pode ser digital)",
                    "Obrigações de fazer (se houver)",
                    "Cláusula para corréu (se houver)",
                ],
            },
        )
    elif origem == "nossa":
        out["nossa_proposta_atual"] = proposta
    else:
        # desconhecido: apenas preserve se já existir
        if "nossa_proposta_atual" not in out:
            out["nossa_proposta_atual"] = None
        if "ultima_contraproposta_cliente" not in out:
            out["ultima_contraproposta_cliente"] = None

    return out


def _resolve_urgencia(temp_metrics: Dict[str, Any]) -> str:
    """
    Harmoniza o 'tom/urgência' com métricas objetivas (engajamento/urgência).
    Regra: 'Urgente' somente se engajamento >= 2 ou urgência >= 2; senão 'Baixa'.
    """
    eng = (temp_metrics or {}).get("engajamento", 0) or 0
    urg = (temp_metrics or {}).get("urgencia", 0) or 0
    if (isinstance(eng, (int, float)) and eng >= 2) or (isinstance(urg, (int, float)) and urg >= 2):
        return "Urgente"
    return "Baixa"


async def _ensure_legal_ctx_json(legal_context_summary: str) -> Optional[Dict[str, Any]]:
    """
    Garante que o contexto legal esteja em JSON válido; caso contrário,
    solicita correção ao LLM com schema estrito.
    """
    try:
        return _safe_json_loads(legal_context_summary)
    except Exception:
        pass

    correction_prompt = f"""
    Você recebeu abaixo um conteúdo que DEVERIA ser JSON do contexto judicial, mas não está em JSON.
    Converta em JSON puro (sem markdown e sem comentários), seguindo ESTRITAMENTE o schema e os campos da especificação.
    Se algum campo não existir, preencha com valores neutros (strings vazias, listas vazias, null) — nunca invente.

    Conteúdo para converter:
    {legal_context_summary}
    """
    fixed = await llm_service.llm_call(
        "Você corrige saídas para JSON estrito.",
        correction_prompt,
        expects_json=True,
    )
    try:
        return _safe_json_loads(fixed)
    except Exception:
        return None


async def execute_tool_call(tool_call: Dict[str, Any], raw_crm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa a chamada de ferramenta solicitada pelo Diretor, com validações de CRM.
    Suporta:
      - AgendarFollowUp
      - AlertarSupervisorParaAtualizacao
    """
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {}) or {}

    person_id = raw_crm.get("person", {}).get("id")
    deal_info = raw_crm.get("deal", {}) or {}
    deal_id = deal_info.get("id")
    user_id = deal_info.get("user_id")

    if not person_id or not deal_id:
        msg = "Ação não pôde ser executada: ID da Pessoa ou do Negócio não encontrado no Pipedrive."
        logger.error(msg)
        return {"status": "falha", "detalhe": msg}

    if not user_id:
        logger.warning(f"Não foi encontrado 'user_id' no deal {deal_id}. A atividade será criada sem um proprietário específico.")

    if tool_name == "AgendarFollowUp":
        logger.info(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        result = await pipedrive_service.create_activity(
            client=email_client,
            person_id=person_id,
            deal_id=deal_id,
            user_id=user_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("note"),
            subject=tool_args.get("subject"),
        )
        return {"status": "sucesso", "resultado_pipedrive": result}

    if tool_name == "AlertarSupervisorParaAtualizacao":
        logger.warning(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        urgencia = (tool_args.get("urgencia") or "Média").upper()
        deal_title = deal_info.get("title", "Negócio")
        assunto_contextual = tool_args.get("assunto_alerta")
        subject = f"[{urgencia}] {assunto_contextual}: {deal_title}" if assunto_contextual else f"[{urgencia}] REVISAR/ATUALIZAR: {deal_title}"

        result = await pipedrive_service.create_activity(
            client=email_client,
            person_id=person_id,
            deal_id=deal_id,
            user_id=user_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("motivo"),
            subject=subject,
        )
        return {"status": "sucesso", "resultado_pipedrive": result}

    logger.error(f"Tentativa de chamar uma ferramenta desconhecida: {tool_name}")
    return {"status": "erro", "detalhe": "Ferramenta não encontrada."}


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


def _format_process_overview_section(legal_ctx: Optional[Dict[str, Any]]) -> str:
    """Bloco com dados processuais básicos."""
    if not isinstance(legal_ctx, dict):
        return ""
    dg = legal_ctx.get("dados_gerais") or {}
    status = legal_ctx.get("status_processual") or dg.get("status_processual") or ""
    numero = (
        dg.get("numero_processo")
        or legal_ctx.get("numeroProcesso")
        or legal_ctx.get("numero_processo")
        or ""
    )
    classe = dg.get("classe") or legal_ctx.get("classe") or ""
    assunto = dg.get("assunto") or legal_ctx.get("assunto") or ""
    valor = dg.get("valor_causa") or legal_ctx.get("valor_causa")
    valor_fmt = (
        f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if isinstance(valor, (int, float))
        else (str(valor) if valor is not None else "")
    )
    orgao = dg.get("orgao_julgador") or legal_ctx.get("orgao") or ""
    tribunal = dg.get("tribunal") or legal_ctx.get("tribunal") or ""

    items = []
    if numero:
        items.append(f"<li><b>Nº do processo:</b> {numero}</li>")
    if classe:
        items.append(f"<li><b>Classe:</b> {classe}</li>")
    if assunto:
        items.append(f"<li><b>Assunto:</b> {assunto}</li>")
    if valor_fmt:
        items.append(f"<li><b>Valor da causa:</b> {valor_fmt}</li>")
    if orgao:
        items.append(f"<li><b>Órgão julgador:</b> {orgao}</li>")
    if tribunal:
        items.append(f"<li><b>Tribunal:</b> {tribunal}</li>")
    if status:
        items.append(f"<li><b>Status processual:</b> {status}</li>")

    if not items:
        return ""

    return f'<div {HTML_SECTION_SPACED}><h4>📄 Quadro Processual</h4><ul>{"".join(items)}</ul></div>'


def _format_timeline_section(legal_ctx: Optional[Dict[str, Any]], limit: Optional[int] = 100) -> str:
    """Bloco com os atos do processo (ordenado)."""
    if not isinstance(legal_ctx, dict):
        return ""
    tl = legal_ctx.get("timeline") or legal_ctx.get("timeline_pre") or []
    if not isinstance(tl, list) or not tl:
        return ""

    tl_sorted = sorted(tl, key=lambda x: (x or {}).get("data") or "")
    if isinstance(limit, int) and limit > 0:
        tail = tl_sorted[-limit:]
        label = f"últimos {limit} atos"
    else:
        tail = tl_sorted
        label = "atos"

    rows = []
    for item in tail:
        data = (item.get("data") or "").strip()
        desc = (item.get("descricao") or "").strip()
        ref = (item.get("doc_ref") or "")
        ref_html = f' <i>({ref})</i>' if ref else ""
        rows.append(f"<li><b>{data}</b> — {desc} {ref_html}</li>")

    if not rows:
        return ""
    return f'<div {HTML_SECTION_SPACED}><h4>📜 Andamento Processual ({label})</h4><ul>{"".join(rows)}</ul></div>'


def _format_theses_section(recommendation_data: Optional[Dict[str, Any]], theses: Optional[Dict[str, Any]]) -> str:
    """
    Mostra resumos das teses. Prioriza 'teses_consideradas' (Júri).
    Fallback: usa objetos dos agentes (conservative/strategic), se necessário.
    """
    cons = est = ""
    if isinstance(recommendation_data, dict):
        tc = recommendation_data.get("teses_consideradas") or {}
        cons = (tc.get("conservadora") or "").strip()
        est = (tc.get("estrategica") or "").strip()

    if not (cons and est) and isinstance(theses, dict):
        c = theses.get("conservative") or {}
        s = theses.get("strategic") or {}
        cons = cons or (c.get("tese") or "")
        est = est or (s.get("tese") or "")

    if not (cons or est):
        return ""

    html = [f'<div {HTML_SECTION_SPACED}><h4>🧭 Resumo das Teses</h4><ul>']
    if cons:
        html.append(f"<li><b>Conservadora:</b> {cons}</li>")
    if est:
        html.append(f"<li><b>Estratégica:</b> {est}</li>")
    html.append("</ul></div>")
    return "".join(html)


def _format_documents_section(legal_ctx: Optional[Dict[str, Any]]) -> str:
    """Seção com documentos-chave (inicial/contestação/réplica) e pontos principais, se existirem."""
    if not isinstance(legal_ctx, dict):
        return ""
    docs = legal_ctx.get("documentos_chave") or {}
    if not isinstance(docs, dict) or not docs:
        return ""

    sections = [f'<div {HTML_SECTION_SPACED}><h4>📎 Documentos-Chave</h4>']
    for key in ("inicial", "contestacao", "replica"):
        block = docs.get(key)
        if not isinstance(block, dict):
            continue
        title = {"inicial": "Petição Inicial", "contestacao": "Contestação", "replica": "Réplica"}.get(key, key.title())
        resumo = block.get("resumo")
        pts = block.get("pontos_principais") or []
        sections.append(f"<h5 style='margin:10px 0 6px 0;'>{title}</h5>")
        if resumo:
            sections.append(f"<p>{resumo}</p>")
        if isinstance(pts, list) and pts:
            sections.append("<ul>")
            for p in pts:
                sections.append(f"<li>{p}</li>")
            sections.append("</ul>")
    sections.append("</div>")
    return "".join(sections)


def _format_risks_and_agreement_section(legal_ctx: Optional[Dict[str, Any]]) -> str:
    """Seções de riscos e hipótese de acordo, se existirem."""
    if not isinstance(legal_ctx, dict):
        return ""
    chunks = []

    # Tema 1061
    if legal_ctx.get("aplica_tema_1061_stj") or legal_ctx.get("detalhe_tema_1061_stj"):
        chunks.append(f'<div {HTML_SECTION_SPACED}><h4>📌 Tema 1061/STJ</h4>')
        detalhe = legal_ctx.get("detalhe_tema_1061_stj") or ""
        if detalhe:
            chunks.append(f"<p>{detalhe}</p>")
        else:
            chunks.append("<p>Aplicável ao caso conforme intimação.</p>")
        chunks.append("</div>")

    # Riscos
    riscos = legal_ctx.get("riscos") or {}
    fatores = riscos.get("fatores") or []
    if riscos or fatores:
        chunks.append(f'<div {HTML_SECTION_SPACED}><h4>⚠️ Riscos e Pontos de Atenção</h4>')
        if riscos.get("nivel"):
            chunks.append(f"<p><b>Nível:</b> {riscos['nivel']}</p>")
        if isinstance(fatores, list) and fatores:
            chunks.append("<ul>")
            chunks.extend(f"<li>{f}</li>" for f in fatores)
            chunks.append("</ul>")
        chunks.append("</div>")

    # Acordo
    acordo = legal_ctx.get("acordo") or {}
    if acordo:
        chunks.append(f'<div {HTML_SECTION_SPACED}><h4>🤝 Hipótese de Acordo e Próximos Passos</h4>')
        if acordo.get("hipotese_acordo"):
            chunks.append(f"<p><b>Hipótese:</b> {acordo['hipotese_acordo']}</p>")
        if acordo.get("faixa_de_acordo_sugerida"):
            chunks.append(f"<p><b>Faixa sugerida:</b> {acordo['faixa_de_acordo_sugerida']}</p>")
        if acordo.get("proximos_passos_provaveis"):
            chunks.append(f"<p><b>Próximos passos:</b> {acordo['proximos_passos_provaveis']}</p>")
        chunks.append("</div>")

    return "".join(chunks)


def _gather_strings(obj: Any) -> Iterable[str]:
    """Percorre estruturas e produz todos os strings encontrados."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _gather_strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _gather_strings(v)


def _find_process_numbers_in_extract(extracted_data: Dict[str, Any], legal_ctx: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Acha números de processo no padrão CNJ dentro do extract_data/strings relacionados,
    e também tenta aproveitar o número do contexto legal.
    """
    pattern = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
    found: Set[str] = set()

    for s in _gather_strings(extracted_data):
        for m in pattern.findall(s):
            found.add(m)

    # Adiciona do contexto legal (se houver)
    if isinstance(legal_ctx, dict):
        dg = legal_ctx.get("dados_gerais") or {}
        for key in ("numero_processo",):
            val = dg.get(key) or legal_ctx.get(key) or legal_ctx.get("numeroProcesso")
            if isinstance(val, str):
                for m in pattern.findall(val):
                    found.add(m)

        # Também varre strings do legal_ctx
        for s in _gather_strings(legal_ctx):
            for m in pattern.findall(s):
                found.add(m)

    return sorted(found)


def _format_note_resumo(summary_data: Dict[str, Any], extract_data: Dict[str, Any], temp_data: Dict[str, Any]) -> str:
    """Nota 1: Resumo da Análise da Negociação — com status, tom e propostas."""
    html = [f'<div {HTML_SECTION_BORDER}><h2>📝 Resumo da Análise da Negociação</h2></div>']

    # Resumo executivo do summarizer
    se = summary_data.get("sumario_executivo")
    if se:
        html.append(f'<div {HTML_SECTION_BORDER}><h4>Resumo Executivo</h4><p>{se}</p></div>')

    # Status & Tom
    estagio = extract_data.get("estagio_negociacao") or ""
    tom = extract_data.get("tom_da_conversa") or ""
    urg = (temp_data or {}).get("urgencia_resolvida") or ""
    html.append(
        f'<div {HTML_SECTION_BORDER}><h4>Status &amp; Tom</h4>'
        f'<ul>'
        f'<li><b>Estágio:</b> {estagio or "N/D"}</li>'
        f'<li><b>Tom:</b> {tom or "N/D"}</li>'
        f'<li><b>Urgência:</b> {urg or "Baixa"}</li>'
        f'</ul></div>'
    )

    # Proposta do cliente (quando houver)
    prop_cliente = extract_data.get("ultima_contraproposta_cliente") or extract_data.get("proposta_atual") or {}
    if isinstance(prop_cliente, dict) and (prop_cliente.get("valor") or prop_cliente.get("condicoes")):
        html.append('<div style="margin-bottom:15px;"><h4>Proposta Atual do Cliente</h4><ul>')
        if prop_cliente.get("valor"):
            html.append(f'<li><b>Valor:</b> {prop_cliente["valor"]}</li>')
        if prop_cliente.get("prazo"):
            html.append(f'<li><b>Prazo:</b> {prop_cliente["prazo"]}</li>')
        conds = prop_cliente.get("condicoes") or []
        if isinstance(conds, list) and conds:
            html.append("<li><b>Condições:</b><ul>")
            html.extend(f"<li>{c}</li>" for c in conds)
            html.append("</ul></li>")
        html.append("</ul></div>")

    # Nossos argumentos e proposta
    nossos_args = extract_data.get("argumentos_nossos") or []
    if nossos_args:
        html.append('<div style="margin-bottom:15px;"><h4>Nossos Argumentos (histórico)</h4><ul>')
        html.extend(f"<li>{a}</li>" for a in nossos_args)
        html.append("</ul></div>")

    nossa_prop = extract_data.get("nossa_proposta_atual")
    if isinstance(nossa_prop, dict) and (nossa_prop.get("valor") or nossa_prop.get("condicoes")):
        html.append('<div style="margin-bottom:15px;"><h4>Nossa Proposta Atual</h4><ul>')
        if nossa_prop.get("valor"):
            html.append(f'<li><b>Valor:</b> {nossa_prop["valor"]}</li>')
        conds = nossa_prop.get("condicoes") or []
        if isinstance(conds, list) and conds:
            html.append("<li><b>Condições:</b><ul>")
            html.extend(f"<li>{c}</li>" for c in conds)
            html.append("</ul></li>")
        html.append("</ul></div>")

    # Histórico resumido (do summarizer)
    historico = summary_data.get("historico_negociacao") or {}
    if historico:
        html.append(f'<div {HTML_SECTION_BORDER}><h4>Histórico da Negociação</h4>')
        if historico.get("fluxo"):
            html.append(f'<p>{historico["fluxo"]}</p>')
        if historico.get("argumentos_cliente"):
            args_cli = historico["argumentos_cliente"]
            html.append('<strong>Argumentos do Cliente:</strong>')
            if isinstance(args_cli, list):
                html.append("<ul>")
                html.extend(f"<li>{x}</li>" for x in args_cli)
                html.append("</ul>")
            else:
                html.append(f"<p><i>{args_cli}</i></p>")
        if historico.get("argumentos_internos"):
            args_int = historico["argumentos_internos"]
            html.append('<br><strong>Nossos Argumentos:</strong>')
            if isinstance(args_int, list):
                html.append("<ul>")
                html.extend(f"<li>{x}</li>" for x in args_int)
                html.append("</ul>")
            else:
                html.append(f"<p><i>{args_int}</i></p>")
        html.append("</div>")

    return "".join(html)


def _format_note_recomendacao(advisor_json: Dict[str, Any], processos: List[str]) -> str:
    """Nota 2: Recomendação do Júri de IAs — com processos citados no cabeçalho."""
    header_extra = ""
    if processos:
        header_extra = f"<p style='margin-top:6px;color:#555'><b>Processos:</b> {', '.join(processos)}</p>"

    html = [f'<div {HTML_SECTION_BORDER}><h2>⚖️ Recomendação do Júri de IAs</h2>{header_extra}</div>']

    if not advisor_json or "erro" in advisor_json:
        html.append("<p><i>Recomendação estratégica indisponível no momento.</i></p>")
        return "".join(html)

    acao = advisor_json.get("acao_recomendada", {}) or {}
    estrategia = acao.get("estrategia") or "N/A"
    proxima = acao.get("proxima_acao") or "N/A"
    racional = (advisor_json.get("racional_juridico") or "N/A").replace("\\n", "<br>")
    conf = advisor_json.get("confidence_score")
    try:
        conf_pct = max(0.0, min(1.0, float(conf))) * 100.0 if conf is not None else None
    except Exception:
        conf_pct = None

    html.append(
        f'<div {HTML_SECTION_SPACED}><h4>Estratégia Recomendada</h4>'
        f'<p><strong>Ação:</strong> {proxima}</p>'
        f'<p><strong>Estratégia:</strong> {estrategia}</p></div>'
    )
    html.append(f'<div {HTML_SECTION_SPACED}><h4>Racional Jurídico</h4><p>{racional}</p></div>')
    if conf_pct is not None:
        html.append(f'<div {HTML_SECTION_SPACED}><h4>Nível de Confiança</h4><p><strong>{conf_pct:.1f}%</strong></p></div>')

    # Teses consideradas (quando houver)
    html.append(_format_theses_section(advisor_json, None))

    return "".join(html)


def _format_note_andamento_teses(
    legal_ctx: Optional[Dict[str, Any]],
    advisor_json: Optional[Dict[str, Any]],
    extracted_data: Optional[Dict[str, Any]],
    *,
    timeline_limit: Optional[int] = None,  # None = todos os atos
) -> str:
    """Nota 3: Andamento Processual + Resumo das Teses (com dados ricos)."""
    html = [f'<div {HTML_SECTION_BORDER}><h2>📜 Andamento Processual + 🧭 Resumo das Teses (Detalhado)</h2></div>']

    # Quadro processual
    html.append(_format_process_overview_section(legal_ctx))

    # Partes (se disponíveis)
    if isinstance(legal_ctx, dict):
        partes = legal_ctx.get("partes") or {}
        autor = partes.get("autor") or {}
        reu = partes.get("reu") or {}
        autor_doc = autor.get("documento") or ""
        reu_doc = reu.get("documento") or ""
        if autor or reu:
            html.append(f'<div {HTML_SECTION_SPACED}><h4>👥 Partes e Advogados</h4>')
            if autor:
                html.append(f"<p><b>Autora:</b> {autor.get('nome','')} {'— CPF ' + autor_doc if autor_doc else ''}</p>")
                advs = autor.get("advogados") or []
                if isinstance(advs, list) and advs:
                    html.append("<ul>")
                    for a in advs:
                        if isinstance(a, dict):
                            html.append(f"<li>Adv. {a.get('nome','')} — OAB {a.get('oab','')}</li>")
                    html.append("</ul>")
            if reu:
                html.append(f"<p><b>Réu:</b> {reu.get('nome','')} {'— CNPJ ' + reu_doc if reu_doc else ''}</p>")
                advs = reu.get("advogados") or []
                if isinstance(advs, list) and advs:
                    html.append("<ul>")
                    for a in advs:
                        if isinstance(a, dict):
                            html.append(f"<li>Adv. {a.get('nome','')} — OAB {a.get('oab','')}</li>")
                    html.append("</ul>")
            html.append("</div>")

    # Documentos-chave + Teses detalhadas
    html.append(_format_documents_section(legal_ctx))

    # Tema 1061, Riscos e Acordo
    html.append(_format_risks_and_agreement_section(legal_ctx))

    # Timeline (todos os atos por padrão nesta nota rica)
    html.append(_format_timeline_section(legal_ctx, limit=timeline_limit))

    # Resumo das Teses (alto nível do Júri)
    html.append(_format_theses_section(advisor_json or {}, None))

    return "".join(x for x in html if x)


def _seconds_between(start_iso: str, end_iso: str) -> int:
    try:
        return int((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds())
    except Exception:
        return -1


def _score_aderencia_prompt(extracted_data: Dict[str, Any]) -> float:
    if not extracted_data:
        return 0.0
    total = len(extracted_data)
    filled = sum(1 for v in extracted_data.values() if v not in (None, "", [], {}))
    return round(filled / total, 2) if total else 0.0


def _build_kpis(thread_meta: Dict[str, Any], extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tempo_resposta_seg": _seconds_between(thread_meta["first_email_date"], thread_meta["last_email_date"]),
        "delta_valor_oferta_%": -1,
        "prob_sucesso_modelo_ml": -1,
        "score_aderencia_prompt": _score_aderencia_prompt(extracted_data),
    }


async def _create_and_log_note(deal_id: int, content: str, note_type: str, pipedrive_actions_list: list) -> None:
    """
    Cria nota no Pipedrive e registra o resultado na lista de ações executadas.
    """
    logger.info(f"Criando nota de '{note_type}' para o Deal ID {deal_id} no Pipedrive.")
    note_result = await pipedrive_service.create_note_for_deal(client=email_client, deal_id=deal_id, content=content)

    action_log = {
        "action": f"create_note_{note_type.lower().replace(' ', '_')}",
        "result": note_result,
        "status": "success" if note_result and note_result.get("id") else "failure",
    }
    if action_log["status"] == "success":
        logger.info(f"Nota de '{note_type}' criada com sucesso (ID: {note_result['id']}).")
    else:
        logger.error(f"Falha ao criar nota de '{note_type}' para o Deal ID {deal_id}.")
    pipedrive_actions_list.append(action_log)


def _save_judicial_analysis_to_db(db: Session, thread_id: int, analysis_json: Dict[str, Any], theses: Dict[str, Any]):
    """Persiste a decisão do Júri (se válida) no banco."""
    if not analysis_json or "erro" in analysis_json:
        logger.error("Análise judicial contém erro ou está vazia. Abortando salvamento.")
        return
    try:
        new_analysis = models.JudicialAnalysis(
            thread_id=thread_id,
            recommended_action=analysis_json.get("acao_recomendada", {}),
            legal_rationale=analysis_json.get("racional_juridico", "N/A"),
            confidence_score=analysis_json.get("confidence_score"),
            conservative_thesis=theses.get("conservative"),
            strategic_thesis=theses.get("strategic"),
        )
        db.add(new_analysis)
        db.commit()
        logger.info(f"Análise do Júri para a thread ID {thread_id} salva com sucesso no banco de dados.")
    except Exception:
        logger.exception(f"Falha ao salvar a análise do Júri para a thread ID {thread_id} no banco de dados.")
        db.rollback()


# =============================================================================
# DB helpers
# =============================================================================
def get_thread_data_from_db(db: Session, conversation_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    thread = db.query(models.EmailThread).filter(models.EmailThread.conversation_id == conversation_id).first()
    if not thread:
        logger.error("Thread %s não encontrada", conversation_id)
        return None, None

    messages = sorted(thread.messages, key=lambda m: m.sent_datetime)

    history_parts = []
    for m in messages:
        cleaned_body = clean_html_body(m.body)
        history_parts.append(
            f"De: {m.sender}\nData: {m.sent_datetime.strftime('%d/%m/%Y %H:%M')}\n\n{cleaned_body}"
        )

    history = "\n\n---\n\n".join(history_parts)

    meta = {
        "participants": thread.participants,
        "subject": thread.subject,
        "first_email_date": thread.first_email_date.isoformat(),
        "last_email_date": thread.last_email_date.isoformat(),
        "total_messages": len(messages),
        "has_attachments": any(m.has_attachments for m in messages),
        "importance": [m.importance for m in messages if m.importance],
    }
    return meta, history


# =============================================================================
# Sub-departamentos
# =============================================================================
async def run_adversarial_extraction(email_body: str) -> str:
    """
    Extração em 3 etapas: geração → validação → refinamento.
    Garante precisão e consistência do JSON extraído.
    """
    logger.info("Iniciando extração adversarial (Etapa 1: Geração)...")
    initial_extraction = await extraction_legal_financial_agent.execute(email_body)

    logger.info("Iniciando Etapa 2: Validação...")
    validation_report_str = await validator_agent.execute(email_body=email_body, json_extraction=initial_extraction)

    try:
        validation_report = _safe_json_loads(validation_report_str)
    except json.JSONDecodeError:
        logger.error("Falha ao decodificar o relatório de validação. Abortando refinamento.")
        return initial_extraction

    if validation_report.get("is_valid"):
        logger.info("Extração inicial validada com sucesso.")
        return initial_extraction

    logger.info("Iniciando Etapa 3: Refinamento...")
    final_extraction = await refiner_agent.execute(
        email_body=email_body,
        initial_extraction=initial_extraction,
        validation_report=validation_report_str,
    )
    logger.info("Refinamento concluído.")
    return final_extraction


async def run_temperature_department(history_txt: str, meta: Dict[str, Any]) -> str:
    logger.info("-- Analysing temperature & behaviour")
    return await temperature_behavioral_agent.execute(meta)


# =============================================================================
# Pipeline principal
# =============================================================================
async def run_department_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    conv_id = payload.get("conversation_id")
    save_result = payload.get("save_result", False)
    logger.info("PIPELINE EMAIL • Iniciando para %s", conv_id)

    # ------------------ Carrega thread e meta ------------------
    db = SessionLocal()
    try:
        thread = db.query(models.EmailThread).filter(models.EmailThread.conversation_id == conv_id).first()
        if not thread:
            logger.error("Thread %s não encontrada", conv_id)
            return {}
        thread_id = thread.id
        thread_meta, full_history = get_thread_data_from_db(db, conv_id)
        if not thread_meta:
            return {}
    finally:
        db.close()

    # ------------------ Contexto CRM ------------------
    raw_crm = await context_miner_agent.execute(thread_meta["subject"])

    # ------------------ Enriquecimento PDPJ ------------------
    logger.info("-- Iniciando enriquecimento com dados da Plataforma Digital do Poder Judiciário (PDPJ)...")
    processo_field_hash = "eed799d442d4ae42f98a505f89bc7a264dbab4a8"
    numero_processo_crm = raw_crm.get("deal", {}).get(processo_field_hash)

    if not numero_processo_crm:
        try:
            subject_extraction = _safe_json_loads(await extraction_subject_agent.execute(thread_meta["subject"]))
            numero_processo_crm = subject_extraction.get("numero_processo")
        except Exception:
            numero_processo_crm = None

    legal_context_summary = ""
    legal_ctx_json: Optional[Dict[str, Any]] = None

    if numero_processo_crm:
        try:
            processo_details = await jusbr_service.get_processo_details_with_docs(numero_processo_crm)
        except Exception as exc:
            logger.error("Erro ao consultar Jus.br: %s", exc)
            processo_details = None

        if processo_details:
            root = processo_details[0] if isinstance(processo_details, list) else processo_details
            tr = root.get("tramitacaoAtual") or {}
            root["timeline_pre"] = build_timeline(tr)
            root["_evidence_index"] = build_evidence_index(root)
            legal_context_summary = await legal_context_synthesizer_agent.execute(root)
            legal_ctx_json = await _ensure_legal_ctx_json(legal_context_summary)
        else:
            logger.warning("Jus.br não retornou dados para o processo informado.")
            legal_context_summary = "**Análise do Processo Judicial (PDPJ):**\n- Dados indisponíveis no momento."
    else:
        logger.warning("Número de processo não identificado para consulta no Jus.br.")
        legal_context_summary = "**Análise do Processo Judicial (PDPJ):**\n- Número do processo não identificado."

    # ------------------ Síntese de contexto ------------------
    enriched_ctx_crm = await context_synthesizer_agent.execute(raw_crm)
    history_plus_ctx = f"{enriched_ctx_crm}\n\n---\n\n{legal_context_summary}\n\n---\n\nHISTÓRICO DE E-MAILS:\n{full_history}"

    # ------------------ Extrações paralelas ------------------
    logger.info("Iniciando extração de dados em paralelo (com processo adversarial)...")
    subject_extraction_str, legal_financial_extraction_str, stage_extraction_str, temp_str = await asyncio.gather(
        extraction_subject_agent.execute(thread_meta["subject"]),
        run_adversarial_extraction(history_plus_ctx),
        extraction_stage_agent.execute(history_plus_ctx),
        run_temperature_department(full_history, thread_meta),
    )

    logger.info("Consolidando relatórios de extração...")
    extract_str = await extraction_manager_agent.execute(
        subject_extraction_str, legal_financial_extraction_str, stage_extraction_str
    )
    extract_data = _safe_json_loads(extract_str)
    extract_data = _split_propostas(extract_data)  # <-- ajuste de autoria das propostas
    temp_data = _safe_json_loads(temp_str)
    urgencia_final = _resolve_urgencia(temp_data)

    # ------------------ KPIs ------------------
    kpis = _build_kpis(thread_meta, extract_data)

    # ------------------ Diretoria ------------------
    logger.info("-- Solicitando decisão do Diretor Estratégico...")
    director_raw = await director_agent.execute(
        extraction_report=json.dumps(extract_data, ensure_ascii=False),
        temperature_report=json.dumps(temp_data, ensure_ascii=False),
        crm_context=json.dumps(raw_crm, ensure_ascii=False),
        conversation_id=conv_id,
    )

    director_decision: Dict[str, Any] = {}
    pipedrive_actions_results: list = []

    try:
        decision_json = _safe_json_loads(director_raw)
        actions_to_execute = decision_json.get("actions")
        tool_name_direct = decision_json.get("name")

        if actions_to_execute and isinstance(actions_to_execute, list):
            logger.info("Diretor solicitou %d ações (lista).", len(actions_to_execute))
            for action_call in actions_to_execute:
                single = {"name": action_call.get("tool_name"), "args": action_call.get("tool_args")}
                exec_result = await execute_tool_call(single, raw_crm)
                pipedrive_actions_results.append({"acao_executada": single, "resultado_execucao": exec_result})
            director_decision = {"acoes_executadas": pipedrive_actions_results}

        elif tool_name_direct and decision_json.get("type") == "function_call":
            logger.info("Diretor solicitou 1 ação (function_call).")
            single = {"name": tool_name_direct, "args": decision_json.get("args", {})}
            exec_result = await execute_tool_call(single, raw_crm)
            pipedrive_actions_results.append({"acao_executada": single, "resultado_execucao": exec_result})
            director_decision = {"acoes_executadas": pipedrive_actions_results}

        elif "resumo_estrategico" in decision_json:
            director_decision = {"resumo_estrategico": decision_json.get("resumo_estrategico", "N/A")}

        else:
            logger.error("Formato de decisão do Diretor inesperado.")
            director_decision = {"erro": "Formato de decisão desconhecido", "raw_output": str(director_raw)}
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Decisão do diretor mal formatada: %s", e)
        director_decision = {"erro": "Decisão do diretor mal formatada", "raw_output": str(director_raw)}

    # ------------------ Júri de IAs ------------------
    logger.info("-- Convocando o Júri de IAs para deliberação...")
    advisor_payload_context = {
        "extract": extract_data,
        "temperature": {**temp_data, "urgencia_resolvida": urgencia_final},
        "kpis": kpis,
        "crm_context": enriched_ctx_crm,
    }
    context_str = json.dumps(advisor_payload_context, ensure_ascii=False, indent=2)

    tese_conservadora_str, tese_estrategica_str = await asyncio.gather(
        conservative_advocate_agent.execute(context_str),
        strategic_advocate_agent.execute(context_str),
    )

    tese_conservadora_json = _safe_json_loads(tese_conservadora_str)
    tese_estrategica_json = _safe_json_loads(tese_estrategica_str)

    max_attempts = 3
    advisor_json: Dict[str, Any] = {}
    advisor_raw = ""

    for attempt in range(1, max_attempts + 1):
        logger.info("Tentativa %d/%d para obter a decisão do Júri.", attempt, max_attempts)
        if attempt == 1:
            advisor_raw = await judicial_arbiter_agent.execute(
                context=context_str,
                tese_conservadora=tese_conservadora_str,
                tese_estrategica=tese_estrategica_str,
            )
        else:
            correction_prompt = f"""
            O texto abaixo deveria ser JSON válido, mas falhou ao decodificar.
            Corrija cuidadosamente erros de sintaxe (vírgulas, aspas, escapes) e retorne APENAS JSON válido.

            Texto:
            {advisor_raw}
            """
            advisor_raw = await llm_service.llm_call(
                "Você é um especialista em correção de JSON.",
                correction_prompt,
                expects_json=True,
                json_schema=ARBITER_SCHEMA,
            )

        try:
            advisor_json = _safe_json_loads(advisor_raw)
            logger.info("Sucesso na decodificação do JSON do Júri na tentativa %d.", attempt)
            break
        except json.JSONDecodeError as e:
            logger.warning("Falha na decodificação do Júri (tentativa %d/%d). Erro: %s", attempt, max_attempts, e)
            if attempt == max_attempts:
                logger.error("Número máximo de tentativas atingido. Abortando decisão do Júri.")
                advisor_json = {"erro": "advisor output inválido após 3 tentativas", "raw": advisor_raw}

    # Persistência da análise do Júri (opcional)
    if "erro" not in advisor_json and save_result and thread_id:
        db = SessionLocal()
        try:
            _save_judicial_analysis_to_db(
                db=db,
                thread_id=thread_id,
                analysis_json=advisor_json,
                theses={"conservative": tese_conservadora_json, "strategic": tese_estrategica_json},
            )
        finally:
            db.close()

    # ------------------ Sumarizador ------------------
    logger.info("-- Gerando sumário formal")
    summarizer_payload = {
        "dados_extraidos": extract_data,
        "analise_temperatura": {**temp_data, "urgencia_resolvida": urgencia_final},
        "contexto_crm": raw_crm,
        "contexto_judicial": legal_ctx_json,
    }
    summary_raw = await formal_summarizer_agent.execute(json.dumps(summarizer_payload, ensure_ascii=False))
    try:
        summary_json = _safe_json_loads(summary_raw)
    except json.JSONDecodeError as e:
        logger.error("Erro ao decodificar o JSON do sumário: %s", e)
        summary_json = {"erro": "summarizer output inválido", "raw": summary_raw}

    # ------------------ Notas no Pipedrive (3 notas separadas) ------------------
    deal_id = raw_crm.get("deal", {}).get("id")
    pipedrive_actions_results = director_decision.get("acoes_executadas", []) if isinstance(director_decision, dict) else []

    if deal_id:
        # Nota 1: Resumo da Análise da Negociação
        note1_content = _format_note_resumo(summary_json, extract_data, {**temp_data, "urgencia_resolvida": urgencia_final})
        await _create_and_log_note(
            deal_id=deal_id,
            content=note1_content,
            note_type="Resumo da Análise da Negociação",
            pipedrive_actions_list=pipedrive_actions_results,
        )

        # Nota 2: Recomendação do Júri de IAs (com números de processos no cabeçalho)
        processos_detectados = _find_process_numbers_in_extract(extract_data, legal_ctx_json)
        note2_content = _format_note_recomendacao(advisor_json if "erro" not in advisor_json else {}, processos_detectados)
        await _create_and_log_note(
            deal_id=deal_id,
            content=note2_content,
            note_type="Recomendação do Júri de IAs",
            pipedrive_actions_list=pipedrive_actions_results,
        )

        # Nota 3: Andamento Processual + Resumo das Teses (dados ricos)
        # timeline_limit=None => todos os atos disponíveis
        note3_content = _format_note_andamento_teses(
            legal_ctx=legal_ctx_json,
            advisor_json=advisor_json if "erro" not in advisor_json else {},
            extracted_data=extract_data,
            timeline_limit=None,
        )
        await _create_and_log_note(
            deal_id=deal_id,
            content=note3_content,
            note_type="Andamento Processual e Resumo das Teses",
            pipedrive_actions_list=pipedrive_actions_results,
        )
    else:
        logger.warning("Notas não criadas no Pipedrive (Deal ID ausente).")

    # ------------------ Relatório final ------------------
    report = {
        "analysis_metadata": {"conversation_id": conv_id},
        "extracted_data": extract_data,
        "temperature_analysis": {**temp_data, "urgencia_resolvida": urgencia_final},
        "kpis": kpis,
        "director_decision": director_decision,
        "advisor_recommendation": advisor_json,
        "context": {"crm_context": enriched_ctx_crm},
        "formal_summary": summary_json,
        "pipedrive_actions": pipedrive_actions_results,
    }

    if save_result:
        logger.info("Salvando resultado da análise (%s)", conv_id)
        db = SessionLocal()
        try:
            database_service.save_email_analysis_results(db=db, analysis_data=report)
        finally:
            db.close()

    logger.info("PIPELINE EMAIL • Finalizado para %s", conv_id)
    return report

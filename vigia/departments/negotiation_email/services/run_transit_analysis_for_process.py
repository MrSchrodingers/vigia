from datetime import datetime, timezone
import json
import re
from sqlalchemy.orm import Session
from db import models
from vigia.departments.negotiation_email.agents import transit_agent

def _parse_date_from_str(text: str) -> datetime | None:
    """Usa regex para encontrar e converter a primeira data DD/MM/AAAA em um objeto datetime."""
    if not text:
        return None
    match = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    if match:
        try:
            # Converte para objeto datetime, mantendo o fuso horário UTC
            return datetime.strptime(match.group(0), '%d/%m/%Y').replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None

async def run_transit_analysis_for_process(process_id: str, db: Session) -> dict:
    """
    Orquestra a análise de trânsito em julgado, salvando/atualizando o resultado no banco.
    """
    proc = db.query(models.LegalProcess).filter(models.LegalProcess.id == process_id).first()
    if not proc:
        return {"erro": "Processo não encontrado"}

    # 1. Coletar dados relevantes: últimas 50 movimentações
    movements_from_db = sorted(proc.movements, key=lambda m: m.date, reverse=True)[:50]
    movimentos_payload = [
        {"data": m.date.isoformat(), "descricao": m.description} for m in movements_from_db
    ]

    # 2. Coletar textos de documentos chave (sentenças, acórdãos, decisões)
    documentos_relevantes = db.query(models.ProcessDocument).filter(
        models.ProcessDocument.process_id == process_id,
        models.ProcessDocument.document_type.ilike('%sentença%') | \
        models.ProcessDocument.document_type.ilike('%acórdão%') | \
        models.ProcessDocument.document_type.ilike('%decisão%')
    ).all()
    
    trechos_decisoes = ""
    for doc in documentos_relevantes:
        if doc.text_content:
            trechos_decisoes += f"\n---\nDOCUMENTO: {doc.name}\nDATA: {doc.juntada_date}\nCONTEÚDO:\n{doc.text_content[:2000]}...\n---\n"

    # 3. Chamar o agente
    analysis_result_str = await transit_agent.execute(
        movimentos=movimentos_payload,
        trechos_decisoes=trechos_decisoes
    )

    try:
        analysis_result = json.loads(analysis_result_str)
    except json.JSONDecodeError:
        return {"erro": "Falha ao decodificar a resposta do agente."}

    # 4. LÓGICA IDEMPOTENTE DE SALVAR/ATUALIZAR
    status = analysis_result.get("status_transito_julgado")
    if status:
        # Extrai os dados do resultado da IA
        justification = analysis_result.get("justificativa")
        key_movements = analysis_result.get("movimentacoes_chave")

        # Tenta extrair a data da forma mais robusta possível
        date_text = " ".join(key_movements) if key_movements else ""
        transit_date = _parse_date_from_str(date_text)
        if not transit_date and justification:
            transit_date = _parse_date_from_str(justification)

        # Busca por uma análise existente para este processo
        existing_analysis = db.query(models.TransitAnalysis).filter_by(process_id=proc.id).first()

        if existing_analysis:
            # Se existe, ATUALIZA os campos
            existing_analysis.status = status
            existing_analysis.justification = justification
            existing_analysis.key_movements = key_movements
            existing_analysis.transit_date = transit_date
            existing_analysis.analysis_raw_data = analysis_result
        else:
            # Se não existe, CRIA um novo registro
            new_analysis = models.TransitAnalysis(
                process_id=proc.id,
                status=status,
                justification=justification,
                key_movements=key_movements,
                transit_date=transit_date,
                analysis_raw_data=analysis_result
            )
            db.add(new_analysis)
        
        if hasattr(proc, 'analysis_content'):
             proc.transit_analysis_content = analysis_result 

        proc.last_update = datetime.now(timezone.utc)
        db.commit()

    return analysis_result
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db import models

logger = logging.getLogger(__name__)

CPJ_DATABASE_URI = os.getenv("CPJ_DATABASE_URI")
cpj_engine = create_engine(
    CPJ_DATABASE_URI,
    pool_pre_ping=True,
    pool_recycle=3600,
)

_CNJ_NON_DIGIT_RE = re.compile(r"\D+")


def _only_digits(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return _CNJ_NON_DIGIT_RE.sub("", s)


def cnj_digits(s: Optional[str]) -> Optional[str]:
    d = _only_digits(s)
    return d if d and len(d) == 20 else None


def cnj_mask(digits20: str) -> str:
    if not digits20 or len(digits20) != 20 or not digits20.isdigit():
        return digits20
    return f"{digits20[0:7]}-{digits20[7:9]}.{digits20[9:13]}.{digits20[13]}.{digits20[14:16]}.{digits20[16:20]}"


def get_latest_updated_cpj_processes(limit: int = 50) -> List[Dict[str, Any]]:
    query = text(
        """
        SELECT
            mpp.cod_processo,
            mpa.cod_agrupador,
            p.ficha,
            p.incidente,
            p.numero_processo,
            p.juizo,
            p.valor_causa,
            p.entrada,
            p.update_data_hora
        FROM cad_processo p
        INNER JOIN mp_processo AS mpp ON mpp.numero_processo = p.numero_processo
        LEFT JOIN mp_agrupador AS mpa ON mpa.cod_processo = mpp.cod_processo
        WHERE p.numero_processo IS NOT NULL AND p.numero_processo <> ''
        ORDER BY (p.update_data_hora IS NULL) ASC, p.update_data_hora DESC
        LIMIT :limit
        """
    )
    with cpj_engine.connect() as connection:
        rows = connection.execute(query, {"limit": limit}).fetchall()
        logger.info(
            "Encontrados %d processos recentemente atualizados e válidos no CPJ.",
            len(rows),
        )
        return [dict(row._mapping) for row in rows]


def _get_cpj_envolvidos(ficha: str, incidente: int) -> List[Dict[str, Any]]:
    query = text(
        """
        SELECT
            ce.qualificacao,
            cp.nome,
            cp.cpf_cnpj
        FROM cad_envolvido ce
        JOIN cad_pessoa cp ON cp.codigo = ce.pessoa
        WHERE ce.ficha = :ficha AND ce.incidente = :incidente
        """
    )
    with cpj_engine.connect() as connection:
        rows = connection.execute(
            query, {"ficha": ficha, "incidente": incidente}
        ).fetchall()
        return [dict(row._mapping) for row in rows]


def _get_cpj_andamentos(cod_agrupador: int) -> List[Dict[str, Any]]:
    query = text(
        """
        SELECT data_andamento, texto_andamento
        FROM mp_andamento
        WHERE cod_agrupador = :cod_agrupador
        ORDER BY data_andamento ASC
        """
    )
    with cpj_engine.connect() as connection:
        rows = connection.execute(query, {"cod_agrupador": cod_agrupador}).fetchall()
        return [dict(row._mapping) for row in rows]


def _infer_tipo_pessoa(doc: str) -> str:
    numeros = _only_digits(doc) or ""
    return "J" if len(numeros) == 14 else "F"


def sync_process_from_cpj(
    db: Session, user_id: str, cpj_data: Dict[str, Any]
) -> Optional[models.LegalProcess]:
    numero_processo_raw: Optional[str] = cpj_data.get("numero_processo")
    ficha: Optional[str] = cpj_data.get("ficha")
    cod_processo_cpj: Optional[int] = cpj_data.get("cod_processo")

    if not numero_processo_raw or not cod_processo_cpj:
        logger.warning(
            "Dados insuficientes para sincronizar processo (Ficha: %s). Faltando numero_processo ou cod_processo.",
            ficha,
        )
        return None

    cnj = cnj_digits(numero_processo_raw)
    if not cnj:
        logger.warning(
            "CNJ inválido/inesperado vindo do CPJ: %r (Ficha: %s)",
            numero_processo_raw,
            ficha,
        )
        return None

    cnj_formatado = cnj_mask(cnj)
    logger.info(
        "Sincronizando processo (CNJ: %s | Ficha: %s)...",
        cnj_formatado,
        ficha,
    )

    processo_principal = None
    processo_formatado = (
        db.query(models.LegalProcess).filter_by(process_number=cnj_formatado).first()
    )
    processo_raw = (
        db.query(models.LegalProcess)
        .filter_by(process_number=numero_processo_raw)
        .first()
        if numero_processo_raw != cnj_formatado
        else None
    )

    if processo_formatado and processo_raw:
        logger.info(
            f"Resolvendo duplicata para CNJ {cnj_formatado}. Unificando em ID {processo_formatado.id}."
        )
        db.query(models.CPJProcess).filter_by(legal_process_id=processo_raw.id).update(
            {"legal_process_id": processo_formatado.id}, synchronize_session=False
        )
        db.delete(processo_raw)
        db.flush()
        processo_principal = processo_formatado
    elif processo_formatado:
        processo_principal = processo_formatado
    elif processo_raw:
        processo_raw.process_number = cnj_formatado
        processo_principal = processo_raw
    else:
        processo_principal = models.LegalProcess(
            owner_id=user_id, process_number=cnj_formatado
        )
        db.add(processo_principal)

    processo_principal.valor_causa = cpj_data.get("valor_causa")
    processo_principal.start_date = cpj_data.get("entrada")
    processo_principal.orgao_julgador = cpj_data.get("juizo")
    processo_principal.status = "Sincronizado do CPJ"

    envolvidos = _get_cpj_envolvidos(ficha, cpj_data.get("incidente", 0))
    if not processo_principal.parties:
        for p in envolvidos:
            polo = "ATIVO" if p.get("qualificacao") == 1 else "PASSIVO"
            party_preview = models.ProcessParty(
                process=processo_principal,
                polo=polo,
                name=p.get("nome", "Não informado"),
                document_number=p.get("cpf_cnpj"),
            )
            db.add(party_preview)

    db.flush()

    cpj_process_db = (
        db.query(models.CPJProcess).filter_by(cpj_cod_processo=cod_processo_cpj).first()
    )
    if not cpj_process_db:
        cpj_process_db = models.CPJProcess(
            legal_process_id=processo_principal.id, cpj_cod_processo=cod_processo_cpj
        )
        db.add(cpj_process_db)
    else:
        cpj_process_db.legal_process_id = processo_principal.id

    cpj_process_db.cpj_cod_agrupador = cpj_data.get("cod_agrupador")
    cpj_process_db.ficha = ficha
    cpj_process_db.incidente = cpj_data.get("incidente")
    cpj_process_db.numero_processo = numero_processo_raw
    cpj_process_db.juizo = cpj_data.get("juizo")
    cpj_process_db.valor_causa = cpj_data.get("valor_causa")
    cpj_process_db.entrada_date = cpj_data.get("entrada")
    cpj_process_db.last_update_cpj = cpj_data.get("update_data_hora")

    db.flush()

    db.query(models.CPJParty).filter_by(process_id=cpj_process_db.id).delete()
    for p in envolvidos:
        documento = p.get("cpf_cnpj") or ""
        db.add(
            models.CPJParty(
                process_id=cpj_process_db.id,
                qualificacao=p.get("qualificacao"),
                nome=p.get("nome"),
                documento=documento,
                tipo_pessoa=_infer_tipo_pessoa(documento),
            )
        )

    if cpj_process_db.cpj_cod_agrupador:
        db.query(models.CPJMovement).filter_by(process_id=cpj_process_db.id).delete()
        for a in _get_cpj_andamentos(cpj_process_db.cpj_cod_agrupador):
            db.add(
                models.CPJMovement(
                    process_id=cpj_process_db.id,
                    data_andamento=a.get("data_andamento"),
                    texto_andamento=a.get("texto_andamento"),
                )
            )

    processo_principal.last_update = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(processo_principal)
        logger.info(
            "Sincronização base do CPJ concluída para %s.",
            cnj_formatado,
        )
        return processo_principal
    except Exception as e:
        db.rollback()
        logger.error(
            "Erro ao salvar dados do CPJ para %s. Rollback executado. Erro: %s",
            numero_processo_raw,
            e,
            exc_info=True,
        )
        return None

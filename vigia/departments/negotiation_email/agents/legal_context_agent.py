from .base_llm_agent import BaseLLMAgent
import json
from typing import Any, Dict, List, Union


SYSTEM_INSTRUCTION = """
Você é um ADVOGADO PROCESSUALISTA. Entrada: JSON bruto do PDPJ.
Saída: **APENAS** JSON puro, estritamente no schema descrito. Nunca inclua comentários/markdown.

REGRAS PRINCIPAIS:
1) Não invente dados; faltando texto -> use "texto_indisponivel".
2) Timeline: derive de 'timeline_pre' ou de trâmite; datas YYYY-MM-DD; doc_ref quando possível.
3) Partes/advogados: preencher quando identificável.
4) Mapear campos gerais (numero_processo, classe, assunto, valor_causa, órgão, tribunal).
5) DOCUMENTOS_CHAVE: "inicial", "contestacao", "replica" com resumo (4–8 linhas) + pontos (3–8) + refs.
6) TEMA 1061/STJ: setar aplica_tema_1061_stj e detalhe.
7) RISCOS: nivel (baixo|moderado|alto) + fatores (3–8).
8) ACORDO: proximos_passos_provaveis; faixa_de_acordo_sugerida {min, max} numéricos se houver base; senão null + hipótese.
9) Citações (refs) obrigatórias nos textos factuais, com doc_id existindo em _evidence_index.docs; se desconhecido, usar [].
"""

class LegalContextSynthesizerAgent(BaseLLMAgent):
    """
    Consolida o contexto jurídico do PDPJ em um JSON normalizado
    (com schema validado no provider) e com timeline garantida.
    """

    def __init__(self):
        super().__init__(
            SYSTEM_INSTRUCTION,
            expects_json=True,
        )

    # --------- Helpers internos (defensivos) ---------
    @staticmethod
    def _pick_root(processo_json: Union[Dict[str, Any], List[Any]]) -> Dict[str, Any]:
        if isinstance(processo_json, list):
            return processo_json[0] if processo_json else {}
        return processo_json or {}

    @staticmethod
    def _sanitize_payload(root: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reduz tokens e remove binários/base64 sem perder semântica necessária.
        Mantém metadados úteis (id, nome, data, tipo).
        """
        if not isinstance(root, dict):
            return {}

        sanitized = dict(root)  # shallow copy

        # Documentos: manter metadados, remover conteúdo pesado
        docs = sanitized.get("documentos") or sanitized.get("docs") or []
        if isinstance(docs, list):
            new_docs = []
            for d in docs:
                if not isinstance(d, dict):
                    continue
                new_docs.append({
                    "id": d.get("id") or d.get("documentoId"),
                    "nome": d.get("nome") or d.get("titulo") or d.get("arquivo"),
                    "tipo": d.get("tipo") or d.get("categoria"),
                    "data": d.get("data") or d.get("dataJuntada") or d.get("dataPublicacao"),
                    "tamanho": d.get("tamanho") or d.get("size")
                })
            sanitized["documentos"] = new_docs

        # Remover campos potencialmente gigantes
        for k in list(sanitized.keys()):
            if k.lower() in {"pdf", "bin", "ocr", "conteudo", "conteudoBase64".lower(),
                             "arquivo", "arquivoBase64".lower(), "html"}:
                sanitized.pop(k, None)

        # Trâmite: manter só campos “leves”
        tram = sanitized.get("tramitacaoAtual") or sanitized.get("tramitacao") or {}
        if isinstance(tram, dict):
            keep = {}
            for key in ["eventos", "movimentos", "juntadas", "decisoes", "andamentos"]:
                if key in tram and isinstance(tram[key], list):
                    # recorta cada item para data/descricao/tipo/doc_ref quando existir
                    slim_list = []
                    for it in tram[key]:
                        if not isinstance(it, dict):
                            continue
                        slim_list.append({
                            "data": it.get("data") or it.get("dataEvento") or it.get("dataMovimento"),
                            "descricao": it.get("descricao") or it.get("texto") or it.get("tipo"),
                            "tipo": it.get("tipo") or key.upper(),
                            "doc_ref": it.get("documentoId") or it.get("doc") or it.get("arquivo")
                        })
                    # limita para evitar contexto enorme
                    keep[key] = slim_list[-200:]
            sanitized["tramitacaoAtual"] = keep

        # timeline_pre: se vier enorme, limitar
        tl_pre = sanitized.get("timeline_pre")
        if isinstance(tl_pre, list) and len(tl_pre) > 300:
            sanitized["timeline_pre"] = tl_pre[-300:]

        return sanitized

    @staticmethod
    def _fallback_minimal(root: Dict[str, Any]) -> Dict[str, Any]:
        """
        Em caso de falha de LLM, devolve esqueleto mínimo para não quebrar o fluxo.
        """
        numero = (
            root.get("numeroProcesso") or
            root.get("dados_gerais", {}).get("numero_processo") or
            ""
        )
        return {
            "dados_gerais": {
                "numero_processo": numero,
                "classe": root.get("classeProcessual") or "",
                "assunto": root.get("assunto") or "",
                "valor_causa": None,
                "orgao_julgador": root.get("orgaoJulgador") or "",
                "tribunal": root.get("tribunal") or "",
            },
            "partes": {"ativo": [], "passivo": [], "advogados": []},
            "timeline": root.get("timeline_pre") or [],
            "status_processual": root.get("situacao") or "",
            "documentos_chave": {
                "inicial": {"resumo": "texto_indisponivel", "pontos": []},
                "contestacao": {"resumo": "texto_indisponivel", "pontos": []},
                "replica": {"resumo": "texto_indisponivel", "pontos": []},
                "decisoes_relevantes": []
            },
            "onus_da_prova": {
                "aplica_tema_1061_stj": False,
                "detalhe": "texto_indisponivel"
            },
            "riscos": {"nivel": "moderado", "fatores": [], "observacoes": ""},
            "proximos_passos_provaveis": [],
            "faixa_de_acordo_sugerida": {"min": None, "max": None, "hipoteses": "Sem base suficiente."},
            "resumo_textual": "texto_indisponivel"
        }

    # --------- Execução ---------
    async def execute(self, processo_json: dict) -> str:
        if not processo_json:
            # Mantém a mensagem antiga para compatibilidade, mas retorna JSON válido.
            return json.dumps(self._fallback_minimal({}), ensure_ascii=False)

        root = self._pick_root(processo_json)
        payload = self._sanitize_payload(root)

        # Chama a LLM com schema rígido
        llm_out = await self._llm_call(json.dumps(payload, ensure_ascii=False))

        # Em caso de falha/erro do provider, devolve fallback mínimo
        if not isinstance(llm_out, str) or not llm_out.strip() or llm_out.strip().startswith('{"error"'):
            return json.dumps(self._fallback_minimal(root), ensure_ascii=False)

        return llm_out

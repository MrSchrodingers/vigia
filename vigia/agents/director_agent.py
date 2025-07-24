import json
import logging
from datetime import datetime
from ..services import llm_service

class BusinessDirectorAgent:
    def __init__(self):
        self.system_prompt = """
        Você é o Diretor Comercial, um estratega mestre em tomar decisões. Sua função é
        analisar relatórios consolidados e decidir a próxima ação. Você opera com uma
        árvore de decisão: primeiro verifica se um acordo foi fechado; se não, verifica
        se um follow-up foi agendado; se nenhuma das opções for verdadeira, você emite uma
        análise estratégica. Você DEVE usar as ferramentas disponíveis sempre que as
        condições para tal forem cumpridas.
        """

    async def execute(self, final_data_str: str, final_temp_str: str, conversation_id: str) -> str | dict:
        """
        Recebe os relatórios, constrói o prompt com uma árvore de decisão e executa a chamada ao LLM.
        """
        executive_summary = f"""
        Resumo da Negociação {conversation_id}:
        - Relatório de Dados Extraídos: {final_data_str}
        - Relatório de Temperatura da Conversa: {final_temp_str}
        """

        try:
            conversation_data = json.loads(final_data_str)
            if not isinstance(conversation_data, dict):
                raise json.JSONDecodeError("O JSON carregado não é um objeto (dicionário).", final_data_str, 0)
        except json.JSONDecodeError:
            logging.error(f"Diretor recebeu JSON de extração inválido ou não-objeto para {conversation_id}: {final_data_str}")
            return json.dumps({
                "status_geral": "Falha na Análise",
                "proxima_acao_sugerida": "Revisão Manual Urgente",
                "detalhes_acao": "O relatório de extração de dados está malformatado ou não é um objeto JSON. A análise foi interrompida."
            })

        status = conversation_data.get("status")
        valores = conversation_data.get("valores", {})
        prazos = conversation_data.get("prazos", {})
        
        data_acordo = prazos.get("data_final_acordada_absoluta")
        data_follow_up = prazos.get("data_follow_up_agendada")

        resumo_negociacao = conversation_data.get("resumo_negociacao")
        telefone_contato = conversation_id.split('@')[0]

        user_prompt = f"""
        A data de hoje é {datetime.now().strftime('%Y-%m-%d')}.
        Abaixo está o resumo executivo de uma negociação. Avalie e decida a próxima ação
        seguindo ESTRITAMENTE a árvore de decisão abaixo.

        --- RESUMO EXECUTIVO ---
        {executive_summary}
        ---

        **ÁRVORE DE DECISÃO PARA AÇÃO:**
        1.  **SE** o status for 'Acordo Fechado' AND a 'data_final_acordada_absoluta' estiver preenchida:
            - Use a ferramenta 'criar_atividade_no_pipedrive'.
            - Preencha o 'subject' com "Cobrança do acordo com {telefone_contato}".
            - Use a 'data_final_acordada_absoluta' como 'due_date'.
            - A 'note' deve ser um resumo claro do acordo final: valor, parcelas e data.

        2.  **SENÃO SE** a 'data_follow_up_agendada' estiver preenchida:
            - Use a ferramenta 'criar_atividade_no_pipedrive'.
            - Preencha o 'subject' com "Follow-up agendado com {telefone_contato}".
            - Use a 'data_follow_up_agendada' como 'due_date'.
            - A 'note' deve ser uma instrução clara para a ação de follow-up. Ela deve começar destacando a AÇÃO PENDENTE e depois fornecer um breve resumo do contexto. Exemplo: 'AÇÃO: Verificar se o cliente respondeu à proposta de R$ 2.000,00. CONTEXTO: Cliente ficou de dar retorno nesta data após o envio da proposta.' Use o resumo da negociação como base para o contexto.

        3.  **SENÃO** (para todos os outros casos):
            - Forneça uma decisão estratégica em JSON com 'status_geral', 'proxima_acao_sugerida' e 'detalhes_acao'.
        
        **DADOS DISPONÍVEIS PARA PREENCHER AS FERRAMENTAS:**
        - Status da Negociação: "{status}"
        - Data do Acordo de Pagamento: "{data_acordo}"
        - Data de Follow-up Agendada: "{data_follow_up}"
        - Telefone do Contato (person_phone): "{telefone_contato}"
        - Resumo para a Nota (note): "{resumo_negociacao}"
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt, use_tools=True)

director_agent = BusinessDirectorAgent()
# Projeto VigIA: Agente Supervisor de IA
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?&style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)

> **VigIA** é um sistema autônomo de IA projetado para atuar como um supervisor em conversas de negociação. Utilizando uma arquitetura multiagente e polimórfica, ele se integra a plataformas de comunicação como WhatsApp e E-mail para analisar, extrair dados, avaliar o sentimento e tomar decisões estratégicas sobre o andamento das negociações em tempo real.

## Índice

- [Conceitos Principais: Arquitetura Organizacional de IA](#conceitos-principais-arquitetura-organizacional-de-ia)
- [Arquitetura de Sistema](#arquitetura-de-sistema)
- [Fluxos de Análise dos Departamentos de IA](#fluxos-de-análise-dos-departamentos-de-ia)
  - [Fluxo do Departamento de WhatsApp](#fluxo-do-departamento-de-whatsapp)
  - [Fluxo do Departamento de E-mail](#fluxo-do-departamento-de-e-mail)
- [Dashboard de Análises](#dashboard-de-análises)
- [Como Executar (Guia Prático)](#como-executar-guia-prático)
- [Tecnologias Utilizadas](#tecnologias-utilizadas)

-----

## Conceitos Principais: Arquitetura Organizacional de IA

O VigIA emula uma estrutura organizacional para decompor a complexa tarefa de análise de conversas. Cada "departamento" é composto por agentes de IA com diferentes especializações e vieses, trabalhando em paralelo e em hierarquia para produzir um relatório coeso e confiável.

- **Orquestração Geral:** Um "Diretor-Geral" atua como a camada de entrada, roteando cada nova comunicação para o departamento especializado correto (WhatsApp ou E-mail) com base na sua origem.
- **Princípio da Diversidade Cognitiva:** Inspirado no conceito de que equipes com diferentes pontos de vista tomam decisões melhores, o VigIA emprega agentes com "personalidades" distintas (ex: um `cauteloso` e um `inquisitivo`) para analisar a mesma informação, reduzindo vieses e aumentando a precisão.
- **Hierarquia de Análise:** A informação flui de agentes *especialistas* (focados em tarefas pequenas) para agentes *gerentes* (que sintetizam informações) e, finalmente, para um agente *diretor* (que toma a decisão estratégica final para aquele departamento).
- **Fonte Única da Verdade:** Embora os agentes gerem suas análises, o histórico completo da conversa, persistido no banco de dados, é sempre a fonte final da verdade, usada pelos agentes gerentes para validar e refinar as conclusões preliminares.

-----

## Arquitetura de Sistema

O sistema é construído sobre uma arquitetura de microsserviços containerizada e orientada a eventos, garantindo escalabilidade, resiliência e desacoplamento.

```mermaid
flowchart LR
  %% --- Fontes de comunicação ---
  subgraph Fontes_Comunicacao
    WA[Evolution API – WhatsApp]
    EM[Microsoft Graph API – E-mail]
  end

  %% --- Infra externa ---
  subgraph Infra_Externa
    CRM[Pipedrive CRM]
  end

  %% --- Núcleo VigIA ---
  subgraph VigIA
    ING[FastAPI – API de Ingestão]
    Q[Redis – Fila/Cache]
    WK[Celery – Worker]
    DB[(PostgreSQL)]
    DASH_WA[Streamlit – Dash WhatsApp]
    DASH_EM[Streamlit – Dash E-mail]

    %% pipeline assíncrono (sem loops!)
    WK -->|Busca histórico| DB
    WK -->|Busca contexto| CRM
    WK -->|Chama LLMs| LLM{Ollama / Gemini}
    WK -->|Salva análise| DB
  end

  %% --- Conexões globais ---
  WA -->|Webhook| ING
  EM -->|Webhook| ING
  ING -->|Enfileira| Q
  Q -->|Entrega tarefa| WK
  DASH_WA -->|Lê análises| DB
  DASH_EM -->|Lê análises| DB
````

  - **API de Ingestão (`FastAPI`):** Um endpoint leve que recebe webhooks de múltiplas fontes (WhatsApp, E-mail), adiciona uma tag de `source` ao payload e enfileira a tarefa no Redis para processamento assíncrono.
  - **Message Broker (`Redis`):** Atua como o intermediário que desacopla a API do Worker. Armazena a fila de tarefas a serem processadas.
  - **Worker de Análise (`Celery`):** O coração do sistema. Consome tarefas da fila, invoca o "Diretor-Geral" para rotear a tarefa, orquestra o ciclo de análise dos agentes de IA do departamento correspondente e persiste os resultados no banco de dados.
  - **Database (`PostgreSQL`):** Armazena de forma persistente as conversas, mensagens, threads de e-mail e os resultados estruturados e polimórficos das análises de IA.
  - **Dashboards (`Streamlit`):** Interfaces web interativas para visualização e análise dos dados gerados pelo VigIA, com um dashboard dedicado para cada departamento (WhatsApp e E-mail).

-----

## Fluxos de Análise dos Departamentos de IA

O processamento dentro do worker é dividido em departamentos que operam com estratégias de IA distintas. **Clique em cada departamento para expandir e ver os detalhes.**

### Fluxo do Departamento de WhatsApp

**Estratégia Principal:** *Tree of Thoughts (ToT)* para extração de dados e análise de sentimento, com pré-processamento de áudio.

**Fase 1: Pré-processamento e Contexto**

  - **Transcrição de Áudio:** O histórico da conversa é analisado. Segmentos de áudio (`[ÁUDIO...]`) são identificados e transcritos usando um agente especializado para lidar com as trancrições geradas pelo modelo Whisper. O texto transcrito substitui a tag de áudio no histórico.
  - **Departamento de Contexto (Estratégia GAN):** Um agente "Minerador" busca dados no Pipedrive a partir do telefone. Um agente "Sintetizador" formata esses dados em um resumo textual claro que é pré-anexado ao histórico.

**Fase 2: Extração e Temperatura (Execução Paralela)**

  - **Departamento de Extração de Dados (Tree of Thoughts):**

    ```mermaid
      flowchart TD
        H[Histórico + Contexto] --> CA(Agente Cauteloso)
        H --> INQ(Agente Inquisitivo)
        CA -->|Relatório literal| GER(Agente Gerente)
        INQ -->|Relatório inferencial| GER
        H --> GER
        GER -->|JSON final| OUT[Dados Extraídos]
    ```

      - **Agente Cauteloso:** Extrai apenas dados explícitos.
      - **Agente Inquisitivo:** Faz inferências lógicas para preencher dados.
      - **Agente Gerente:** Recebe os dois relatórios, compara com o histórico, resolve conflitos (especialmente com datas relativas) e produz o relatório final.

  - **Departamento de Análise de Temperatura:**

      - **Agente Lexical:** Foca em palavras, emojis e pontuação.
      - **Agente Comportamental:** Foca em padrões como frequência e uso de caixa alta.
      - **Agente Gerente de Sentimento:** Consolida as duas análises para determinar a "temperatura final" e a "tendência".

**Fase 3: Supervisão e Diretoria**

  - **Agente de Guarda (Auditor):** Um agente meta que valida se a estrutura do JSON da extração está em conformidade com o schema esperado, garantindo a qualidade dos dados.
  - **Agente Diretor (WhatsApp):** Recebe os relatórios validados e, seguindo uma árvore de decisão estrita, determina a próxima ação. Ele pode acionar ferramentas como `criar_atividade_no_pipedrive` ou `AlertarSupervisor`.

### Fluxo do Departamento de E-mail

**Estratégia Principal:** *Adversarial* para extração de dados, garantindo máxima precisão através de um ciclo de geração, crítica e refinamento.

**Fase 1: Contexto e Preparação**

  - **Departamento de Contexto:** A lógica é invertida. O agente "Minerador" primeiro extrai o número do processo do assunto do e-mail para buscar o Deal no Pipedrive, e só então busca a Pessoa associada, garantindo maior precisão. O "Sintetizador" formata os dados para o histórico.
  - **Limpeza de HTML:** O corpo dos e-mails é pré-processado para remover tags HTML e extrair o texto puro, facilitando a análise.

**Fase 2: Extração e Temperatura (Execução Paralela)**

  - **Departamento de Extração de Dados (Estratégia Adversarial):**

    ```mermaid
      flowchart TD
        H[Histórico + Contexto] --> GEN(Agente Gerador)
        GEN -->|Inicial| AUD(Agente Validador)
        AUD -->|Crítica| REF(Agente Refinador)
        GEN --> REF
        H --> AUD & REF
        REF -->|JSON final| OUT[Dados Extraídos]
    ```

      - **Agente Gerador (Legal/Financeiro):** Realiza a extração inicial dos dados da negociação.
      - **Agente Validador (Auditor):** Recebe a extração inicial e a critica rigorosamente em busca de erros, omissões ou má interpretação.
      - **Agente Refinador (Juiz):** Recebe a extração inicial e a crítica do auditor para produzir a versão final e definitiva do JSON.
      - **Agentes Especialistas Adicionais:** Agentes focados no assunto do e-mail e no estágio da negociação rodam em paralelo para enriquecer o relatório final.

  - **Departamento de Análise de Temperatura:**

      - **Agente Comportamental (E-mail):** Este agente analisa os *metadados* da thread (importância, latência de resposta, anexos) para inferir o comportamento e o engajamento.

**Fase 3: Análise Estratégica e Diretoria**

  - **Agente Conselheiro Judicial:** Um agente especializado que recebe todos os dados (extração, temperatura, KPIs, contexto) e fornece uma recomendação jurídica sobre a próxima ação, estimando probabilidade de sucesso e custos.
  - **Agente Sumarizador Formal:** Cria um resumo formal e estruturado da negociação, ideal para ser salvo como nota no CRM.
  - **Agente Diretor (E-mail):** Recebe todos os relatórios consolidados e, seguindo uma árvore de decisão complexa, pode acionar múltiplas ferramentas, como `AgendarFollowUp` e `AlertarSupervisorParaAtualizacao`, garantindo que tanto a negociação quanto os dados no CRM avancem.

-----

## Dashboard de Análises

O projeto inclui dashboards interativos construídos com Streamlit, que fornecem uma visão aprofundada das análises geradas. Eles se conectam diretamente ao banco de dados PostgreSQL e oferecem múltiplas abas para diferentes tipos de análise, com uma URL para cada departamento:

  - **Dashboard de WhatsApp:** Focado em métricas de performance, KPIs financeiros e operacionais, e insights extraídos das conversas de texto e áudio.
  - **Dashboard de E-mail:** Focado em análises de funil, tempo de resolução, modelagem estatística (Logit, Curva de Sobrevivência) e visualizações de rede de participantes.

-----

## Como Executar (Guia Prático)

### Pré-requisitos

  - [Docker](https://www.docker.com/products/docker-desktop/) e [Docker Compose](https://docs.docker.com/compose/install/) instalados.
  - [Git](https://git-scm.com/downloads) instalado.

### 1\. Configuração do Ambiente

Primeiro, **clone o repositório** e entre no diretório. Depois, **crie o seu arquivo de configuração** a partir do exemplo.

```bash
git clone <URL_DO_REPOSITORIO>
cd VigIA
cp .env.example .env
```

Agora, **edite o arquivo `.env`** e preencha todas as variáveis necessárias.

### 2\. Executando a Aplicação

Com o arquivo `.env` configurado, **suba os containers** com o Docker Compose:

```bash
docker-compose up --build -d
```

O comando `-d` executa os containers em modo "detached". Para **visualizar os logs em tempo real**:

```bash
docker-compose logs -f api worker
```

> 💡 **Nota:** Ao iniciar pela primeira vez, o script `docker-entrypoint.sh` executará as migrações do Alembic automaticamente, criando as tabelas no banco de dados.

### 3\. Acessando os Serviços

  - **API:** `http://localhost:8026`
  - **Dashboard WhatsApp:** `http://localhost:8501`
  - **Dashboard E-mail:** `http://localhost:8502`

### 4\. Ingestão e Análise de Dados

  - **Webhook:** Configure sua Evolution API (WhatsApp) ou Microsoft Graph API (E-mail) para enviar webhooks para os endpoints correspondentes em `http://<SEU_IP>:8026/webhook/...`.
  - **Importação Histórica (WhatsApp):** Para analisar conversas passadas, execute o script de importação:
    ```bash
    docker-compose exec api python -m vigia.departments.negotiation_whatsapp.scripts.historical_importer
    ```
  - **Reanálise em Lote:** Para reanalisar conversas já existentes no banco (útil após uma melhoria nos prompts), use os scripts de análise de cada departamento:
    ```bash
    # Reanalisa uma conversa específica do WhatsApp
    docker-compose exec api python -m vigia.departments.negotiation_whatsapp.scripts.reanalyze_conversation --conversa <REMOTE_JID_DA_CONVERSA> --salvar

    # Reanalisa uma thread de e-mail específica
    docker-compose exec api python -m vigia.departments.negotiation_email.scripts.reanalyze_thread --thread <CONVERSATION_ID_DA_THREAD> --salvar
    ```

-----

## Tecnologias Utilizadas

| Tecnologia | Papel no Projeto |
| :--- | :--- |
| **Python** | Linguagem principal de desenvolvimento. |
| **FastAPI** | Framework web assíncrono para a API de ingestão. |
| **Celery** | Sistema de filas distribuídas para processamento assíncrono. |
| **PostgreSQL** | Banco de dados relacional para persistência dos dados. |
| **Redis** | Message broker para o Celery e cache. |
| **Docker** | Plataforma de containerização para ambiente e deploy. |
| **Alembic** | Ferramenta para gerenciamento de migrações de schema do DB. |
| **Streamlit** | Framework para criação dos Dashboards de Análises. |
| **Ollama/Gemini**| Provedores de Large Language Models (LLMs) para a IA. |
| **Pydantic** | Validação de dados e gerenciamento de configurações. |
| **Whisper** | Modelo de IA para transcrição de áudio de alta precisão. |
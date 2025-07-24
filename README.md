# Projeto VigIA: Agente Supervisor de IA

> **VigIA** é um sistema autônomo de IA projetado para atuar como um supervisor em conversas de negociação. Utilizando uma arquitetura multiagente, ele se integra a plataformas de comunicação para analisar, extrair dados, avaliar o sentimento e tomar decisões estratégicas sobre o andamento das negociações em tempo real.

## Índice

  - [Conceitos Principais: Arquitetura Organizacional de IA](https://www.google.com/search?q=%23conceitos-principais-arquitetura-organizacional-de-ia)
  - [Arquitetura de Sistema](https://www.google.com/search?q=%23arquitetura-de-sistema)
  - [Fluxos de Análise dos Departamentos de IA](https://www.google.com/search?q=%23fluxos-de-an%C3%A1lise-dos-departamentos-de-ia)
  - [Dashboard de Análises](https://www.google.com/search?q=%23dashboard-de-an%C3%A1lises)
  - [Como Executar (Guia Prático)](https://www.google.com/search?q=%23como-executar-guia-pr%C3%A1tico)
  - [Tecnologias Utilizadas](https://www.google.com/search?q=%23tecnologias-utilizadas)

-----

## Conceitos Principais: Arquitetura Organizacional de IA

O VigIA emula uma estrutura organizacional para decompor a complexa tarefa de análise de conversas. Cada "departamento" é composto por agentes de IA com diferentes especializações e vieses, trabalhando em paralelo e em hierarquia para produzir um relatório coeso e confiável.

  - **Princípio da Diversidade Cognitiva:** Inspirado no conceito de que equipes com diferentes pontos de vista tomam decisões melhores, o VigIA emprega agentes com "personalidades" distintas (ex: um `cauteloso` e um `inquisitivo`) para analisar a mesma informação, reduzindo vieses e aumentando a precisão.
  - **Hierarquia de Análise:** A informação flui de agentes *especialistas* (focados em tarefas pequenas) para agentes *gerentes* (que sintetizam informações) e, finalmente, para um agente *diretor* (que toma a decisão estratégica).
  - **Fonte Única da Verdade:** Embora os agentes gerem suas análises, o histórico completo da conversa, persistido no banco de dados, é sempre a fonte final da verdade, usada pelos agentes gerentes para validar e refinar as conclusões preliminares.

-----

## Arquitetura de Sistema

O sistema é construído sobre uma arquitetura de microsserviços containerizada e orientada a eventos, garantindo escalabilidade, resiliência e desacoplamento.

```mermaid
graph TD
    subgraph "Infraestrutura Externa"
        A[Evolution API - WhatsApp]
        G[Pipedrive CRM]
    end

    subgraph "Infraestrutura VigIA (Docker Compose)"
        B(FastAPI - API Ingestion)
        C(Redis - Cache & Message Broker)
        D(Celery - Worker de Análise)
        E(PostgreSQL - Banco de Dados)
        H(Streamlit - Dashboard)

        subgraph "Processamento Assíncrono"
            direction LR
            D -- Busca Histórico --> E
            D -- Busca Contexto --> G
            D -- Chama LLMs --> F{LLM Providers}
            D -- Salva Análise --> E
        end
        
        H -- Lê Análises --> E
    end

    subgraph "Provedores de IA"
        F[Ollama / Gemini]
    end

    A -- Webhook --> B
    B -- Enfileira Tarefa --> C
    D -- Consome Tarefa --> C
```

  - **Ingestion API (`FastAPI`):** Um endpoint leve que recebe webhooks, valida minimamente e enfileira a tarefa no Redis. Sua única responsabilidade é a ingestão rápida.
  - **Message Broker (`Redis`):** Atua como o intermediário que desacopla a API do Worker. Armazena a fila de tarefas a serem processadas.
  - **Analysis Worker (`Celery`):** O coração do sistema. Consome tarefas da fila, orquestra o ciclo de análise dos agentes de IA e persiste os resultados. Pode ser escalado horizontalmente para aumentar a capacidade de processamento.
  - **Database (`PostgreSQL`):** Armazena de forma persistente as conversas, mensagens e os resultados estruturados das análises de IA.
  - **Dashboard (`Streamlit`):** Uma interface web interativa para visualização e análise dos dados gerados pelo VigIA.

-----

## Fluxos de Análise dos Departamentos de IA

O processamento dentro do worker é dividido em fases e departamentos que operam de forma sequencial e paralela para enriquecer e analisar os dados. **Clique em cada departamento para expandir e ver os detalhes.**

\<details\>
\<summary\>\<strong\> Fase 1. Departamento de Contexto (Estratégia GAN)\</strong\>\</summary\>

**Objetivo:** Enriquecer o histórico da conversa com dados externos de um CRM (Pipedrive) antes da análise principal.

```mermaid
graph TD
    A[ID da Conversa] --> B(Agente Minerador de Dados);
    B -- Dados brutos do CRM (JSON) --> C(Agente Sintetizador de Contexto);
    C -- Contexto Formatado (Texto) --> D[Output: Histórico Enriquecido];
```

  - **Agente Minerador de Dados (Gerador):** Busca informações de contatos e negócios no Pipedrive a partir do ID da conversa.
  - **Agente Sintetizador de Contexto (Validador):** Recebe os dados brutos do CRM e os formata em um resumo textual claro e conciso, que é então pré-anexado ao histórico da conversa.

\</details\>

\<details\>
\<summary\>\<strong\> Fase 2. Departamentos de Extração e Temperatura (Execução Paralela)\</strong\>\</summary\>

**Objetivo:** Extrair fatos estruturados e avaliar o sentimento da conversa de forma simultânea.

  - **Departamento de Extração de Dados (Estratégia ToT - Tree of Thoughts):**

    ```mermaid
    graph TD
        A[Histórico Enriquecido] --> B(Agente Cauteloso);
        A --> C(Agente Inquisitivo);
        B -- Relatório Literal (JSON) --> D(Agente Gerente de Validação);
        C -- Relatório Inferencial (JSON) --> D;
        A --> D;
        D -- Relatório Consolidado (JSON) --> F[Output: Dados Extraídos];
    ```

      - **Agente Cauteloso:** Extrai apenas dados explícitos. Se não está escrito, o campo fica nulo.
      - **Agente Inquisitivo:** Faz inferências lógicas para preencher os dados (ex: se o cliente diz "fechado", o status é "Acordo Fechado").
      - **Agente Gerente:** Recebe os dois relatórios, compara com o histórico original, resolve conflitos e produz o relatório final.

  - **Departamento de Análise de Temperatura:**

    ```mermaid
    graph TD
        A[Histórico Original] --> B(Agente Lexical);
        A --> C(Agente Comportamental);
        B -- Análise das Palavras (JSON) --> D(Agente Gerente de Sentimento);
        C -- Análise dos Padrões (JSON) --> D;
        D -- Relatório Consolidado de Temperatura (JSON) --> F[Output: Análise de Temperatura];
    ```

      - **Agente Lexical:** Foca nas palavras, emojis e pontuação para determinar o sentimento.
      - **Agente Comportamental:** Foca nos padrões: frequência, uso de caixa alta, velocidade das respostas.
      - **Agente Gerente de Sentimento:** Consolida as duas análises para determinar a "temperatura final" e a "tendência" (se a conversa está melhorando ou piorando).

\</details\>

\<details\>
\<summary\>\<strong\> Fase 3. Departamentos de Supervisão e Diretoria (Execução Sequencial)\</strong\>\</summary\>

**Objetivo:** Garantir a conformidade dos dados e tomar a decisão estratégica final.

```mermaid
graph TD
    A[Relatório de Dados Extraídos] --> B(Agente de Guarda - Auditor);
    B -- Validação de Formato --> C(Agente Diretor);
    D[Relatório de Temperatura] --> C;
    C -- Decisão Estratégica ou Chamada de Ferramenta --> F[Output: Decisão Final];
```

  - **Agente de Guarda (Auditor):** Um agente meta que não avalia o conteúdo, mas sim se a estrutura do JSON do departamento de extração está em conformidade com o schema esperado, garantindo a qualidade dos dados.
  - **Agente Diretor:** Recebe os relatórios validados e, seguindo uma árvore de decisão, determina a próxima ação. Ele pode tomar uma decisão estratégica (ex: "Aguardar retorno do cliente") ou acionar uma ferramenta para ações práticas, como criar uma atividade no Pipedrive ou alertar um supervisor humano.

\</details\>

-----

## Dashboard de Análises

O projeto inclui um dashboard interativo construído com Streamlit, que fornece uma visão aprofundada das análises geradas. Ele se conecta diretamente ao banco de dados PostgreSQL e oferece múltiplas abas para diferentes tipos de análise.

  - **Visão Geral:** Métricas principais como total de análises, taxa de sucesso, distribuição de status e volume de análises ao longo do tempo.
  - **Análise Financeira:** Indicadores como valor total original, valor acordado, descontos concedidos e taxa de recuperação. Inclui gráficos de dispersão e histogramas para visualizar a relação entre valores e descontos.
  - **Performance Operacional:** Gráficos sobre as próximas ações sugeridas pelo Agente Diretor e a tendência (melhorando, piorando, estável) das conversas.
  - **Insights do Cliente:** Análise de frequência dos "pontos-chave" mencionados pelos clientes, permitindo identificar os principais motivos de contato e objeções.
  - **Analytics Avançado:** Modelos estatísticos como regressão linear para correlacionar valor da negociação com percentual de desconto, e clusterização K-Means para segmentar negociações em diferentes perfis.

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

Agora, **edite o arquivo `.env`** e preencha todas as variáveis necessárias:

  - `POSTGRES_*`: Credenciais para o banco de dados.
  - `DATABASE_URL`: A URL de conexão completa, no formato `postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB`. Para o Docker Compose, o host será `postgres`.
  - `REDIS_HOST`: Para o Docker Compose, use `redis`.
  - `CELERY_*_URL`: As URLs para o broker e backend do Celery, usando o host do Redis. Ex: `redis://redis:6379/0`.
  - `LLM_PROVIDER`: Escolha entre `gemini` ou `ollama`.
  - `GEMINI_API_KEY`: Sua chave de API, se estiver usando o Gemini.
  - `EVOLUTION_*`: As credenciais da sua instância da Evolution API.
  - `PIPEDRIVE_*`: Suas credenciais da API do Pipedrive.

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
  - **Dashboard:** `http://localhost:8501`

### 4\. Ingestão e Análise de Dados

  - **Webhook:** Configure sua Evolution API para enviar webhooks de novas mensagens para `http://<SEU_IP>:8026/webhook/evolution`.
  - **Importação Histórica:** Para analisar conversas passadas, execute o script de importação:
    ```bash
    docker-compose exec api python -m scripts.historical_importer
    ```
  - **Reanálise em Lote:** Para reanalisar conversas já existentes no banco (útil após uma melhoria nos prompts), use os scripts de análise:
    ```bash
    # Analisa uma conversa específica
    docker-compose exec api python -m scripts.reanalyze_conversation --conversa <REMOTE_JID_DA_CONVERSA> --salvar

    # Analisa as 10 conversas mais longas
    docker-compose exec api python -m scripts.batch_analyzer --limit 10 --strategy longest
    ```

-----

## Tecnologias Utilizadas

| Tecnologia      | Papel no Projeto                                        |
| :-------------- | :------------------------------------------------------ |
| **Python** | Linguagem principal de desenvolvimento.                 |
| **FastAPI** | Framework web assíncrono para a API de ingestão.        |
| **Celery** | Sistema de filas distribuídas para processamento assíncrono. |
| **PostgreSQL** | Banco de dados relacional para persistência dos dados.  |
| **Redis** | Message broker para o Celery e cache.                   |
| **Docker** | Plataforma de containerização para ambiente e deploy.   |
| **Alembic** | Ferramenta para gerenciamento de migrações de schema do DB. |
| **Streamlit** | Framework para criação do Dashboard de Análises.        |
| **Ollama/Gemini**| Provedores de Large Language Models (LLMs) para a IA.    |
| **Pydantic** | Validação de dados e gerenciamento de configurações.    |

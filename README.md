# Projeto VigIA: Agente Supervisor de IA

> **VigIA** é um sistema autônomo de IA projetado para atuar como um supervisor em conversas de negociação. Utilizando uma arquitetura multiagente, ele se integra a plataformas de comunicação para analisar, extrair dados, avaliar o sentimento e tomar decisões estratégicas sobre o andamento das negociações em tempo real.

\<br\>

## 📚 Índice

  - [Conceitos Principais: Arquitetura Organizacional de IA](https://www.google.com/search?q=%23-conceitos-principais-arquitetura-organizacional-de-ia)
  - [Arquitetura de Sistema](https://www.google.com/search?q=%23%EF%B8%8F-arquitetura-de-sistema)
  - [Fluxos de Análise de IA](https://www.google.com/search?q=%23-fluxos-de-an%C3%A1lise-dos-departamentos-de-ia)
  - [Como Executar (Guia Prático)](https://www.google.com/search?q=%23-como-executar-guia-pr%C3%A1tico)
  - [Tecnologias Utilizadas](https://www.google.com/search?q=%23%EF%B8%8F-tecnologias-utilizadas)

-----

## Conceitos Principais: Arquitetura Organizacional de IA

O VigIA emula uma estrutura organizacional para decompor a complexa tarefa de análise de conversas. Cada "departamento" é composto por agentes de IA com diferentes especializações e vieses, trabalhando em paralelo e em hierarquia para produzir um relatório coeso e confiável.

  - **Princípio da Diversidade Cognitiva:** Inspirado no conceito de que equipes com diferentes pontos de vista tomam decisões melhores, o VigIA emprega agentes com "personalidades" distintas (ex: um `cauteloso` e um `inquisitivo`) para analisar a mesma informação, reduzindo vieses e aumentando a precisão.
  - **Hierarquia de Análise:** A informação flui de agentes *especialistas* (focados em tarefas pequenas) para agentes *gerentes* (que sintetizam informações) e, finalmente, para um agente *diretor* (que toma a decisão estratégica).
  - **Fonte Única da Verdade:** Embora os agentes gerem suas análises, o histórico completo da conversa, persistido no banco de dados, é sempre a fonte final da verdade, usada pelos agentes gerentes para validar e refinar as conclusões preliminares.

-----

## Arquitetura de Sistema

O sistema é construído sobre uma arquitetura de microsserviços containerizada, orientada a eventos, garantindo escalabilidade, resiliência e desacoplamento.

```mermaid
graph TD
    subgraph "Infraestrutura Externa"
        A[Evolution API - WhatsApp]
    end

    subgraph "Infraestrutura VigIA (Docker Compose)"
        B(FastAPI - API Ingestion)
        C(Redis - Cache & Message Broker)
        D(Celery - Worker de Análise)
        E(PostgreSQL - Banco de Dados)

        subgraph "Processamento Assíncrono"
            direction LR
            D -- Busca Histórico --> E
            D -- Chama LLMs --> F{LLM Providers}
            D -- Salva Análise --> E
        end
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

-----

## Fluxos de Análise dos Departamentos de IA

O processamento dentro do worker é dividido em departamentos que operam em paralelo. **Clique em cada departamento para expandir e ver os detalhes.**

\<details\>
\<summary\>\<strong\> 1. Departamento de Extração de Dados\</strong\>\</summary\>

**Objetivo:** Extrair informações estruturadas e fatos da conversa.

```mermaid
graph TD
    A[Histórico da Conversa] --> B(Agente Cauteloso);
    A --> C(Agente Inquisitivo);
    B -- Relatório Literal (JSON) --> D(Agente Gerente de Validação);
    C -- Relatório Inferencial (JSON) --> D;
    A --> D;
    D -- Relatório Consolidado (JSON) --> F[Output: Dados Extraídos];
```

  - **Agente Cauteloso:** Extrai apenas dados explícitos. Se não está escrito, o campo fica nulo.
  - **Agente Inquisitivo:** Faz inferências lógicas para preencher os dados (ex: se o cliente diz "fechado", o status é "Acordo Fechado").
  - **Agente Gerente:** Recebe os dois relatórios, compara com o histórico original, resolve conflitos e produz o relatório final.

\</details\>

\<details\>
\<summary\>\<strong\> 2. Departamento de Análise de Temperatura\</strong\>\</summary\>

**Objetivo:** Avaliar o sentimento e o tom da conversa do ponto de vista do cliente.

```mermaid
graph TD
    A[Histórico da Conversa] --> B(Agente Lexical);
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
\<summary\>\<strong\> 3. Departamentos de Supervisão e Diretoria (Sequencial)\</strong\>\</summary\>

**Objetivo:** Garantir a conformidade e tomar a decisão estratégica final.

```mermaid
graph TD
    A[Relatório de Dados Extraídos] --> B(Agente de Guarda - Auditor);
    B -- Validação de Formato --> C(Agente Diretor);
    D[Relatório de Temperatura] --> C;
    C -- Decisão Estratégica (JSON) --> F[Output: Decisão Final];
```

  - **Agente de Guarda (Auditor):** Um agente meta que não avalia o conteúdo, mas sim se a estrutura do JSON do departamento de extração está em conformidade com o schema esperado.
  - **Agente Diretor:** Recebe os relatórios validados dos outros departamentos e toma a decisão final, como "Monitorar Pagamento" ou "Alertar Supervisor Humano".

\</details\>

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

Agora, **edite o arquivo `_env_`** e preencha todas as variáveis necessárias:

  - `POSTGRES_*`: Credenciais para o banco de dados.
  - `DATABASE_URL`: A URL de conexão completa, no formato `postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB`. Para o Docker Compose, o host será `postgres`.
  - `REDIS_HOST`: Para o Docker Compose, use `redis`.
  - `CELERY_*_URL`: As URLs para o broker e backend do Celery, usando o host do Redis. Ex: `redis://redis:6379/0`.
  - `LLM_PROVIDER`: Escolha entre `gemini` ou `ollama`.
  - `GEMINI_API_KEY`: Sua chave de API, se estiver usando o Gemini.
  - `EVOLUTION_*`: As credenciais da sua instância da Evolution API.

### 2\. Executando a Aplicação

Com o arquivo `_.env_` configurado, **suba os containers** com o Docker Compose:

```bash
docker-compose up --build -d
```

O comando `-d` executa os containers em modo "detached". Para **visualizar os logs em tempo real**:

```bash
docker-compose logs -f api worker
```

> 💡 **Nota:** Ao iniciar pela primeira vez, o script `docker-entrypoint.sh` executará as migrações do Alembic automaticamente, criando as tabelas no banco de dados.

### 3\. Ingestão de Dados

  - **Webhook:** Configure sua Evolution API para enviar webhooks de novas mensagens para `http://<SEU_IP>:8026/webhook/evolution`.
  - **Importação Histórica:** Para analisar conversas passadas, execute o script de importação:
    ```bash
    docker-compose exec api python -m scripts.historical_importer
    ```

### 4\. Análise em Lote

Para reanalisar conversas já existentes no banco (útil após uma melhoria nos prompts), use os scripts de análise:

  - **Analisar uma conversa específica:**
    ```bash
    docker-compose exec api python -m scripts.reanalyze_conversation --conversa <REMOTE_JID_DA_CONVERSA> --salvar
    ```
  - **Analisar um lote de conversas:**
    ```bash
    # Analisa as 10 conversas mais longas
    docker-compose exec api python -m scripts.batch_analyzer --limit 10 --strategy longest

    # Analisa as 5 conversas mais recentes
    docker-compose exec api python -m scripts.batch_analyzer --limit 5 --strategy latest
    ```

-----

## Tecnologias Utilizadas

| Tecnologia | Papel no Projeto |
| :----------- | :------------------------------------------------------ |
| **Python** | Linguagem principal de desenvolvimento. |
| **FastAPI** | Framework web assíncrono para a API de ingestão. |
| **Celery** | Sistema de filas distribuídas para processamento assíncrono. |
| **PostgreSQL**| Banco de dados relacional para persistência dos dados. |
| **Redis** | Message broker para o Celery e cache. |
| **Docker** | Plataforma de containerização para ambiente e deploy. |
| **Alembic** | Ferramenta para gerenciamento de migrações de schema do DB. |
| **Ollama/Gemini**| Provedores de Large Language Models (LLMs) para a IA. |
| **Pydantic** | Validação de dados e gerenciamento de configurações. |
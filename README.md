# Projeto Vigia

Agente Supervisor de IA para monitoramento e análise de conversas de negociação.

## Descrição

Este projeto implementa um sistema de agentes de IA para monitorar conversas do WhatsApp (via Evolution API), extrair dados, analisar métricas de performance e integrar com o Pipedrive.

## Como Executar (com Docker)

1.  Renomeie `.env.example` para `.env` e preencha as variáveis.
2.  Construa e suba os containers:
    ```bash
    docker-compose up --build
    ```

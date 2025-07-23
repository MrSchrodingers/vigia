# 1. Imagem Base
# Começamos com uma imagem Python oficial, leve e segura.
FROM python:3.10-slim

# 2. Diretório de Trabalho
# Definimos o diretório padrão dentro do container.
WORKDIR /app

# 3. Copiar e Instalar Dependências
# Copiamos apenas o arquivo de dependências primeiro. O Docker armazena
# esta camada em cache. Se o arquivo não mudar, ele não reinstalará tudo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar Código da Aplicação
# Copiamos o script do dashboard para o diretório de trabalho.
COPY dashboard.py .

# 5. Expor a Porta
# Informamos ao Docker que o container escutará na porta 8501.
EXPOSE 8501

# 6. Comando de Execução
# Este é o comando que será executado quando o container iniciar.
# Ele inicia o servidor do Streamlit, permitindo conexões de qualquer endereço.
CMD ["streamlit", "run", "dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
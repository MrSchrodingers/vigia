from bs4 import BeautifulSoup

def clean_html_body(html_string: str) -> str:
    """
    Usa BeautifulSoup para limpar uma string HTML de um corpo de e-mail.
    
    - Remove tags de script e estilo.
    - Extrai apenas o texto visível.
    - Junta as linhas de texto de forma inteligente para preservar a legibilidade.
    
    Returns:
        Uma string com o texto limpo e legível.
    """
    if not html_string:
        return ""

    try:
        soup = BeautifulSoup(html_string, 'html.parser')

        for element in soup(["script", "style"]):
            element.decompose()

        text = soup.get_text(separator=' ', strip=True)
        
        return text
    except Exception as e:
        print(f"Alerta: Falha ao fazer o parsing do HTML. Retornando conteúdo bruto. Erro: {e}")
        return html_string
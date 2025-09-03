import base64
import logging
import os
import json
import pathlib
import random
import redis
import time
import threading
import re
from typing import Any, Dict, Optional, Awaitable, Callable, Tuple
import asyncio

import httpx
from seleniumwire import webdriver
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from .pje_headless_server import run_server

# --- Configuração (sem alterações) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
PJE_PFX_PATH = os.getenv("PJE_PFX")
PJE_PFX_PASS = os.getenv("PJE_PFX_PASS")
PJE_HEADLESS_PORT = int(os.getenv("PJE_HEADLESS_PORT", 8800))

JUSBR_LOGIN_URL = (
    "https://sso.cloud.pje.jus.br/auth/realms/pje/protocol/openid-connect/auth?client_id=jusbr&scope=openid&redirect_uri=https://www.jus.br&response_type=code"
)
JUSBR_CONSULTA_URL = "https://portaldeservicos.pdpj.jus.br/consulta-processual"
JUSBR_API_BASE_URL = "https://portaldeservicos.pdpj.jus.br/api/v2"

def _normalize_numero(n: str) -> str:
    return re.sub(r"\D", "", n or "")

# --- LÓGICA DE CAPTURA DE TOKEN (Simplificada com selenium-wire) ---
def _get_bearer_token() -> str:
    """
    Login SSO -> abrir Consulta Processual -> disparar busca -> interceptar Authorization.
    Salva snapshots de debug em /mnt/data quando há atrasos/falhas.
    """
    def save_debug(tag: str):
        try:
            ts = time.strftime("%Y%m%d-%H%M%S")
            base = f"/mnt/data/debug_{tag}_{ts}"
            pathlib.Path("/mnt/data").mkdir(parents=True, exist_ok=True)
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            driver.save_screenshot(f"{base}.png")
            logging.info(f"[DEBUG] Snapshot salvo: {base}.html / {base}.png  "
                         f"URL={driver.current_url}  TITLE={driver.title!r}  HANDLES={driver.window_handles}")
        except Exception as e:
            logging.warning(f"[DEBUG] Falha ao salvar snapshot ({tag}): {e}")

    def wait_backdrop_gone(timeout=20, tag="backdrop"):
        """Espera sumirem overlays/backdrops que bloqueiam cliques."""
        selectors = [
            ".cdk-overlay-backdrop.cdk-overlay-backdrop-showing",
            ".cdk-overlay-backdrop",               # fallback amplo
            ".ngx-spinner-overlay",                # comum em apps Angular
            ".mat-mdc-dialog-container",           # diálogo aberto
        ]
        end = time.time() + timeout
        while time.time() < end:
            try:
                exists = False
                for sel in selectors:
                    if driver.find_elements(By.CSS_SELECTOR, sel):
                        exists = True
                        break
                if not exists:
                    return
            except Exception:
                return
            time.sleep(0.2)
        save_debug(f"{tag}_timeout")
        logging.info("Backdrop ainda presente após timeout (seguindo mesmo assim).")

    def smart_click(el, name="elemento"):
        """Clica com robustez: scroll + wait + overlay + fallback JS."""
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        try:
            Wait(driver, 6).until(EC.element_to_be_clickable(el))
        except Exception:
            pass
        wait_backdrop_gone(10, tag=f"{name}_pre_click_backdrop")
        try:
            el.click()
        except ElementClickInterceptedException:
            logging.info(f"{name}: clique interceptado; aguardando backdrop e usando JS…")
            wait_backdrop_gone(10, tag=f"{name}_retry_backdrop")
            driver.execute_script("arguments[0].click();", el)

    sw_options = {
        "scopes": [
            r".*jus\.br.*",
            r".*pdpj\.jus\.br.*",
            r".*portaldeservicos\.pdpj\.jus\.br.*",
            r".*sso\.cloud\.pje\.jus\.br.*",
        ],
        "exclude_hosts": [
            "www.google-analytics.com", "www.googletagmanager.com",
            "www.clarity.ms", "q.clarity.ms", "c.clarity.ms",
            "fonts.googleapis.com", "fonts.gstatic.com",
        ],
    }

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options, seleniumwire_options=sw_options)

    def switch_to_new_tab_if_any(before_handles, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            handles = driver.window_handles
            if len(handles) > len(before_handles):
                for h in handles:
                    if h not in before_handles:
                        driver.switch_to.window(h)
                        logging.info("Mudamos para a nova aba/guia.")
                        return True
            time.sleep(0.2)
        return False

    def fechar_modal_silencioso():
        # Banner/modal do jus.br (se houver)
        try:
            entendi = Wait(driver, 5).until(EC.element_to_be_clickable((By.ID, "btn-entendi")))
            smart_click(entendi, "btn-entendi")
            logging.info("Modal de aviso fechado.")
        except Exception:
            try:
                btn = Wait(driver, 2).until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[normalize-space()='Entendi' or contains(., 'Entendi')]")))
                smart_click(btn, "btn-entendi-fallback")
                logging.info("Modal de aviso (fallback) fechado.")
            except Exception:
                logging.info("Nenhum modal de aviso encontrado.")

    def encontrar_link_consulta(timeout=20):
        xpaths = [
            "//a[contains(@href,'portaldeservicos.pdpj.jus.br/consulta')]",
            "//a[contains(@href,'/servico/consulta-processual')]",
            "//a[normalize-space()='Consultar processos' or contains(., 'Consultar processos')]",
        ]
        end = time.time() + timeout
        while time.time() < end:
            for xp in xpaths:
                els = driver.find_elements(By.XPATH, xp)
                vis = [e for e in els if e.is_displayed()]
                if vis:
                    return vis[0]
                if els:
                    return els[0]
            time.sleep(0.3)
        return None

    try:
        # 1) Login no SSO
        logging.info("Iniciando login…")
        driver.get(JUSBR_LOGIN_URL)
        Wait(driver, 60).until(lambda d: d.execute_script("return typeof window.autenticar === 'function'"))
        cert_link = Wait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@onclick, 'autenticar')]"))
        )
        driver.execute_script("arguments[0].click();", cert_link)
        Wait(driver, 90).until(EC.url_contains("www.jus.br"))
        logging.info("Login realizado. Chegamos no portal institucional (www.jus.br).")
        time.sleep(2)

        # 2) Modal e navegação até "Consultar processos"
        fechar_modal_silencioso()
        logging.info("Procurando o link 'Consultar processos'…")
        link = encontrar_link_consulta(timeout=20)

        if link:
            href = (link.get_attribute("href") or "").strip()
            tgt  = (link.get_attribute("target") or "").strip()
            logging.info(f"Link encontrado. href={href} target={tgt!r}. Clicando…")
            before = driver.window_handles[:]
            smart_click(link, "link_consultar_processos")
            opened = switch_to_new_tab_if_any(before, timeout=15)
            if not opened and href:
                if "portaldeservicos.pdpj.jus.br" not in (driver.current_url or ""):
                    logging.info("Nova aba não detectada. Indo pelo href do link…")
                    driver.get(href)
        else:
            logging.info("Link não localizado. Indo direto para a página de consulta…")
            driver.get(JUSBR_CONSULTA_URL)

        # 3) Garantir que estamos no portal
        try:
            Wait(driver, 30).until(EC.url_contains("portaldeservicos.pdpj.jus.br"))
        except TimeoutException:
            save_debug("wait_portal_url")
            driver.get(JUSBR_CONSULTA_URL)
            Wait(driver, 30).until(EC.url_contains("portaldeservicos.pdpj.jus.br"))

        # 4) Aguardar formulário e estabilidade visual (sem backdrop)
        try:
            Wait(driver, 30).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='numeroProcesso']"))
            )
        except TimeoutException:
            save_debug("wait_form")
            raise
        wait_backdrop_gone(15, tag="consulta_form_ready")
        logging.info("Página de consulta carregada.")

        # 5) Limpa requests anteriores e dispara a busca
        try:
            del driver.requests
        except Exception:
            pass

        numero_input = driver.find_element(By.CSS_SELECTOR, "input[formcontrolname='numeroProcesso']")
        buscar_button = driver.find_element(By.XPATH, "//button[contains(., 'Buscar')]")

        numero_input.clear()
        numero_input.send_keys("07108025520188020001")

        # aguarda o botão habilitar (Angular usa atributo 'disabled')
        try:
            Wait(driver, 10).until(lambda d: buscar_button.is_enabled() and not buscar_button.get_attribute("disabled"))
        except TimeoutException:
            logging.info("Botão 'Buscar' aparenta habilitado (ou app não usa atributo 'disabled').")

        smart_click(buscar_button, "btn_buscar")
        logging.info("Busca disparada. Aguardando a chamada da API…")

        # 6) Interceptar a chamada de API e ler Authorization
        try:
            req = driver.wait_for_request(r".*/api/v2/processos/.*", timeout=60)
        except TimeoutException:
            save_debug("wait_api_primary")
            # fallback amplo
            req = driver.wait_for_request(r".*/api/v2/.*processo.*", timeout=30)

        auth_header = (req.headers.get("Authorization")
                       or next((v for k, v in req.headers.items() if k.lower() == "authorization"), "")
                      ).strip()
        if not auth_header:
            save_debug("no_auth_header")
            raise ValueError("API interceptada, mas sem header 'Authorization'.")

        logging.info("✅ SUCESSO! Bearer Token capturado.")
        return auth_header

    finally:
        try:
            save_debug("finally_snapshot")
        except Exception:
            pass
        driver.quit()

# --- Cliente de API e Worker  ---

class PjeApiClient:
    """
    Cliente com renovação automática: ao receber 401, reexecuta a autenticação completa
    (via callable refresh_token) e repete a requisição UMA vez.
    Nunca gera traceback por causa de 401; quem chama decide como lidar.
    """
    def __init__(
        self,
        get_token: Callable[[], Awaitable[str]],
        refresh_token: Callable[[], Awaitable[str]],
    ):
        self._get_token = get_token
        self._refresh_token = refresh_token
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._refresh_lock = asyncio.Lock()

    async def _ensure_client(self) -> None:
        if self._client is None:
            if not self._token:
                self._token = await self._get_token()
            self._client = httpx.AsyncClient(
                base_url=JUSBR_API_BASE_URL,
                headers={"Authorization": self._token, "Accept": "text/plain, */*"},
                timeout=httpx.Timeout(connect=20, read=45, write=20, pool=60),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                http2=True,
            )
    
    async def _extract_text_fallback(self, href_texto: str, resp: httpx.Response) -> str:
        """
        Se /texto não retornou texto, tenta:
        - Se a resposta atual for HTML -> strip de tags
        - Senão, tenta baixar /arquivo (substituindo '/texto' por '/arquivo') e extrair:
            * HTML: strip tags
            * PDF: tenta extrair texto básico se houver (sem OCR); se não houver, reporta mensagem útil
            * DOCX: devolve aviso (ou implemente docx2txt se quiser)
        """
        ctype = (resp.headers.get("content-type") or "").lower()
        content = resp.content or b""

        # 1) Se já veio HTML, limpa e retorna
        if "text/html" in ctype or ("html" in ctype and "text/" in ctype):
            return self._strip_html_to_text(content.decode(errors="replace"))

        # 2) Baixar /arquivo (se existir mapeamento simples)
        arquivo_url = self._build_arquivo_url(href_texto)
        if arquivo_url:
            try:
                bin_resp = await self._request("GET", arquivo_url)
                bin_resp.raise_for_status()
                bin_ctype = (bin_resp.headers.get("content-type") or "").lower()
                bin_data = bin_resp.content or b""

                if "text/html" in bin_ctype or ("html" in bin_ctype and "text/" in bin_ctype):
                    return self._strip_html_to_text(bin_data.decode(errors="replace"))

                if "application/pdf" in bin_ctype or bin_data[:4] == b"%PDF":
                    # Extração básica (sem OCR). Se não houver texto embutido, avisa.
                    txt = self._extract_pdf_basic(bin_data)
                    return txt if txt.strip() else "[PDF sem texto embutido (provável imagem/scan). Precisa de OCR.]"

                if "application/json" in bin_ctype:
                    # às vezes o servidor retorna um JSON de erro/mensagem
                    try:
                        j = bin_resp.json()
                        return json.dumps(j, ensure_ascii=False)
                    except Exception:
                        return bin_data.decode(errors="replace")

                # Outros tipos: devolve um aviso curto
                return f"[Conteúdo binário ({bin_ctype or 'desconhecido'}) sem suporte de extração no worker]"

            except httpx.HTTPError as e:
                return f"[Falha ao baixar /arquivo: {e}]"

        # 3) Sem /arquivo: tenta decodificar algo do próprio resp
        if "application/pdf" in ctype or content[:4] == b"%PDF":
            txt = self._extract_pdf_basic(content)
            return txt if txt.strip() else "[PDF sem texto embutido (provável imagem/scan). Precisa de OCR.]"

        if "application/json" in ctype:
            try:
                j = resp.json()
                return json.dumps(j, ensure_ascii=False)
            except Exception:
                return content.decode(errors="replace")

        # Último fallback
        return content.decode(errors="replace")

    def _build_arquivo_url(self, href_texto: str) -> Optional[str]:
        """
        Mapeia .../documentos/{id}/texto -> .../documentos/{id}/arquivo
        Só retorna algo se identificar claramente o padrão.
        """
        if "/documentos/" in href_texto and "/texto" in href_texto:
            return href_texto.replace("/texto", "/arquivo", 1)
        return None

    def _strip_html_to_text(self, html: str) -> str:
        # Remove scripts/styles e tags básicas sem depender de libs externas
        html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _extract_pdf_basic(self, data: bytes) -> str:
        """
        Extração mínima de texto de PDF sem libs pesadas (não faz milagre).
        Se você puder, instale 'pdfminer.six' ou 'pymupdf' e troque esta função.
        """
        try:
            # Tentativa muito simples: alguns PDFs têm trechos ASCII visíveis;
            # isso NÃO substitui uma lib real de extração.
            sample = data.decode(errors="ignore")
            # Heurística fraca: pega blocos legíveis
            chunks = re.findall(r"[ -~\n\r\t]{50,}", sample)
            return "\n".join(ch.strip() for ch in chunks)
        except Exception:
            return ""
        
    async def _rebuild_client_with_new_token(self) -> None:
        # Evita corrida de múltiplos refreshes
        async with self._refresh_lock:
            new_token = await self._refresh_token()
            # Só reconstrói se mudou ou se não há client
            if new_token != self._token or self._client is None:
                self._token = new_token
                if self._client:
                    await self._client.aclose()
                self._client = httpx.AsyncClient(
                    base_url=JUSBR_API_BASE_URL,
                    headers={"Authorization": self._token},
                    timeout=60.0,
                )

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        await self._ensure_client()
        attempts = 0
        last_exc = None

        # até 5 tentativas para 5xx/timeout
        while attempts < 5:
            try:
                resp = await self._client.request(method, url, **kwargs)

                if resp.status_code == 401:
                    logging.warning("401 recebido. Renovando token e repetindo a requisição…")
                    await self._rebuild_client_with_new_token()
                    resp = await self._client.request(method, url, **kwargs)

                # se 5xx, aplica retry
                if 500 <= resp.status_code < 600:
                    raise httpx.HTTPStatusError(
                        f"server error {resp.status_code}", request=resp.request, response=resp
                    )

                return resp

            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.HTTPStatusError) as e:
                last_exc = e
                attempts += 1

                # Se houver Retry-After, respeita
                retry_after = 0.0
                if isinstance(e, httpx.HTTPStatusError):
                    ra = e.response.headers.get("Retry-After")
                    if ra:
                        try:
                            retry_after = float(ra)
                        except Exception:
                            retry_after = 0.0

                # backoff exponencial com jitter
                base = 0.6 * (2 ** (attempts - 1))
                delay = max(retry_after, base + random.random() * 0.4)
                logging.info(f"Retry {attempts}/5 em {delay:.1f}s para {url} (motivo: {type(e).__name__})")
                await asyncio.sleep(delay)

        # estourou as tentativas
        if last_exc:
            raise last_exc
        raise RuntimeError("Falha desconhecida na requisição")

    async def get_processo_details(self, numero_processo: str) -> Dict[str, Any]:
        numero = _normalize_numero(numero_processo)
        resp = await self._request("GET", f"/processos/{numero}")
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            raise ValueError("API não retornou uma lista de processos válida.")
        return data[0]

    async def get_documento_texto(self, href_texto: str) -> str:
        """
        Tenta pegar o texto já extraído do PDPJ.
        Se o Content-Type não for text/* ou vier vazio, faz fallback para baixar o arquivo e extrair algo útil.
        """
        # Aceita URL absoluta ou relativa
        url = href_texto
        headers = {"Accept": "text/plain, */*"}
        resp = await self._request("GET", url, headers=headers)

        # Se der erro HTTP, levanta aqui
        resp.raise_for_status()

        ctype = (resp.headers.get("content-type") or "").lower()
        clen  = int(resp.headers.get("content-length") or 0)
        if ("text/" in ctype) and resp.content:
            # Texto "de verdade" vindo do endpoint
            return resp.text

        if clen == 0 or not resp.content:
            # Sem conteúdo — tenta alternativo
            raise ValueError("Endpoint /texto sem conteúdo (vazio ou não suportado no servidor).")

        # Não é texto: tenta extrair localmente (HTML/PDF/DOCX etc.)
        return await self._extract_text_fallback(href_texto, resp)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class PjeWorker:
    def __init__(self, cert_path: str, cert_pass: str, headless_port: int):
        self.cert_path = cert_path
        self.cert_pass = cert_pass
        self.headless_port = headless_port
        self.current_token: Optional[str] = None
        self._token_lock = asyncio.Lock()
        self._start_headless_server()

    def _start_headless_server(self):
        logging.info(f"Iniciando servidor headless PJe na porta {self.headless_port} em segundo plano...")
        threading.Thread(target=run_server, args=(self.cert_path, self.cert_pass, self.headless_port), daemon=True).start()
        time.sleep(2)
        logging.info("Servidor headless PJe pronto.")
        
    def refresh_and_store_token(self) -> bool:
        """
        Executa a rotina de login via Selenium e armazena o token no Redis.
        Retorna True em caso de sucesso.
        """
        logging.info("Tentando obter um novo Bearer Token do Jus.br...")
        try:
            # A função _get_bearer_token já está no escopo global deste arquivo
            token = _get_bearer_token()
            if token and token.startswith("Bearer"):
                # Armazena o token no Redis com expiração de 2 horas (7200s)
                self.redis_conn.set("jusbr:bearer_token", token, ex=7200)
                logging.info("Bearer Token atualizado e salvo no Redis com sucesso.")
                return True
            else:
                logging.error("Falha ao obter um Bearer Token válido.")
                self.redis_conn.delete("jusbr:bearer_token")
                return False
        except Exception as e:
            logging.exception(f"Uma exceção ocorreu durante a obtenção do token: {e}")
            self.redis_conn.delete("jusbr:bearer_token")
            return False

    async def _get_token_cached(self) -> str:
        # Primeiro uso: reutiliza se já existe; NÃO reloga à toa
        async with self._token_lock:
            if not self.current_token:
                logging.info("Obtendo Bearer Token inicial via navegação headless…")
                self.current_token = await asyncio.to_thread(_get_bearer_token)
            return self.current_token

    async def _refresh_token_force(self) -> str:
        # Refresh: sempre reexecuta a autenticação completa
        async with self._token_lock:
            logging.info("Reexecutando autenticação completa para renovar o Bearer Token…")
            self.current_token = await asyncio.to_thread(_get_bearer_token)
            return self.current_token

    def _deduz_read_timeout(self, tamanho_texto: int) -> int:
        if tamanho_texto is None:
            return 30
        if tamanho_texto < 3_000:
            return 15
        if tamanho_texto < 30_000:
            return 35
        return 60

    async def get_documento_conteudo_for_doc(self, doc: Dict[str, Any], api_client: PjeApiClient) -> Tuple[str, Optional[bytes]]:
        """
        Busca o conteúdo textual e binário de um documento, com lógica de fallback.

        Retorna:
            Tuple[str, Optional[bytes]]: (conteúdo_texto, conteúdo_binário)
        """
        href_texto = doc.get("hrefTexto")
        href_binario = doc.get("hrefBinario")
        tamanho_arquivo = doc.get("arquivo", {}).get("tamanho")

        texto_final = f"[Texto não pôde ser extraído para o documento: {doc.get('nome')}]"
        binario_final = None

        # --- Etapa 1: Tenta buscar o binário primeiro (fonte da verdade) ---
        if href_binario:
            try:
                timeout = httpx.Timeout(connect=20, read=self._deduz_read_timeout(tamanho_arquivo))
                resp_bin = await api_client._request("GET", href_binario, timeout=timeout)
                resp_bin.raise_for_status()
                binario_final = resp_bin.content
                logging.info(f"Sucesso ao baixar binário de '{doc.get('nome')}' ({len(binario_final) / 1024:.1f} KB).")
                
                # Tenta extrair texto do binário baixado
                texto_extraido = await api_client._extract_text_fallback(href_texto, resp_bin)
                if texto_extraido and not texto_extraido.startswith("["):
                    texto_final = texto_extraido
            except Exception as e:
                logging.warning(f"Falha ao baixar binário de '{doc.get('nome')}': {e}. Tentando /texto como fallback.")
        
        # --- Etapa 2: Se o binário falhou ou não existe, tenta o endpoint de texto ---
        if binario_final is None and href_texto:
            try:
                timeout = httpx.Timeout(connect=20, read=self._deduz_read_timeout(tamanho_arquivo))
                texto_final = await api_client.get_documento_texto(href_texto)
                logging.info(f"Sucesso ao obter texto de '{doc.get('nome')}' via endpoint /texto.")
            except Exception as e:
                logging.error(f"Falha total ao obter conteúdo para '{doc.get('nome')}': {e}")
        
        return texto_final, binario_final
    
    async def get_documento_texto_for_doc(self, doc: Dict[str, Any]) -> str:
        api_client = PjeApiClient(self._get_token_cached, self._refresh_token_force)
        href_texto   = doc.get("hrefTexto")
        href_binario = doc.get("hrefBinario")
        meta         = (doc.get("arquivo") or {})
        tamanho_txt  = meta.get("tamanhoTexto") or 0

        if not href_texto:
            return "[Sem hrefTexto para este documento]"

        # 3.1) tenta /texto com timeout calibrado pelo tamanhoTexto
        per_req_timeout = httpx.Timeout(connect=20, read=self._deduz_read_timeout(tamanho_txt), write=20, pool=60)
        try:
            resp = await api_client._request("GET", href_texto, timeout=per_req_timeout, headers={"Accept": "text/plain, */*"})
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()

            if "text/" in ctype:
                return resp.text

            # às vezes o servidor devolve HTML — limpe tags e siga
            if "html" in ctype:
                return self._strip_html_to_text(resp.text)

            # conteúdo estranho: cai no fallback binário
            logging.info(f"/texto retornou content-type '{ctype}'. Usando fallback binário…")

        except Exception as e:
            logging.warning(f"Falha ao obter /texto de '{doc.get('nome')}': {repr(e)}. Tentando binário…")

        # 3.2) fallback: baixa binário e tenta extrair algo
        if not href_binario:
            return "[/texto falhou e não há hrefBinario para fallback]"

        try:
            # timeouts mais folgados para binários grandes
            per_req_timeout_bin = httpx.Timeout(connect=25, read=90, write=25, pool=60)
            bin_resp = await api_client._request("GET", href_binario, timeout=per_req_timeout_bin)
            bin_resp.raise_for_status()
            bin_ctype = (bin_resp.headers.get("content-type") or "").lower()
            data = bin_resp.content or b""

            if "text/html" in bin_ctype or ("html" in bin_ctype and "text/" in bin_ctype):
                return self._strip_html_to_text(data.decode(errors="replace"))

            if "application/pdf" in bin_ctype or data[:4] == b"%PDF":
                txt = self._extract_pdf_basic(data)
                return txt if txt.strip() else "[PDF sem texto embutido (provável imagem/scan).]"

            if "application/json" in bin_ctype:
                try:
                    return json.dumps(bin_resp.json(), ensure_ascii=False)
                except Exception:
                    return data.decode(errors="replace")

            # outros tipos: devolve um pingado útil
            return f"[Conteúdo binário {bin_ctype or 'desconhecido'} sem extrator configurado]"
        except Exception as e:
            return f"[Falha no fallback binário: {e}]"

    def _strip_html_to_text(self, html: str) -> str:
        html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _extract_pdf_basic(self, data: bytes) -> str:
        # Extração bem simples sem OCR (suficiente para muitos PDFs textos)
        try:
            sample = data.decode(errors="ignore")
            chunks = re.findall(r"[ -~\n\r\t]{50,}", sample)
            return "\n".join(ch.strip() for ch in chunks)
        except Exception:
            return ""
    
    async def process_task(self, numero_processo: str) -> Dict[str, Any]:
        async def get_token_from_redis() -> str:
            token = self.redis_conn.get("jusbr:bearer_token")
            if not token:
                logging.warning("Token não encontrado no Redis. Tentando um refresh forçado.")
                if self.refresh_and_store_token():
                    token = self.redis_conn.get("jusbr:bearer_token")
                else:
                    raise RuntimeError("Falha ao obter token mesmo após refresh.")
            return token.decode('utf-8')

        async def refresh_token_via_worker() -> str:
            logging.info("Token expirado (401). Forçando refresh completo.")
            if self.refresh_and_store_token():
                token = self.redis_conn.get("jusbr:bearer_token")
                if token:
                    return token.decode('utf-8')
            raise RuntimeError("Não foi possível renovar o token após expirar.")
        
        api_client = PjeApiClient(get_token_from_redis, refresh_token_via_worker)
        try:
            logging.info(f"Buscando detalhes do processo {numero_processo} via API.")
            processo_details = await api_client.get_processo_details(numero_processo)

            documentos = (processo_details.get("tramitacaoAtual") or {}).get("documentos", []) or []
            
            # Limita o número de documentos para evitar sobrecarga
            subset_docs = sorted(documentos, key=lambda d: d.get('dataHoraJuntada'), reverse=True)[:30]
            logging.info(f"Processando os {len(subset_docs)} documentos mais recentes...")

            sem = asyncio.Semaphore(5) # Limita a concorrência para não sobrecarregar a API

            async def _fetch_one(doc: Dict[str, Any]) -> Dict[str, Any]:
                async with sem:
                    try:
                        texto, binario = await self.get_documento_conteudo_for_doc(doc, api_client)
                        return {
                            "external_id": doc.get("idOrigem") or doc.get("idCodex"),
                            "name": doc.get("nome"),
                            "document_type": (doc.get("tipo") or {}).get("nome"),
                            "juntada_date": doc.get("dataHoraJuntada"),
                            "text_content": texto,
                            "binary_content_b64": base64.b64encode(binario).decode('utf-8') if binario else None,
                            "file_type": doc.get("arquivo", {}).get("tipo"),
                            "file_size": doc.get("arquivo", {}).get("tamanho")
                        }
                    except Exception as e:
                        logging.warning(f"Falha ao buscar conteúdo do doc '{doc.get('nome')}': {repr(e)}")
                        return {"name": doc.get("nome"), "error": str(e)}

            tasks = [_fetch_one(doc) for doc in subset_docs]
            documentos_com_conteudo = await asyncio.gather(*tasks)
            
            # Adiciona o novo campo ao JSON que será retornado
            processo_details["documentos_com_conteudo"] = documentos_com_conteudo
            
            return processo_details

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else "?"
            logging.error(f"HTTP {status} ao consultar {numero_processo}: {e}", exc_info=False)
            return {"erro": f"HTTP {status} ao consultar o processo."}
        except Exception as e:
            logging.error(f"Erro inesperado ao processar {numero_processo}: {e}", exc_info=False)
            return {"erro": str(e)}
        finally:
            await api_client.close()


async def main_loop():
    logging.info("PJE Worker (Modo Otimizado com selenium-wire) iniciado. Aguardando tarefas...")
    redis_conn = redis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}/0", decode_responses=True)
    worker = PjeWorker(cert_path=PJE_PFX_PATH, cert_pass=PJE_PFX_PASS, headless_port=PJE_HEADLESS_PORT)

    while True:
        try:
            _, task_payload_str = redis_conn.blpop("jusbr_work_queue")
            task_payload = json.loads(task_payload_str)
            numero_processo, result_key = task_payload["numero_processo"], task_payload["result_key"]
            logging.info(f"Nova tarefa recebida: Processo {numero_processo}")

            result_data = await worker.process_task(numero_processo)
            redis_conn.lpush(result_key, json.dumps(result_data, ensure_ascii=False))

        except redis.exceptions.ConnectionError as e:
            logging.error(f"Erro de conexão com o Redis: {e}. Reconectando em 10s...", exc_info=False)
            time.sleep(10)

        except Exception as e:
            # Sem traceback aqui também
            logging.error(f"Erro inesperado no loop principal: {e}", exc_info=False)
            time.sleep(5)


if __name__ == "__main__":
    asyncio.run(main_loop())
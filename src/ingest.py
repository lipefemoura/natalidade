"""Coleta, por município do Maranhão, os nascidos vivos registrados (IBGE/SIDRA, tabela 2609)
e a população residente estimada (IBGE/Agregados, tabela 6579)."""

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests


# ============================================================
# CONFIGURAÇÕES
# ============================================================

UF_CODIGO = "21"  # Maranhão
ANO_INICIAL = 2003  # primeiro ano da tabela 2609
ANO_FINAL = 2024

FONTE = "IBGE/SIDRA - Tabela 2609 (Estatísticas do Registro Civil)"
URL_BASE = "https://apisidra.ibge.gov.br/values"
DIR_RAW = Path("data/raw/ibge_sidra_2609")

FONTE_POPULACAO = "IBGE/Agregados v3 - Tabela 6579 (População residente estimada)"
URL_POPULACAO = "https://servicodados.ibge.gov.br/api/v3/agregados/6579"
DIR_RAW_POPULACAO = Path("data/raw/ibge_agregados_6579")
# A tabela 6579 não publica estimativa nesses anos (anos de censo, de contagem e 2023)
ANOS_SEM_ESTIMATIVA = (2007, 2010, 2022, 2023)
ANOS_POPULACAO = tuple(
    ano for ano in range(ANO_INICIAL, ANO_FINAL + 1) if ano not in ANOS_SEM_ESTIMATIVA
)

MAX_TENTATIVAS = 4
TIMEOUT = 120
PAUSA_ENTRE_ANOS = 1
HEADERS = {"User-Agent": "natalidade-ICD-IFMA/0.1 (projeto academico)"}


# ============================================================
# CONSULTA
# ============================================================

def montar_url(ano: int) -> str:
    """Monta a URL de consulta de um ano.

    Trechos da URL:
        t/2609          tabela 2609 (Estatísticas do Registro Civil)
        n6/in n3 21     municípios (n6) da UF 21 (Maranhão)
        p/{ano}         ano consultado
        v/217           nascidos vivos registrados no ano
        c2/0            sexo: total
        c232/0          ano de nascimento: total
        c240/all        idade da mãe: todas as categorias

    Os parâmetros ficam no caminho da URL porque o SIDRA ignora, sem erro,
    parâmetros enviados na query string (?c240=all).

    É feita uma chamada por ano porque a API recusa pedidos acima de
    50.000 valores, e um ano do Maranhão tem cerca de 10 mil.
    """
    return (
        f"{URL_BASE}/t/2609/n6/in%20n3%20{UF_CODIGO}/p/{ano}"
        f"/v/217/c2/0/c232/0/c240/all"
    )


def montar_url_populacao() -> str:
    """Monta a URL da população de todos os anos publicados, numa só consulta.

    Trechos da URL:
        periodos/2003|2004|...   anos com estimativa publicada
        variaveis/9324           população residente estimada (pessoas)
        localidades=N6[N3[21]]   municípios (N6) da UF 21 (Maranhão)

    São 217 municípios × 18 anos = 3.906 valores, abaixo do limite da API.
    """
    anos = "%7C".join(map(str, ANOS_POPULACAO))
    return (
        f"{URL_POPULACAO}/periodos/{anos}/variaveis/9324"
        f"?localidades=N6%5BN3%5B{UF_CODIGO}%5D%5D"
    )


def segundos_retry_after(resposta: requests.Response, padrao: int) -> int:
    """Retorna o Retry-After em segundos, ou o padrão se ausente ou em formato de data."""
    valor = resposta.headers.get("Retry-After", "")
    return int(valor) if valor.isdigit() else padrao


def requisitar(url: str) -> list[dict]:
    """Executa a requisição com tratamento diferenciado de erros.

    401/403 e demais 4xx: encerram sem nova tentativa.
    429, 5xx e falhas de rede: nova tentativa com backoff exponencial.
    """
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        espera = 2 ** tentativa  # 2, 4, 8 s

        try:
            resposta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as erro:
            motivo = f"falha de rede ({type(erro).__name__})"
        else:
            status = resposta.status_code

            if status == 200:
                try:
                    return resposta.json()
                except requests.JSONDecodeError as erro:
                    raise RuntimeError(
                        f"Resposta 200 sem JSON válido: {resposta.text[:200]}"
                    ) from erro

            if status in (401, 403):
                raise PermissionError(
                    f"Acesso negado ({status}). O SIDRA não usa chave, então o "
                    f"provável motivo é bloqueio da Cloudflare: repetir agora não resolve."
                )

            if status == 429:
                motivo = "limite de requisições (429)"
                espera = segundos_retry_after(resposta, espera)
            elif status >= 500:
                motivo = f"erro do servidor ({status})"
            else:
                raise ValueError(f"Consulta recusada ({status}): {resposta.text[:200]}")

        if tentativa == MAX_TENTATIVAS:
            break
        print(f"    {motivo}; tentativa {tentativa}/{MAX_TENTATIVAS}, aguardando {espera}s...")
        time.sleep(espera)

    raise RuntimeError(f"Desisti após {MAX_TENTATIVAS} tentativas ({motivo}): {url}")


def validar(dados: list, ano: int) -> int:
    """Valida a resposta e retorna o número de registros.

    A API responde 200 com apenas o cabeçalho quando o período não tem dados.
    """
    if not isinstance(dados, list) or not dados:
        raise RuntimeError(f"Ano {ano}: resposta em formato inesperado.")

    registros = len(dados) - 1  # o primeiro item é o cabeçalho
    if registros == 0:
        raise RuntimeError(f"Ano {ano}: a API devolveu só o cabeçalho, sem registros.")
    return registros


def validar_populacao(dados: list) -> int:
    """Valida a resposta da população e retorna o número de valores (município × ano)."""
    try:
        series = dados[0]["resultados"][0]["series"]
    except (TypeError, KeyError, IndexError) as erro:
        raise RuntimeError("População: resposta em formato inesperado.") from erro

    valores = sum(len(item["serie"]) for item in series)
    if valores == 0:
        raise RuntimeError("População: a API não devolveu nenhum valor.")
    return valores


# ============================================================
# SALVAMENTO
# ============================================================

def salvar(envelope: dict, destino: Path) -> None:

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporario.replace(destino)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    pasta = DIR_RAW / date.today().isoformat()
    total, baixados = 0, 0

    print(f"{FONTE}, UF {UF_CODIGO}, {ANO_INICIAL} a {ANO_FINAL}")

    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        destino = pasta / f"uf{UF_CODIGO}_{ano}.json"

        if destino.exists():  # idempotência
            registros = json.loads(destino.read_text(encoding="utf-8"))["registros"]
            print(f"  {ano}: já coletado hoje ({registros} registros)")
            total += registros
            continue

        url = montar_url(ano)
        dados = requisitar(url)
        registros = validar(dados, ano)

        salvar(
            {
                "fonte": FONTE,
                "url": url,
                "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "registros": registros,
                "dado": dados,  # resposta original da API
            },
            destino,
        )
        print(f"  {ano}: {registros} registros")
        total += registros
        baixados += 1
        time.sleep(PAUSA_ENTRE_ANOS)

    anos = ANO_FINAL - ANO_INICIAL + 1
    print(f"\n{total} registros de {anos} anos ({baixados} baixados agora) em {pasta}")

    coletar_populacao()


def coletar_populacao() -> None:
    """Coleta a população e os metadados da tabela 6579, que o transform.py confere.

    Os metadados dizem a unidade, o nível territorial e os anos publicados: se a
    tabela mudar, o transform.py para em vez de usar um dado com outro significado.
    """
    pasta = DIR_RAW_POPULACAO / date.today().isoformat()
    consultas = {
        "metadados": f"{URL_POPULACAO}/metadados",
        "periodos": f"{URL_POPULACAO}/periodos",
        "populacao": montar_url_populacao(),
    }

    print(f"\n{FONTE_POPULACAO}, UF {UF_CODIGO}, {len(ANOS_POPULACAO)} anos")

    for nome, url in consultas.items():
        destino = pasta / f"{nome}.json"

        if destino.exists():  # idempotência
            print(f"  {nome}: já coletado hoje")
            continue

        dados = requisitar(url)
        envelope = {
            "fonte": FONTE_POPULACAO,
            "url": url,
            "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dado": dados,  # resposta original da API
        }
        if nome == "populacao":
            envelope["registros"] = validar_populacao(dados)
        salvar(envelope, destino)
        detalhe = f" ({envelope['registros']} valores)" if nome == "populacao" else ""
        print(f"  {nome}: coletado{detalhe}")
        time.sleep(PAUSA_ENTRE_ANOS)

    print(f"população em {pasta}")


if __name__ == "__main__":
    main()
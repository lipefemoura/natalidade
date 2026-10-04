import json
import os
from datetime import date
from pathlib import Path
from time import sleep

import requests
from dotenv import load_dotenv


load_dotenv()

# ============================================================
# CONFIGURAÇÕES
# ============================================================

UF_CODIGO = os.environ.get("UF_CODIGO", "21")

ANO_INICIAL = 2003
ANO_FINAL = 2024

TABELA = "2609"
VARIAVEL = "217"

URL_BASE = "https://apisidra.ibge.gov.br/values"

# Consulta:
# n6 = municípios
# all = todos os municípios
# p = período
# v = variável
# c = classificações
#
# D4 = sexo
# D5 = ano de nascimento
# D6 = idade da mãe

DADOS_RAW = Path("data/raw/ibge_nascimentos")


# ============================================================
# FUNÇÃO DE CONSULTA
# ============================================================

def buscar_dados(ano: int) -> list:
    """Consulta os dados da Tabela 2609 para um determinado ano."""

    url = f"{URL_BASE}/t/{TABELA}/n6/all/p/{ano}"

    params = {
        "v": VARIAVEL,
        "c782": "0",
        "c783": "0",
        "c784": "all",
    }

    for tentativa in range(1, 4):
        try:
            resposta = requests.get(
                url,
                params=params,
                timeout=120,
            )

            if resposta.status_code == 429:
                espera = tentativa * 5
                print(
                    f"IBGE retornou 429 (muitas requisições). "
                    f"Aguardando {espera}s..."
                )
                sleep(espera)
                continue

            if resposta.status_code >= 500:
                espera = tentativa * 5
                print(
                    f"Servidor do IBGE retornou {resposta.status_code}. "
                    f"Tentativa {tentativa}/3..."
                )

                if tentativa < 3:
                    sleep(espera)
                    continue

            resposta.raise_for_status()

            dados = resposta.json()

            if not isinstance(dados, list):
                raise RuntimeError(
                    f"Resposta inesperada da API para o ano {ano}."
                )

            return dados

        except requests.RequestException as erro:
            if tentativa < 3:
                espera = tentativa * 5
                print(
                    f"Erro de conexão para {ano}. "
                    f"Tentando novamente em {espera}s..."
                )
                sleep(espera)
            else:
                raise RuntimeError(
                    f"Não foi possível consultar o IBGE para o ano {ano}."
                ) from erro

    raise RuntimeError(
        f"Não foi possível consultar o IBGE para o ano {ano}."
    )


# ============================================================
# FILTRO DOS MUNICÍPIOS DO MARANHÃO
# ============================================================

def filtrar_maranhao(dados: list) -> list:
    """
    Mantém somente os municípios do Maranhão.

    Os códigos IBGE dos municípios do Maranhão começam com 21.
    """

    if not dados:
        return []

    cabecalho = dados[0]

    registros = []

    for registro in dados[1:]:
        codigo_municipio = registro.get("D1C", "")

        if codigo_municipio.startswith(UF_CODIGO):
            registros.append(registro)

    return [cabecalho] + registros


# ============================================================
# SALVAMENTO
# ============================================================

def salvar_dados(dados_por_ano: dict) -> Path:
    """Salva a resposta bruta da API em JSON."""

    hoje = date.today().isoformat()

    pasta_saida = DADOS_RAW / hoje
    pasta_saida.mkdir(parents=True, exist_ok=True)

    arquivo_saida = (
        pasta_saida
        / f"nascimentos_tabela{TABELA}_uf{UF_CODIGO}.json"
    )

    with arquivo_saida.open(
        "w",
        encoding="utf-8",
    ) as arquivo:
        json.dump(
            dados_por_ano,
            arquivo,
            ensure_ascii=False,
            indent=2,
        )

    return arquivo_saida


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    print("=" * 60)
    print("COLETA DE NASCIDOS VIVOS - IBGE/SIDRA")
    print("=" * 60)
    print(f"UF: {UF_CODIGO} - Maranhão")
    print(f"Anos: {ANO_INICIAL} a {ANO_FINAL}")
    print(f"Tabela: {TABELA}")
    print(f"Variável: {VARIAVEL} - Nascidos vivos registrados no ano")
    print("Nível territorial: Município")
    print("Idade da mãe: todas as categorias")
    print("=" * 60)
    print()

    dados_por_ano = {}

    anos = range(ANO_INICIAL, ANO_FINAL + 1)
    total_anos = len(list(anos))

    for indice, ano in enumerate(anos, start=1):
        print(
            f"[{indice}/{total_anos}] "
            f"Coletando ano {ano}..."
        )

        dados = buscar_dados(ano)

        dados_ma = filtrar_maranhao(dados)

        quantidade = len(dados_ma) - 1

        print(
            f"  ✓ Registros encontrados para o Maranhão: "
            f"{quantidade}"
        )

        dados_por_ano[str(ano)] = dados_ma

        # Pequena pausa para evitar excesso de requisições
        if ano != ANO_FINAL:
            sleep(1)

    arquivo = salvar_dados(dados_por_ano)

    print()
    print("=" * 60)
    print("COLETA CONCLUÍDA")
    print("=" * 60)
    print(f"Arquivo salvo em:")
    print(arquivo)
    print("=" * 60)


if __name__ == "__main__":
    main()
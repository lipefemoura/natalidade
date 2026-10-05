"""Transformação e validação dos dados da Tabela 2609 do IBGE/SIDRA."""

import json
from pathlib import Path

import pandas as pd
import pandera.pandas as pa


# ============================================================
# CONFIGURAÇÕES
# ============================================================

DIR_RAW = Path("data/raw/ibge_sidra_2609")
DIR_TRUSTED = Path("data/trusted")
DIR_QUARENTENA = Path("data/quarentena")

ARQUIVO_TRUSTED = DIR_TRUSTED / "nascimentos.parquet"
ARQUIVO_QUARENTENA = DIR_QUARENTENA / "rejeitados.parquet"

FAIXAS_IDADE = {
    "Menos de 15 anos",
    "15 a 19 anos",
    "20 a 24 anos",
    "25 a 29 anos",
    "30 a 34 anos",
    "35 a 39 anos",
    "40 a 44 anos",
    "45 a 49 anos",
    "50 anos ou mais",
    "Ignorada",
}


# ============================================================
# LEITURA
# ============================================================

def localizar_arquivos() -> list[Path]:
    """Localiza os arquivos JSON da camada raw."""

    arquivos = sorted(
        DIR_RAW.glob("**/uf21_*.json")
    )

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo encontrado em: {DIR_RAW}"
        )

    return arquivos


def carregar_dados() -> pd.DataFrame:
    """Carrega os registros dos envelopes JSON."""

    registros = []

    arquivos = localizar_arquivos()

    for arquivo in arquivos:
        print(f"Lendo: {arquivo}")

        with arquivo.open(
            "r",
            encoding="utf-8",
        ) as f:
            envelope = json.load(f)

        dados = envelope.get("dado", [])

        if not isinstance(dados, list) or len(dados) < 2:
            raise RuntimeError(
                f"Arquivo sem registros válidos: {arquivo}"
            )

        # O primeiro item é o cabeçalho do SIDRA.
        registros.extend(dados[1:])

    print(
        f"  Registros carregados: {len(registros)}"
    )

    return pd.DataFrame(registros)


# ============================================================
# HIGIENIZAÇÃO
# ============================================================

def higienizar(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Padroniza os campos necessários para a análise."""

    resultado = pd.DataFrame()

    resultado["codigo_municipio"] = (
        df["D1C"]
        .astype(str)
        .str.strip()
    )

    resultado["nome_municipio"] = (
        df["D1N"]
        .astype(str)
        .str.strip()
    )

    resultado["ano"] = pd.to_numeric(
        df["D2C"],
        errors="coerce",
    )

    resultado["variavel_codigo"] = (
        df["D3C"]
        .astype(str)
        .str.strip()
    )

    resultado["variavel"] = (
        df["D3N"]
        .astype(str)
        .str.strip()
    )

    resultado["sexo"] = (
        df["D4N"]
        .astype(str)
        .str.strip()
    )

    resultado["ano_nascimento"] = (
        df["D5N"]
        .astype(str)
        .str.strip()
    )

    resultado["faixa_idade_mae"] = (
        df["D6N"]
        .astype(str)
        .str.strip()
    )

    resultado["codigo_idade_mae"] = (
        df["D6C"]
        .astype(str)
        .str.strip()
    )

    resultado["valor_bruto"] = (
        df["V"]
        .astype(str)
        .str.strip()
    )

    return resultado


# ============================================================
# VALIDAÇÃO
# ============================================================

def validar_categorias_idade(
    df: pd.DataFrame,
) -> None:
    """Verifica se a dimensão de idade materna foi coletada."""

    categorias = sorted(
        df["faixa_idade_mae"]
        .dropna()
        .unique()
        .tolist()
    )

    print(
        "\nCategorias de idade materna encontradas:"
    )

    for categoria in categorias:
        print(f"  - {categoria}")

    if categorias == ["Total"]:
        raise RuntimeError(
            "A coleta contém somente a categoria 'Total' "
            "para idade da mãe.\n\n"
            "A pergunta analítica exige a comparação por "
            "faixa etária da mãe.\n\n"
            "A coleta deve ser corrigida antes de gerar "
            "a camada trusted."
        )


def validar_schema(
    df: pd.DataFrame,
) -> None:
    """Valida a estrutura e os tipos dos dados."""

    schema = pa.DataFrameSchema(
        {
            "codigo_municipio": pa.Column(
                str,
                nullable=False,
            ),
            "nome_municipio": pa.Column(
                str,
                nullable=False,
            ),
            "ano": pa.Column(
                int,
                nullable=False,
            ),
            "variavel_codigo": pa.Column(
                str,
                nullable=False,
            ),
            "variavel": pa.Column(
                str,
                nullable=False,
            ),
            "sexo": pa.Column(
                str,
                nullable=False,
            ),
            "ano_nascimento": pa.Column(
                str,
                nullable=False,
            ),
            "faixa_idade_mae": pa.Column(
                str,
                nullable=False,
            ),
            "codigo_idade_mae": pa.Column(
                str,
                nullable=False,
            ),
            "valor_bruto": pa.Column(
                str,
                nullable=False,
            ),
        },
        strict=True,
    )

    schema.validate(df)


# ============================================================
# REGRAS DE NEGÓCIO
# ============================================================

def aplicar_regras(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Aplica as regras de qualidade.

    Os registros válidos para o recorte analítico seguem
    para trusted.

    Registros com problemas de qualidade são enviados
    para quarentena.

    Categorias de idade individual e "Total" são válidas
    no SIDRA, mas ficam fora do escopo desta análise.
    """

    trabalho = df.copy()

    # --------------------------------------------------------
    # 1. Município
    # --------------------------------------------------------

    mascara_municipio = trabalho[
        "codigo_municipio"
    ].str.match(
        r"^21\d{5}$",
        na=False,
    )

    rejeitados_municipio = trabalho.loc[
        ~mascara_municipio
    ].copy()

    trabalho = trabalho.loc[
        mascara_municipio
    ].copy()

    # --------------------------------------------------------
    # 2. Ano
    # --------------------------------------------------------

    mascara_ano = trabalho["ano"].between(
        2003,
        2024,
    )

    rejeitados_ano = trabalho.loc[
        ~mascara_ano
    ].copy()

    trabalho = trabalho.loc[
        mascara_ano
    ].copy()

    # --------------------------------------------------------
    # 3. Variável
    # --------------------------------------------------------

    mascara_variavel = (
        trabalho["variavel_codigo"] == "217"
    )

    rejeitados_variavel = trabalho.loc[
        ~mascara_variavel
    ].copy()

    trabalho = trabalho.loc[
        mascara_variavel
    ].copy()

    # --------------------------------------------------------
    # 4. Sexo e ano de nascimento
    # --------------------------------------------------------

    mascara_total = (
        (trabalho["sexo"] == "Total")
        & (trabalho["ano_nascimento"] == "Total")
    )

    rejeitados_total = trabalho.loc[
        ~mascara_total
    ].copy()

    trabalho = trabalho.loc[
        mascara_total
    ].copy()

    # --------------------------------------------------------
    # 5. Idade materna
    # --------------------------------------------------------

    # O IBGE disponibiliza faixas agregadas, idades
    # individuais e o total geral.
    #
    # Para esta análise, utilizamos somente as 10
    # categorias agregadas definidas no recorte analítico.
    #
    # As idades individuais e "Total" são dados válidos,
    # porém ficam fora do escopo da análise.

    mascara_idade = trabalho[
        "faixa_idade_mae"
    ].isin(
        FAIXAS_IDADE
    )

    trabalho = trabalho.loc[
        mascara_idade
    ].copy()

    # --------------------------------------------------------
    # 6. Valores
    # --------------------------------------------------------

    # Segundo a convenção do SIDRA, "-" representa
    # zero absoluto.
    #
    # Portanto, a conversão para 0 não é uma imputação.
    # É a transformação da representação textual oficial
    # para formato numérico.

    trabalho["valor_bruto"] = trabalho[
        "valor_bruto"
    ].replace(
        {
            "-": "0",
        }
    )

    valor_numerico = pd.to_numeric(
        trabalho["valor_bruto"],
        errors="coerce",
    )

    mascara_valor = valor_numerico.notna()

    rejeitados_valor = trabalho.loc[
        ~mascara_valor
    ].copy()

    trabalho = trabalho.loc[
        mascara_valor
    ].copy()

    trabalho["valor"] = valor_numerico.loc[
        trabalho.index
    ].astype("int64")

    # --------------------------------------------------------
    # 7. Duplicidades
    # --------------------------------------------------------

    chaves = [
        "codigo_municipio",
        "ano",
        "faixa_idade_mae",
    ]

    duplicados = trabalho[
        trabalho.duplicated(
            subset=chaves,
            keep=False,
        )
    ].copy()

    trabalho = trabalho.drop_duplicates(
        subset=chaves,
        keep="first",
    )

    # --------------------------------------------------------
    # Quarentena
    # --------------------------------------------------------

    rejeitados = pd.concat(
        [
            rejeitados_municipio,
            rejeitados_ano,
            rejeitados_variavel,
            rejeitados_total,
            rejeitados_valor,
            duplicados,
        ],
        ignore_index=True,
    )

    return trabalho, rejeitados


# ============================================================
# SALVAMENTO
# ============================================================

def salvar(
    trusted: pd.DataFrame,
    rejeitados: pd.DataFrame,
) -> None:
    """Salva as camadas trusted e quarentena."""

    DIR_TRUSTED.mkdir(
        parents=True,
        exist_ok=True,
    )

    DIR_QUARENTENA.mkdir(
        parents=True,
        exist_ok=True,
    )

    trusted.to_parquet(
        ARQUIVO_TRUSTED,
        index=False,
    )

    rejeitados.to_parquet(
        ARQUIVO_QUARENTENA,
        index=False,
    )


# ============================================================
# EXECUÇÃO
# ============================================================

def main() -> None:

    print("=" * 70)
    print(
        "TRANSFORMAÇÃO DOS DADOS DE NASCIMENTOS - IBGE/SIDRA"
    )
    print("=" * 70)

    print("\n[1/5] Carregando dados brutos...")

    df_raw = carregar_dados()

    print("\n[2/5] Higienizando dados...")

    df = higienizar(df_raw)

    print(
        "\n[3/5] Verificando categorias de idade..."
    )

    validar_categorias_idade(df)

    print("\n[4/5] Validando schema...")

    validar_schema(df)

    print(
        "\n[5/5] Aplicando regras de qualidade..."
    )

    trusted, rejeitados = aplicar_regras(df)

    print()
    print(
        f"Registros trusted: {len(trusted)}"
    )
    print(
        f"Registros em quarentena: {len(rejeitados)}"
    )

    salvar(
        trusted,
        rejeitados,
    )

    print()
    print("=" * 70)
    print("TRANSFORMAÇÃO CONCLUÍDA")
    print("=" * 70)
    print(
        f"Trusted: {ARQUIVO_TRUSTED}"
    )
    print(
        f"Quarentena: {ARQUIVO_QUARENTENA}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
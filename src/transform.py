"""Leva os nascidos vivos registrados de data/raw/ para data/trusted/, validando na fronteira."""

import json
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema


# ============================================================
# CONFIGURAÇÕES
# ============================================================

DIR_RAW = Path("data/raw/ibge_sidra_2609")
TRUSTED = Path("data/trusted/nascimentos.parquet")
QUARENTENA = Path("data/quarentena/rejeitados.parquet")

# Nove faixas de idade e a idade ignorada: juntas, cobrem todos os nascimentos sem repetição
FAIXAS = [
    "Menos de 15 anos", "15 a 19 anos", "20 a 24 anos", "25 a 29 anos", "30 a 34 anos",
    "35 a 39 anos", "40 a 44 anos", "45 a 49 anos", "50 anos ou mais", "Ignorada",
]

COLUNAS = [
    "cod_municipio", "municipio", "ano", "faixa_idade_mae",
    "nascidos", "valor_era_traco", "total_municipio_ano",
]
CHAVE = ["cod_municipio", "ano", "faixa_idade_mae"]

# Participação no total do estado, comparada com a participação mediana do município
LIMITE_BAIXO, LIMITE_ALTO = 0.25, 3


# ============================================================
# CONTRATO
# ============================================================

CONTRATO = DataFrameSchema(
    columns={
        "cod_municipio": Column(
            str, Check.str_matches(r"^21\d{5}$", error="municipio_fora_do_maranhao"), nullable=False
        ),
        "municipio": Column(
            str, Check.str_length(min_value=1, error="municipio_sem_nome"), nullable=False
        ),
        "ano": Column(
            int, Check.in_range(2003, 2024, error="ano_fora_da_janela"), nullable=False
        ),
        "faixa_idade_mae": Column(
            str, Check.isin(FAIXAS, error="faixa_fora_do_dominio"), nullable=False
        ),
        "nascidos": Column(
            int, Check.greater_than_or_equal_to(0, error="nascidos_negativo"), nullable=False
        ),
        "valor_era_traco": Column(bool, nullable=False),
        "total_municipio_ano": Column(
            int, Check.greater_than_or_equal_to(0, error="total_negativo"), nullable=False
        ),
    },
    checks=[
        Check(
            lambda df: df["nascidos"] <= df["total_municipio_ano"],
            error="faixa_maior_que_total",
        ),
        Check(
            lambda df: df.groupby(["cod_municipio", "ano"])["nascidos"].transform("sum")
            == df["total_municipio_ano"],
            error="soma_das_faixas_difere_do_total",
        ),
        Check(
            lambda df: ~df["valor_era_traco"] | (df["nascidos"] == 0),
            error="traco_com_valor_diferente_de_zero",
        ),
    ],
    unique=CHAVE,
    coerce=True,
    strict=True,
)


# ============================================================
# ETAPAS
# ============================================================

def carregar(diretorio: Path) -> pd.DataFrame:
    """Lê os JSON da coleta mais recente e remove as linhas repetidas na íntegra."""
    coleta = max(p for p in diretorio.iterdir() if p.is_dir())
    arquivos = sorted(coleta.glob("uf21_*.json"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo de coleta em {coleta}")

    registros = []
    for arquivo in arquivos:
        envelope = json.loads(arquivo.read_text(encoding="utf-8"))
        registros.extend(envelope["dado"][1:])  # o primeiro item é o cabeçalho da API

    print(f"coleta: {coleta.name} | {len(arquivos)} arquivos | {len(registros)} registros")
    return pd.DataFrame(registros).drop_duplicates().reset_index(drop=True)


def higienizar(df: pd.DataFrame) -> pd.DataFrame:
    """Nomes legíveis, '-' como zero (com indicadora), números como inteiros, nome sem a UF."""
    simbolos = set(df.loc[~df["V"].str.fullmatch(r"\d+"), "V"]) - {"-"}
    if simbolos:
        raise ValueError(f"Símbolos desconhecidos em valor: {sorted(simbolos)}")

    return pd.DataFrame({
        "cod_municipio": df["D1C"],
        "municipio": df["D1N"].str.removesuffix(" - MA"),
        "ano": df["D2C"].astype(int),
        "idade_mae": df["D6N"],
        "nascidos": df["V"].replace("-", "0").astype(int),
        "valor_era_traco": df["V"] == "-",
    })


def tratar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mantém as dez faixas com o total do município e separa os municípios e anos atípicos.

    Devolve (tratado, quarentena dos atípicos).
    """
    total = (
        df.loc[df["idade_mae"] == "Total", ["cod_municipio", "ano", "nascidos"]]
        .rename(columns={"nascidos": "total_municipio_ano"})
    )
    faixas = (
        df[df["idade_mae"].isin(FAIXAS)]
        .rename(columns={"idade_mae": "faixa_idade_mae"})
        .merge(total, on=["cod_municipio", "ano"], how="left", validate="many_to_one")
    )[COLUNAS]

    pares = faixas.drop_duplicates(["cod_municipio", "ano"])[["cod_municipio", "ano", "total_municipio_ano"]]
    participacao = pares["total_municipio_ano"] / pares.groupby("ano")["total_municipio_ano"].transform("sum")
    razao = participacao / participacao.groupby(pares["cod_municipio"]).transform("median")
    atipicos = pares.loc[(razao < LIMITE_BAIXO) | (razao > LIMITE_ALTO), ["cod_municipio", "ano"]]

    marcado = faixas.merge(atipicos, on=["cod_municipio", "ano"], how="left", indicator=True)
    em_quarentena = marcado["_merge"] == "both"
    marcado = marcado.drop(columns="_merge")

    quarentena = marcado[em_quarentena].assign(motivo="participacao_atipica_no_municipio")
    tratado = marcado[~em_quarentena].reset_index(drop=True)
    return tratado, quarentena.reset_index(drop=True)


def validar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica o contrato. Devolve (aprovado, reprovado com motivo). Não grava nada.

    Uma linha reprovada leva junto as demais faixas do mesmo município e ano, porque as
    dez faixas só fazem sentido completas. Falha sem linha é de estrutura: nada é gravado.
    """
    try:
        return CONTRATO.validate(df, lazy=True), df.iloc[0:0].assign(motivo=pd.Series(dtype=str))
    except pa.errors.SchemaErrors as erro:
        falhas = erro.failure_cases
        if falhas["index"].isna().any():
            raise SystemExit(f"Contrato quebrado na estrutura, nada foi gravado:\n{falhas}")

        motivo_por_linha = falhas.groupby("index")["check"].agg(lambda s: ", ".join(sorted(set(map(str, s)))))
        pares = df.loc[motivo_por_linha.index, ["cod_municipio", "ano"]].drop_duplicates()
        no_par = df.merge(pares, on=["cod_municipio", "ano"], how="left", indicator=True)["_merge"].eq("both")
        no_par.index = df.index

        reprovado = df[no_par].assign(
            motivo=motivo_por_linha.reindex(df.index[no_par]).fillna("municipio_ano_com_faixa_reprovada")
        )
        aprovado = CONTRATO.validate(df[~no_par])
        return aprovado, reprovado


def ordenar(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena por município, ano e faixa (na ordem das idades), para a saída ser estável."""
    ordem_faixa = {faixa: i for i, faixa in enumerate(FAIXAS)}
    return (
        df.sort_values(
            CHAVE, key=lambda c: c.map(ordem_faixa) if c.name == "faixa_idade_mae" else c
        )
        .reset_index(drop=True)
    )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    tratado, quarentena_atipicos = tratar(higienizar(carregar(DIR_RAW)))
    aprovado, reprovado = validar(tratado)

    rejeitado = pd.concat([quarentena_atipicos, reprovado], ignore_index=True)
    rejeitado["detectado_em"] = pd.Timestamp.now(tz="UTC")

    TRUSTED.parent.mkdir(parents=True, exist_ok=True)
    ordenar(aprovado).to_parquet(TRUSTED, index=False)

    QUARENTENA.parent.mkdir(parents=True, exist_ok=True)
    ordenar(rejeitado).to_parquet(QUARENTENA, index=False)

    print(f"trusted:    {len(aprovado):6d} linhas -> {TRUSTED}")
    print(f"quarentena: {len(rejeitado):6d} linhas -> {QUARENTENA}")
    for motivo, n in rejeitado["motivo"].value_counts().items():
        print(f"  {motivo:40} {n}")


if __name__ == "__main__":
    main()

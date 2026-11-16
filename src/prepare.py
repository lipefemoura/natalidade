"""Etapa 2 (primeira metade): exploração e flat table, sem treinar modelos."""

from pathlib import Path

import pandas as pd

from src.transform import CONTRATO, FAIXAS


RAIZ = Path(__file__).resolve().parents[1]
TRUSTED = RAIZ / "data/trusted/nascimentos.parquet"
DESTINO = RAIZ / "data/analysis"
ANOS_EXPLORACAO = tuple(range(2003, 2021))
ANOS_ATRIBUTOS = (2018, 2019, 2020)
ANO_ALVO = 2021
ATRIBUTOS = [
    "media_registros_2018_2020",
    "variacao_registros_2018_2020_pct",
    "participacao_menores_20_pct",
    "participacao_30_mais_pct",
    "participacao_ignorada_pct",
]
ALVO = "queda_registros_2021"


def validar_base(df: pd.DataFrame) -> pd.DataFrame:
    """Falhar antes de analisar uma trusted vazia, ambígua ou incompleta no grão."""
    base = CONTRATO.validate(df, lazy=True)
    if base.empty:
        raise ValueError("Trusted vazia: execute a ingestão e a transformação.")
    if base.groupby("cod_municipio")["municipio"].nunique().gt(1).any():
        raise ValueError("Código de município com mais de um nome.")
    grupos = base.groupby(["cod_municipio", "ano"])
    if grupos.size().ne(len(FAIXAS)).any():
        raise ValueError("Município-ano sem as dez faixas; ausência não é zero.")
    if grupos["total_municipio_ano"].nunique().ne(1).any():
        raise ValueError("Total divergente entre faixas do mesmo município-ano.")
    return base


def totais_municipais(base: pd.DataFrame) -> pd.DataFrame:
    """Agregar nascidos; jamais somar total_municipio_ano, repetido por faixa."""
    return (
        base.groupby(["cod_municipio", "municipio", "ano"], as_index=False)
        .agg(registros=("nascidos", "sum"))
        .sort_values(["cod_municipio", "ano"])
        .reset_index(drop=True)
    )


def coorte_completa(totais: pd.DataFrame, anos: tuple[int, ...]) -> pd.DataFrame:
    """Manter apenas municípios presentes em cada ano pedido; não preencher lacunas."""
    if not anos or len(set(anos)) != len(anos):
        raise ValueError("Informe anos distintos e não vazios.")
    periodo = totais[totais["ano"].isin(anos)]
    contagem = periodo.groupby("cod_municipio")["ano"].nunique()
    codigos = contagem.index[contagem.eq(len(anos))]
    return periodo[periodo["cod_municipio"].isin(codigos)].copy()


def explorar(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Resumir só 2003–2020, mostrando o denominador e uma coorte constante."""
    periodo = base[base["ano"].isin(ANOS_EXPLORACAO)].copy()
    if set(periodo["ano"]) != set(ANOS_EXPLORACAO):
        raise ValueError("Exploração exige todos os anos de 2003 a 2020.")
    totais = totais_municipais(periodo)
    balanceada = coorte_completa(totais, ANOS_EXPLORACAO)
    if balanceada.empty:
        raise ValueError("Não há município com a série exploratória completa.")
    serie = totais.groupby("ano", as_index=False).agg(
        municipios_observados=("cod_municipio", "nunique"),
        registros_aprovados=("registros", "sum"),
    )
    constante = balanceada.groupby("ano", as_index=False).agg(
        municipios_coorte=("cod_municipio", "nunique"),
        registros_coorte=("registros", "sum"),
    )
    serie = serie.merge(constante, on="ano", validate="one_to_one")
    serie["municipios_sem_observacao"] = base["cod_municipio"].nunique() - serie["municipios_observados"]
    periodo["zero"] = periodo["nascidos"].eq(0)
    faixas = periodo.groupby("faixa_idade_mae", as_index=False).agg(
        celulas=("nascidos", "size"),
        zeros=("zero", "sum"),
        registros=("nascidos", "sum"),
    )
    faixas["pct_zeros"] = 100 * faixas["zeros"] / faixas["celulas"]
    # Razão das somas, não média dos percentuais municipais.
    faixas["participacao_pct"] = 100 * faixas["registros"] / faixas["registros"].sum()
    faixas = faixas.set_index("faixa_idade_mae").reindex(FAIXAS).reset_index()
    ignorada = (
        periodo[periodo["faixa_idade_mae"].eq("Ignorada")]
        .groupby("ano", as_index=False)
        .agg(registros_idade_ignorada=("nascidos", "sum"))
        .merge(serie[["ano", "registros_aprovados"]], on="ano", validate="one_to_one")
    )
    ignorada["participacao_pct"] = 100 * ignorada["registros_idade_ignorada"] / ignorada["registros_aprovados"]
    return {"serie_anual": serie, "perfil_faixas": faixas,
            "idade_ignorada": ignorada, "totais_exploracao": totais}


def demonstrar_melt(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Demonstrar ida e volta largo/longo sem alegar que a trusted é desarrumada."""
    totais = totais_municipais(base)
    completos = coorte_completa(totais, ANOS_ATRIBUTOS)
    if completos.empty:
        raise ValueError("Sem municípios completos em 2018–2020 para o melt.")
    largo = completos.pivot(index=["cod_municipio", "municipio"], columns="ano", values="registros")
    largo = largo.loc[:, list(ANOS_ATRIBUTOS)].reset_index()
    # Parquet exige nomes textuais; anos são valores nos cabeçalhos desta demonstração.
    largo.columns = largo.columns.map(str)
    largo.columns.name = None
    esperado = len(largo) * len(ANOS_ATRIBUTOS)
    longo = largo.melt(id_vars=["cod_municipio", "municipio"],
                       var_name="ano", value_name="registros").astype({"ano": int})
    if len(longo) != esperado:
        raise ValueError(f"melt: esperado {esperado}, obtido {len(longo)}.")
    ordem = ["cod_municipio", "ano"]
    pd.testing.assert_frame_equal(
        completos.sort_values(ordem).reset_index(drop=True),
        longo[completos.columns].sort_values(ordem).reset_index(drop=True),
        check_dtype=False,
    )
    return largo, longo


def montar_flat(base: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por município: atributos 2018–2020 e alvo posterior, em 2021.

    Pergunta didática, não previsão de nascimentos: os registros de 2021 ficam
    abaixo da média anual de 2018–2020? O alvo não usa informação como atributo.
    """
    totais = totais_municipais(base)
    completos = coorte_completa(totais, (*ANOS_ATRIBUTOS, ANO_ALVO))
    if completos.empty:
        raise ValueError("Sem municípios com atributos e alvo completos.")
    antes = completos[completos["ano"].isin(ANOS_ATRIBUTOS)]
    flat = antes.groupby(["cod_municipio", "municipio"], as_index=False).agg(
        media_registros_2018_2020=("registros", "mean"),
    )
    pontas = antes.pivot(index="cod_municipio", columns="ano", values="registros")
    if pontas[2018].eq(0).any():
        raise ValueError("Base zero em 2018: variação percentual indefinida.")
    variacao = (100 * (pontas[2020] / pontas[2018] - 1)).rename("variacao_registros_2018_2020_pct")
    flat = flat.merge(variacao, on="cod_municipio", validate="one_to_one")
    historico = base[base["ano"].isin(ANOS_ATRIBUTOS) & base["cod_municipio"].isin(flat["cod_municipio"])]
    contagens = historico.pivot_table(index="cod_municipio", columns="faixa_idade_mae",
                                      values="nascidos", aggfunc="sum").reindex(columns=FAIXAS)
    denominador = contagens.sum(axis=1)
    if denominador.eq(0).any():
        raise ValueError("Total histórico zero: participação indefinida.")
    categorias = {
        "participacao_menores_20_pct": FAIXAS[:2],
        "participacao_30_mais_pct": FAIXAS[4:9],
        "participacao_ignorada_pct": ["Ignorada"],
    }
    for coluna, faixas in categorias.items():
        proporcao = (100 * contagens[faixas].sum(axis=1) / denominador).rename(coluna)
        flat = flat.merge(proporcao, on="cod_municipio", validate="one_to_one")
    depois = completos[completos["ano"].eq(ANO_ALVO)][["cod_municipio", "registros"]]
    flat = flat.merge(depois.rename(columns={"registros": "registros_2021"}),
                      on="cod_municipio", validate="one_to_one")
    flat[ALVO] = flat["registros_2021"] < flat["media_registros_2018_2020"]
    return flat.sort_values("cod_municipio").reset_index(drop=True)


def separar_xy(flat: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Selecionar atributos explicitamente: identificação e futuro não entram em X."""
    return flat[ATRIBUTOS].copy(), flat[ALVO].copy()


def executar(origem: Path = TRUSTED, destino: Path = DESTINO) -> dict[str, pd.DataFrame]:
    if not origem.exists():
        raise FileNotFoundError(f"Trusted não encontrada em {origem}. Execute src/transform.py.")
    base = validar_base(pd.read_parquet(origem))
    saidas = explorar(base)
    largo, longo = demonstrar_melt(base)
    flat = montar_flat(base)
    x, y = separar_xy(flat)
    saidas.update({"melt_largo": largo, "melt_longo": longo, "flat_municipios": flat,
                   "X": x, "y": y.to_frame()})
    # Todos os cálculos e verificações ocorrem antes de publicar os arquivos.
    destino.mkdir(parents=True, exist_ok=True)
    for nome, tabela in saidas.items():
        arquivo = destino / f"{nome}.parquet"
        tabela.to_parquet(arquivo, index=False)
        pd.testing.assert_frame_equal(tabela, pd.read_parquet(arquivo))
        print(f"{nome:22} {len(tabela):6} linhas | {len(tabela.columns):2} colunas")
    print(f"melt: {len(largo)} municípios × 3 anos = {len(longo)} linhas, valores preservados")
    print(f"flat: {len(flat)} municípios; {base.cod_municipio.nunique() - len(flat)} excluídos por lacunas")
    print("X: só 2018–2020; y: queda de registros em 2021. Nenhum modelo treinado.")
    print("2022–2024 fora da nova exploração; NÃO são confirmação independente (ver tidy.qmd).")
    return saidas


if __name__ == "__main__":
    executar()
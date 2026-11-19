"""Análise descritiva pareada das pontas do período, sem alegação confirmatória."""

from pathlib import Path

import pandas as pd

from src.model import DIR_GOLD
from src.prepare import RAIZ
from src.transform import FAIXAS


ANALISE = RAIZ / "data/analysis"
ANO_INICIAL, ANO_FINAL = 2003, 2024
COD_SAO_LUIS = "2111300"


def ler_gold(diretorio: Path = DIR_GOLD) -> pd.DataFrame:
    """Ler a fato atômica e suas dimensões com cardinalidade validada."""
    necessarias = [diretorio / f"{nome}.parquet" for nome in (
        "fato_registros", "dim_municipio", "dim_ano", "dim_faixa_idade",
    )]
    ausentes = [str(caminho) for caminho in necessarias if not caminho.exists()]
    if ausentes:
        raise FileNotFoundError(f"Gold incompleta; execute src/model.py: {ausentes}")
    fato, municipio, ano, faixa = [pd.read_parquet(caminho) for caminho in necessarias]
    dados = (
        fato.merge(municipio[["municipio_sk", "cod_municipio", "municipio"]],
                   on="municipio_sk", how="left", validate="many_to_one")
        .merge(ano[["ano_sk", "ano"]], on="ano_sk", how="left", validate="many_to_one")
        .merge(faixa[["faixa_sk", "faixa_idade_mae", "ordem"]],
               on="faixa_sk", how="left", validate="many_to_one")
    )
    if dados[["cod_municipio", "municipio", "ano", "faixa_idade_mae"]].isna().any().any():
        raise ValueError("FK sem correspondência dimensional na gold.")
    if dados.duplicated(["cod_municipio", "ano", "faixa_idade_mae"]).any():
        raise ValueError("Gold duplicada no grão município-ano-faixa.")
    return dados


def mudancas_pareadas(
    dados: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Comparar apenas município-faixa com dado trusted em ambas as pontas.

    As contagens faltantes por quarentena não são zero. Este recorte é descritivo;
    a seleção da quarentena usou toda a série, logo não há confirmação independente.
    """
    pontas = dados[dados["ano"].isin([ANO_INICIAL, ANO_FINAL])]
    largo = pontas.pivot(
        index=["cod_municipio", "municipio", "faixa_idade_mae", "ordem"],
        columns="ano", values="nascidos",
    ).reset_index()
    largo.columns.name = None
    if ANO_INICIAL not in largo or ANO_FINAL not in largo:
        raise ValueError("A gold não contém as duas pontas do período.")
    pareados = largo.dropna(subset=[ANO_INICIAL, ANO_FINAL]).copy().reset_index(drop=True)
    pareados[ANO_INICIAL] = pareados[ANO_INICIAL].astype("int64")
    pareados[ANO_FINAL] = pareados[ANO_FINAL].astype("int64")
    pareados = pareados.rename(columns={ANO_INICIAL: "registros_2003", ANO_FINAL: "registros_2024"})
    pareados["variacao_absoluta"] = pareados.registros_2024 - pareados.registros_2003
    pareados["queda_absoluta"] = -pareados.variacao_absoluta
    pareados["variacao_pct"] = (
        100 * pareados.variacao_absoluta / pareados.registros_2003.where(pareados.registros_2003.ne(0))
    )
    por_faixa = (
        pareados.groupby(["faixa_idade_mae", "ordem"], as_index=False, sort=False)
        .agg(
            municipios_pareados=("cod_municipio", "nunique"),
            registros_2003=("registros_2003", "sum"),
            registros_2024=("registros_2024", "sum"),
            municipios_com_base_zero=("registros_2003", lambda s: int(s.eq(0).sum())),
        )
    )
    por_faixa["variacao_absoluta"] = por_faixa.registros_2024 - por_faixa.registros_2003
    por_faixa["queda_absoluta"] = -por_faixa.variacao_absoluta
    por_faixa["variacao_pct"] = 100 * por_faixa.variacao_absoluta / por_faixa.registros_2003.where(
        por_faixa.registros_2003.ne(0),
    )
    por_faixa = por_faixa.sort_values("queda_absoluta", ascending=False).reset_index(drop=True)

    sem_sao = pareados[pareados.cod_municipio.ne(COD_SAO_LUIS)]
    sensibilidade = (
        sem_sao.groupby(["faixa_idade_mae", "ordem"], as_index=False, sort=False)
        .agg(
            municipios_pareados=("cod_municipio", "nunique"),
            registros_2003=("registros_2003", "sum"),
            registros_2024=("registros_2024", "sum"),
        )
    )
    sensibilidade["variacao_absoluta"] = sensibilidade.registros_2024 - sensibilidade.registros_2003
    sensibilidade["queda_absoluta"] = -sensibilidade.variacao_absoluta
    sensibilidade["variacao_pct"] = 100 * sensibilidade.variacao_absoluta / sensibilidade.registros_2003.where(
        sensibilidade.registros_2003.ne(0),
    )
    sensibilidade = sensibilidade.sort_values("queda_absoluta", ascending=False).reset_index(drop=True)

    ranking = pareados.sort_values(
        ["queda_absoluta", "registros_2003", "cod_municipio"], ascending=[False, False, True],
    ).head(20).reset_index(drop=True)
    ranking_sem_sao = sem_sao.sort_values(
        ["queda_absoluta", "registros_2003", "cod_municipio"], ascending=[False, False, True],
    ).head(20).reset_index(drop=True)
    resumo_pareamento = pd.DataFrame([{
        "municipios_dimensao": dados.cod_municipio.nunique(),
        "municipios_2003": pontas.loc[pontas.ano.eq(ANO_INICIAL), "cod_municipio"].nunique(),
        "municipios_2024": pontas.loc[pontas.ano.eq(ANO_FINAL), "cod_municipio"].nunique(),
        "municipios_pareados": pareados.cod_municipio.nunique(),
        "municipios_sem_ambas_pontas": dados.cod_municipio.nunique() - pareados.cod_municipio.nunique(),
        "pares_municipio_faixa": len(pareados),
        "pares_com_base_zero": int(pareados.registros_2003.eq(0).sum()),
        "pares_sao_luis": int(pareados.cod_municipio.eq(COD_SAO_LUIS).sum()),
    }])
    if len(pareados) != pareados.cod_municipio.nunique() * len(FAIXAS):
        raise ValueError("Município pareado sem todas as dez faixas nas duas pontas.")
    por_faixa = por_faixa.sort_values("ordem").reset_index(drop=True)
    sensibilidade = sensibilidade.sort_values("ordem").reset_index(drop=True)
    if por_faixa.faixa_idade_mae.tolist() != FAIXAS:
        raise ValueError("A agregação não preservou o domínio ordenado das faixas.")
    return resumo_pareamento, pareados, por_faixa, ranking, sensibilidade, ranking_sem_sao


def executar(
    diretorio_gold: Path = DIR_GOLD,
    destino: Path = ANALISE,
    imprimir: bool = True,
) -> dict[str, pd.DataFrame]:
    dados = ler_gold(diretorio_gold)
    resumo, pareados, faixas, ranking, sensibilidade, ranking_sem_sao = mudancas_pareadas(dados)
    saidas = {
        "pareamento_pontas": resumo,
        "mudancas_municipio_faixa": pareados,
        "resumo_mudancas_faixa": faixas,
        "maiores_quedas_municipio_faixa": ranking,
        "sensibilidade_sem_sao_luis": sensibilidade,
        "maiores_quedas_sem_sao_luis": ranking_sem_sao,
    }
    destino.mkdir(parents=True, exist_ok=True)
    for nome, tabela in saidas.items():
        caminho = destino / f"{nome}.parquet"
        tabela.to_parquet(caminho, index=False)
        pd.testing.assert_frame_equal(tabela, pd.read_parquet(caminho))
        if imprimir:
            print(f"{nome:38} {len(tabela):6} linhas")
    if imprimir:
        print("\nCobertura do pareamento:")
        print(resumo.to_string(index=False))
        print("\nVariação agregada por faixa — somente municípios com ambas as pontas:")
        print(faixas[["faixa_idade_mae", "registros_2003", "registros_2024",
                      "variacao_absoluta", "variacao_pct"]].to_string(index=False))
        print("\n20 maiores reduções absolutas por município e faixa (ordem descritiva):")
        print(ranking[["municipio", "faixa_idade_mae", "registros_2003", "registros_2024",
                       "queda_absoluta", "variacao_pct"]].to_string(index=False))
        print("\nSem São Luís — reordenação agregada por faixa:")
        print(sensibilidade[["faixa_idade_mae", "variacao_absoluta", "variacao_pct"]].to_string(index=False))
        print("\nSem teste, intervalo de confiança ou interpretação causal nesta etapa exploratória.")
    return saidas


if __name__ == "__main__":
    executar()
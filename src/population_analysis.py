"""Etapa 2: integração e associação exploratória, não taxa real de natalidade."""

import pandas as pd
from scipy.stats import pearsonr, spearmanr

from src.model import DIR_GOLD, _publicar, construir
from src.population import CONTRATO, RAIZ, perfil_temporal
from src.prepare import validar_base


CHAVE = ["cod_municipio", "ano"]
X_COLUNAS = ["crescimento_pop_2018_2020_pct", "populacao_media_2018_2020",
             "registros_media_2018_2020", "indicador_medio_2018_2020"]


def integrar(registros: pd.DataFrame, populacao: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrega o numerador ANTES do LEFT JOIN 1:1, preserva ausências e audita."""
    registros = validar_base(registros)
    populacao = CONTRATO.validate(populacao, lazy=True)
    totais = registros.groupby(CHAVE, as_index=False).agg(
        municipio=("municipio", "first"), registros=("nascidos", "sum"),
    )
    pop = populacao.rename(columns={"municipio": "municipio_populacao"})
    auditoria = totais.merge(pop, on=CHAVE, how="outer", indicator=True, validate="one_to_one")
    auditoria["nomes_divergentes"] = (
        auditoria["_merge"].eq("both") & auditoria.municipio.ne(auditoria.municipio_populacao)
    )
    cobertura = auditoria.groupby(["ano", "_merge"], observed=True).agg(
        pares=("cod_municipio", "size"), nomes_divergentes=("nomes_divergentes", "sum"),
    ).reset_index().rename(columns={"_merge": "situacao"})
    cobertura["situacao"] = cobertura.situacao.astype(str).map({
        "left_only": "registros_sem_populacao", "right_only": "populacao_sem_registros",
        "both": "pareado",
    })
    painel = totais.merge(pop, on=CHAVE, how="left", validate="one_to_one")
    if len(painel) != len(totais) or painel.registros.sum() != registros.nascidos.sum():
        raise ValueError("Integração multiplicou linhas ou numerador.")
    painel["populacao"] = painel.populacao.astype("Int64")
    painel["registros_por_mil"] = painel.registros / painel.populacao * 1000
    return painel.sort_values(CHAVE).reset_index(drop=True), cobertura


def parear(painel: pd.DataFrame, inicio: int = 2003, fim: int = 2024) -> pd.DataFrame:
    """Flat de pontas com queda positiva; nunca preenche observação ausente."""
    if inicio >= fim or painel.duplicated(CHAVE).any():
        raise ValueError("Janela inválida ou painel com chave duplicada.")
    medidas = ["registros", "populacao", "registros_por_mil"]
    esquerda = painel.loc[painel.ano.eq(inicio) & painel.populacao.notna(),
                           ["cod_municipio", "municipio"] + medidas]
    direita = painel.loc[painel.ano.eq(fim) & painel.populacao.notna(),
                         ["cod_municipio"] + medidas]
    pares = esquerda.merge(direita, on="cod_municipio", how="inner",
                            suffixes=("_inicial", "_final"), validate="one_to_one")
    pares["ano_inicial"], pares["ano_final"] = inicio, fim
    pares["crescimento_pop_pct"] = (pares.populacao_final / pares.populacao_inicial - 1) * 100
    pares["queda_indicador_por_mil"] = pares.registros_por_mil_inicial - pares.registros_por_mil_final
    pares["queda_registros_pct"] = (
        (pares.registros_inicial - pares.registros_final) / pares.registros_inicial.where(
            pares.registros_inicial.gt(0)) * 100
    )
    # Controle aritmético: o que ocorreria só por aumentar o denominador?
    pares["queda_denominador_constante_numerador"] = (
        pares.registros_por_mil_inicial - pares.registros_inicial / pares.populacao_final * 1000
    )
    return pares.sort_values("cod_municipio").reset_index(drop=True)


def correlacoes(pares: pd.DataFrame, cenario: str) -> pd.DataFrame:
    """Testes bilaterais nominais, pós-exploratórios e condicionais ao modelo.

    Pearson: H0 rho=0 sob o modelo usual de pares independentes e normalidade
    bivariada. Spearman: H0 de ausência de associação de ranks, p assintótico.
    Não são testes espaciais nem confirmação da hipótese substantiva.
    """
    linhas = []
    for medida in ("queda_indicador_por_mil", "queda_registros_pct",
                   "queda_denominador_constante_numerador"):
        valores = pares[["crescimento_pop_pct", medida]].dropna().astype(float)
        x, y = valores.crescimento_pop_pct, valores[medida]
        suficiente = len(valores) >= 3 and x.nunique() > 1 and y.nunique() > 1
        pearson = pearsonr(x, y, alternative="two-sided") if suficiente else None
        spearman = spearmanr(x, y, alternative="two-sided") if suficiente else None
        intervalo = pearson.confidence_interval(confidence_level=0.95) if pearson is not None else None
        linhas.append({"cenario": cenario, "desfecho": medida, "n": len(valores),
                       "pearson": float(pearson.statistic) if pearson is not None else float("nan"),
                       "pearson_p_bilateral": float(pearson.pvalue) if pearson is not None else float("nan"),
                       "pearson_ic95_inferior": float(intervalo.low) if intervalo is not None else float("nan"),
                       "pearson_ic95_superior": float(intervalo.high) if intervalo is not None else float("nan"),
                       "spearman": float(spearman.statistic) if spearman is not None else float("nan"),
                       "spearman_p_bilateral": float(spearman.pvalue) if spearman is not None else float("nan"),
                       "status": "teste_nominal_exploratorio" if suficiente else "amostra_ou_variacao_insuficiente"})
    return pd.DataFrame(linhas)


def ajustar_holm(tabela: pd.DataFrame) -> pd.DataFrame:
    """Família conjunta Pearson/Spearman × cenários × desfechos da tabela.

    Hipóteses indefinidas contam conservadoramente na família com p=1, mas
    continuam ausentes na saída. Holm não exige independência entre testes,
    mas não corrige seleção anterior nem p-valores inválidos por dependência espacial.
    """
    saida = tabela.copy()
    colunas = ["pearson_p_bilateral", "spearman_p_bilateral"]
    p = tabela[colunas].reset_index(drop=True).stack(future_stack=True)
    ordem = p.fillna(1.0).sort_values(kind="stable")
    ajustados = (ordem * pd.Series(range(len(ordem), 0, -1), index=ordem.index)).cummax().clip(upper=1)
    ajustados = ajustados.reindex(p.index).where(p.notna()).unstack()
    for coluna in colunas:
        saida[coluna.replace("bilateral", "holm")] = ajustados[coluna].to_numpy()
    return saida


def flat_temporal(painel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """X só 2018–2020, y queda do indicador em 2021; sem treinamento."""
    anteriores = painel.loc[painel.ano.between(2018, 2020) & painel.populacao.notna()].copy()
    completos = anteriores.groupby("cod_municipio").ano.nunique().eq(3)
    anteriores = anteriores.loc[anteriores.cod_municipio.isin(completos[completos].index)]
    medias = anteriores.groupby("cod_municipio", as_index=False).agg(
        municipio=("municipio", "first"), populacao_media_2018_2020=("populacao", "mean"),
        registros_media_2018_2020=("registros", "mean"),
        indicador_medio_2018_2020=("registros_por_mil", "mean"),
    )
    crescimento = parear(anteriores, 2018, 2020)[["cod_municipio", "crescimento_pop_pct"]].rename(
        columns={"crescimento_pop_pct": "crescimento_pop_2018_2020_pct"})
    alvo = painel.loc[painel.ano.eq(2021) & painel.populacao.notna(),
                      ["cod_municipio", "registros_por_mil"]].rename(
                          columns={"registros_por_mil": "indicador_2021"})
    flat = (medias.merge(crescimento, on="cod_municipio", validate="one_to_one")
            .merge(alvo, on="cod_municipio", validate="one_to_one")
            .sort_values("cod_municipio").reset_index(drop=True))
    flat["queda_indicador_2021"] = flat.indicador_2021.lt(flat.indicador_medio_2018_2020)
    return flat, flat[X_COLUNAS].copy(), flat[["queda_indicador_2021"]].copy()


def analisar(registros: pd.DataFrame, populacao: pd.DataFrame) -> dict[str, pd.DataFrame]:
    painel, cobertura = integrar(registros, populacao)
    pontas = parear(painel)
    perfil = perfil_temporal(populacao)
    sinalizados = set(perfil.loc[perfil.revisar_variacao, "cod_municipio"])
    cenarios = {
        "2003_2024_todos_pareados": pontas,
        "2003_2024_sem_sao_luis": pontas.loc[pontas.cod_municipio.ne("2111300")],
        "2003_2024_sem_saltos_pop_sinalizados": pontas.loc[~pontas.cod_municipio.isin(sinalizados)],
        "2011_2021_pareados": parear(painel, 2011, 2021),
    }
    correlacao = ajustar_holm(pd.concat(
        [correlacoes(df, nome) for nome, df in cenarios.items()], ignore_index=True))
    # Não confundir intervalos censitários de 2/3 anos com crescimento anual.
    anuais = []
    anos = set(populacao.ano)
    for fim in sorted(anos):
        if fim - 1 in anos:
            anuais.append(correlacoes(parear(painel, fim - 1, fim), f"{fim - 1}_{fim}"))
    anual = ajustar_holm(pd.concat(anuais, ignore_index=True)) if anuais else correlacao.iloc[0:0].copy()
    flat, x, y = flat_temporal(painel)
    return {"painel": painel, "cobertura": cobertura, "pontas": pontas,
            "correlacoes": correlacao, "correlacoes_anuais": anual,
            "flat": flat, "X": x, "y": y}


def executar() -> dict[str, pd.DataFrame]:
    """Reconstrói gold, analisa e publica apenas saídas reconciliadas/relegíveis."""
    origem_pop = RAIZ / "data/trusted/populacao.parquet"
    construir(origem_populacao=origem_pop, destino=DIR_GOLD)
    registros = pd.read_parquet(RAIZ / "data/trusted/nascimentos.parquet")
    populacao = pd.read_parquet(origem_pop)
    saidas = analisar(registros, populacao)
    _publicar(saidas, RAIZ / "data/analysis/hipotese_populacao")
    print("\nAssociações EXPLORATÓRIAS (não taxa de natalidade; não causais):")
    print(saidas["correlacoes"].to_string(index=False, float_format=lambda x: f"{x:.6g}"))
    print("\nAuditoria das junções:")
    print(saidas["cobertura"].groupby("situacao").pares.sum().to_string())
    return saidas


if __name__ == "__main__":
    executar()
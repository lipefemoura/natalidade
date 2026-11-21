"""Constrói e reconcilia a camada dimensional gold a partir da trusted."""

import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import pandas as pd

from src.prepare import RAIZ, TRUSTED, validar_base
from src.transform import FAIXAS


DIR_GOLD = RAIZ / "data/gold"
ANOS = tuple(range(2003, 2025))
TABELAS = (
    "dim_municipio", "dim_ano", "dim_faixa_idade", "dim_origem_valor",
    "fato_registros", "fato_registros_municipio_ano",
)
TABELAS_TRUSTED = ("nascimentos",)
TABELAS_GOLD = TABELAS
CHAVES = (
    ("dim_municipio", "cod_municipio", "municipio_sk"),
    ("dim_ano", "ano", "ano_sk"),
    ("dim_faixa_idade", "faixa_idade_mae", "faixa_sk"),
    ("dim_origem_valor", "valor_era_traco", "origem_sk"),
)
CONFERENCIA = (
    ("linhas_fato_central", "SELECT COUNT(*) FROM trusted", "SELECT COUNT(*) FROM central"),
    ("nascidos_total", "SELECT SUM(nascidos) FROM trusted", "SELECT SUM(nascidos) FROM central"),
    ("pares_municipio_ano", "SELECT COUNT(*) FROM (SELECT DISTINCT cod_municipio, ano FROM trusted)",
     "SELECT COUNT(*) FROM agregada"),
    ("nascidos_agregada", "SELECT SUM(nascidos) FROM trusted", "SELECT SUM(registros) FROM agregada"),
    ("idade_ignorada", "SELECT SUM(nascidos) FROM trusted WHERE faixa_idade_mae = 'Ignorada'",
     "SELECT SUM(registros_idade_ignorada) FROM agregada"),
    ("celulas_era_traco", "SELECT SUM(CAST(valor_era_traco AS BIGINT)) FROM trusted",
     "SELECT SUM(celulas_era_traco) FROM agregada"),
)


class ModeloInvalido(ValueError):
    """Erro de chave, granularidade ou reconciliação; nada deve ser publicado."""


def dimensoes(base: pd.DataFrame, anos: tuple[int, ...] = ANOS) -> dict[str, pd.DataFrame]:
    """Criar dimensões com SK estáveis na reconstrução integral e ordem explícita."""
    if tuple(sorted(set(anos))) != anos or not anos:
        raise ModeloInvalido("A dimensão ano requer anos distintos, crescentes e não vazios.")
    codigos = base[["cod_municipio", "municipio"]].drop_duplicates()
    if codigos.cod_municipio.duplicated().any():
        raise ModeloInvalido("Código natural aponta para nomes municipais conflitantes.")
    with duckdb.connect() as con:
        con.register("codigos", codigos)
        municipios = con.sql("""
            SELECT ROW_NUMBER() OVER (ORDER BY cod_municipio) AS municipio_sk,
                   cod_municipio, municipio FROM codigos ORDER BY cod_municipio
        """).df()
        # Calendário anual, inclusivo, independentemente de haver eventos.
        dim_ano = con.sql(f"""
            SELECT ano AS ano_sk, ano, (ano // 10) * 10 AS decada
            FROM generate_series({anos[0]}, {anos[-1]}) AS calendario(ano)
            WHERE ano IN ({','.join(map(str, anos))}) ORDER BY ano
        """).df()
    municipios["uf"] = "MA"
    municipios["regiao"] = "Nordeste"

    dim_faixa = pd.DataFrame({
        "faixa_idade_mae": FAIXAS,
        "ordem": range(1, len(FAIXAS) + 1),
        "idade_conhecida": [faixa != "Ignorada" for faixa in FAIXAS],
    })
    dim_faixa.insert(0, "faixa_sk", range(1, len(dim_faixa) + 1))

    dim_origem = pd.DataFrame({
        "valor_era_traco": [False, True],
        "descricao": ["Valor numérico publicado", "Traço publicado, convertido em zero"],
    })
    dim_origem.insert(0, "origem_sk", range(1, len(dim_origem) + 1))

    return {
        "dim_municipio": municipios,
        "dim_ano": dim_ano,
        "dim_faixa_idade": dim_faixa,
        "dim_origem_valor": dim_origem,
    }


def _conferir_dimensao(
    fonte: pd.DataFrame, dimensao: pd.DataFrame, natural: str, surrogate: str,
) -> None:
    """Falhar com chave natural órfã antes de trocar por chave substituta."""
    if dimensao[natural].duplicated().any() or dimensao[surrogate].duplicated().any():
        raise ModeloInvalido(f"{dimensao.columns[0]} não é única em {natural}/{surrogate}.")
    faltantes = fonte[[natural]].drop_duplicates().merge(
        dimensao[[natural]], on=natural, how="left", indicator=True, validate="one_to_one",
    )
    faltantes = faltantes.loc[faltantes["_merge"].eq("left_only"), natural]
    if not faltantes.empty:
        amostra = faltantes.head(5).tolist()
        raise ModeloInvalido(f"{len(faltantes)} chaves sem dimensão para {natural}: {amostra}")


def fatos(
    base: pd.DataFrame,
    dims: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trocar chaves naturais e construir fatos no grão declarado, sem INNER JOIN."""
    fato = base.copy()
    for tabela, natural, surrogate in CHAVES:
        dim = dims[tabela]
        _conferir_dimensao(fato, dim, natural, surrogate)
        fato = fato.merge(
            dim[[natural, surrogate]], on=natural, how="left", validate="many_to_one",
        )

    chaves = ["municipio_sk", "ano_sk", "faixa_sk", "origem_sk"]
    if fato[chaves].isna().any().any():
        raise ModeloInvalido("Chave substituta nula após LEFT JOIN dimensional.")
    if fato.duplicated(chaves).any():
        raise ModeloInvalido("A fato central não é única no grão município-ano-faixa-origem.")
    central = fato[chaves + ["nascidos"]].sort_values(chaves).reset_index(drop=True)

    # A API retorna ambas para manter compatibilidade; a agregação tem função própria.
    return central, agregada(central, dims)


def agregada(central: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Materializar o resumo município-ano em DuckDB, como na aula de aplicação."""
    with duckdb.connect() as con:
        con.register("central", central)
        con.register("faixas", dims["dim_faixa_idade"])
        con.register("origens", dims["dim_origem_valor"])
        return con.sql("""
            SELECT municipio_sk, ano_sk, SUM(nascidos)::BIGINT AS registros,
                   SUM(CASE WHEN faixa_idade_mae = 'Ignorada' THEN nascidos ELSE 0 END)::BIGINT
                       AS registros_idade_ignorada,
                   SUM(CAST(valor_era_traco AS BIGINT))::BIGINT AS celulas_era_traco
            FROM central LEFT JOIN faixas USING (faixa_sk)
                         LEFT JOIN origens USING (origem_sk)
            GROUP BY municipio_sk, ano_sk ORDER BY municipio_sk, ano_sk
        """).df()


def reconciliar(
    base: pd.DataFrame,
    dims: dict[str, pd.DataFrame],
    central: pd.DataFrame,
    agregada: pd.DataFrame,
) -> pd.DataFrame:
    """Comparar linhas, totais e cada grupo antes de publicar qualquer arquivo."""
    if len(central) != len(base):
        raise ModeloInvalido(f"Linhas trusted={len(base)}, central={len(central)}.")
    if central.nascidos.sum() != base.nascidos.sum():
        raise ModeloInvalido("A soma de nascidos não reconcilia trusted/central.")
    municipio = dims["dim_municipio"][["municipio_sk", "cod_municipio"]]
    ano = dims["dim_ano"][["ano_sk", "ano"]]
    faixa = dims["dim_faixa_idade"][["faixa_sk", "faixa_idade_mae"]]
    origem = dims["dim_origem_valor"][["origem_sk", "valor_era_traco"]]
    central_natural = (
        central.merge(municipio, on="municipio_sk", how="left", validate="many_to_one")
        .merge(ano, on="ano_sk", how="left", validate="many_to_one")
        .merge(faixa, on="faixa_sk", how="left", validate="many_to_one")
        .merge(origem, on="origem_sk", how="left", validate="many_to_one")
    )
    trusted_grupo = base.groupby(
        ["cod_municipio", "ano", "faixa_idade_mae"], as_index=False, sort=True,
    ).agg(nascidos_trusted=("nascidos", "sum"), tracos_trusted=("valor_era_traco", "sum"))
    gold_grupo = central_natural.groupby(
        ["cod_municipio", "ano", "faixa_idade_mae"], as_index=False, sort=True,
    ).agg(nascidos_gold=("nascidos", "sum"), tracos_gold=("valor_era_traco", "sum"))
    por_faixa = trusted_grupo.merge(
        gold_grupo, on=["cod_municipio", "ano", "faixa_idade_mae"],
        how="outer", indicator=True, validate="one_to_one",
    )
    if not por_faixa["_merge"].eq("both").all():
        raise ModeloInvalido("Chaves município-ano-faixa divergentes na fato central.")
    if not (por_faixa.nascidos_trusted.eq(por_faixa.nascidos_gold)
            & por_faixa.tracos_trusted.eq(por_faixa.tracos_gold)).all():
        raise ModeloInvalido("Medidas divergentes na reconciliação por município-ano-faixa.")
    if len(agregada) != base[["cod_municipio", "ano"]].drop_duplicates().shape[0]:
        raise ModeloInvalido("Contagem de pares trusted/agregada não reconcilia.")

    esperado = base.groupby(
        ["cod_municipio", "ano"], as_index=False, sort=True,
    ).agg(
        registros_esperados=("nascidos", "sum"),
        ignorada_esperada=("nascidos", lambda s: int(s[base.loc[s.index, "faixa_idade_mae"].eq("Ignorada")].sum())),
        tracos_esperados=("valor_era_traco", "sum"),
    )
    codigos = municipio
    anos = ano
    observado = (
        agregada.merge(codigos, on="municipio_sk", how="left", validate="many_to_one")
        .merge(anos, on="ano_sk", how="left", validate="many_to_one")
    )
    comparacao = esperado.merge(
        observado, on=["cod_municipio", "ano"], how="outer", indicator=True, validate="one_to_one",
    )
    if not comparacao["_merge"].eq("both").all():
        raise ModeloInvalido("Pares município-ano órfãos na reconciliação da agregada.")
    medidas = [
        ("registros_esperados", "registros"),
        ("ignorada_esperada", "registros_idade_ignorada"),
        ("tracos_esperados", "celulas_era_traco"),
    ]
    linhas = []
    with duckdb.connect() as con:
        con.register("trusted", base)
        con.register("central", central)
        con.register("agregada", agregada)
        for nome, consulta_trusted, consulta_gold in CONFERENCIA:
            a = int(con.sql(consulta_trusted).fetchone()[0])
            b = int(con.sql(consulta_gold).fetchone()[0])
            if a != b:
                raise ModeloInvalido(f"Conferência {nome} divergiu: trusted={a}, gold={b}.")
            linhas.append({"medida": nome, "trusted": a, "gold": b})
    for origem, destino in medidas:
        if not (comparacao[origem] == comparacao[destino]).all():
            raise ModeloInvalido(f"Reconciliação por município-ano falhou em {destino}.")
    return pd.DataFrame(linhas)


def _conferir_dominios(dims: dict[str, pd.DataFrame], anos: tuple[int, ...]) -> None:
    if tuple(dims["dim_ano"].ano) != anos:
        raise ModeloInvalido("Dimensão ano não cobre exatamente o calendário declarado.")
    if dims["dim_faixa_idade"].faixa_idade_mae.tolist() != FAIXAS:
        raise ModeloInvalido("Domínio ou ordem das faixas não reconcilia.")
    if set(dims["dim_origem_valor"].valor_era_traco) != {False, True}:
        raise ModeloInvalido("Dimensão de origem deve cobrir traço e valor numérico.")


def fato_populacao(base: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """População fica em fato própria, nunca repetida por faixa etária.

    As dimensões município e ano são conformadas às dos registros. A origem
    da medida é preservada como atributos degenerados tabela/variável.
    """
    from src.population import CONTRATO

    base = CONTRATO.validate(base, lazy=True)
    fato = base.copy()
    for tabela, natural, surrogate in (
        ("dim_municipio", "cod_municipio", "municipio_sk"),
        ("dim_ano", "ano", "ano_sk"),
    ):
        dim = dims[tabela]
        _conferir_dimensao(fato, dim, natural, surrogate)
        fato = fato.merge(dim[[natural, surrogate]], on=natural, how="left", validate="many_to_one")
    chaves = ["municipio_sk", "ano_sk"]
    if fato[chaves].isna().any().any() or fato.duplicated(chaves).any():
        raise ModeloInvalido("Chave populacional órfã ou duplicada.")
    saida = fato[chaves + ["populacao", "tabela", "variavel"]].sort_values(chaves).reset_index(drop=True)
    reconstruida = (
        saida.merge(dims["dim_municipio"][["municipio_sk", "cod_municipio"]],
                    on="municipio_sk", validate="many_to_one")
        .merge(dims["dim_ano"][["ano_sk", "ano"]], on="ano_sk", validate="many_to_one")
    )
    colunas = ["cod_municipio", "ano", "populacao", "tabela", "variavel"]
    pd.testing.assert_frame_equal(
        base[colunas].sort_values(colunas[:2]).reset_index(drop=True),
        reconstruida[colunas].sort_values(colunas[:2]).reset_index(drop=True),
    )
    return saida


def _publicar(
    tabelas: dict[str, pd.DataFrame],
    destino: Path,
) -> None:
    """Gravar em staging, reler, e trocar o diretório inteiro só após validação."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    staging_raiz = Path(tempfile.mkdtemp(prefix=".gold-stage-", dir=destino.parent))
    staging = staging_raiz / destino.name
    staging.mkdir()
    backup = destino.parent / f".gold-backup-{staging_raiz.name.removeprefix('.gold-stage-')}"
    try:
        for nome, tabela in tabelas.items():
            caminho = staging / f"{nome}.parquet"
            tabela.to_parquet(caminho, index=False)
            relida = pd.read_parquet(caminho)
            pd.testing.assert_frame_equal(tabela, relida, check_dtype=True)
        if destino.exists():
            destino.replace(backup)
        try:
            staging.replace(destino)
        except Exception:
            if backup.exists():
                backup.replace(destino)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if staging_raiz.exists():
            shutil.rmtree(staging_raiz)


def construir(
    origem: Path = TRUSTED,
    destino: Path = DIR_GOLD,
    anos: tuple[int, ...] = ANOS,
    origem_populacao: Path | None = None,
    remover_ano_dimensao: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Executar fail-stop em memória; nenhuma tabela é publicada antes de reconciliar."""
    if not origem.exists():
        raise FileNotFoundError(f"Trusted não encontrada em {origem}.")
    base = validar_base(pd.read_parquet(origem))
    if not set(base.ano).issubset(anos):
        raise ModeloInvalido("Trusted contém ano ausente do calendário dimensional.")
    dims = dimensoes(base, anos)
    _conferir_dominios(dims, anos)
    if remover_ano_dimensao is not None:
        # Injeção de falha explícita para a evidência exigida na atividade.
        dims["dim_ano"] = dims["dim_ano"].loc[dims["dim_ano"].ano.ne(remover_ano_dimensao)]
    central, agregada = fatos(base, dims)
    reconciliacao = reconciliar(base, dims, central, agregada)
    tabelas = {**dims, "fato_registros": central,
               "fato_registros_municipio_ano": agregada}
    if origem_populacao is not None:
        populacao = pd.read_parquet(origem_populacao)
        tabelas["fato_populacao"] = fato_populacao(populacao, dims)
        resumo_pop = pd.DataFrame([
            {"medida": "linhas_populacao", "trusted": len(populacao), "gold": len(tabelas["fato_populacao"])},
            # Total de células-pessoas só verifica transporte, não pessoas únicas no tempo.
            {"medida": "soma_celulas_populacao", "trusted": int(populacao.populacao.sum()),
             "gold": int(tabelas["fato_populacao"].populacao.sum())},
        ])
        reconciliacao = pd.concat([reconciliacao, resumo_pop], ignore_index=True)
    _publicar(tabelas, destino)
    for nome, tabela in tabelas.items():
        print(f"{nome:34} {len(tabela):6} linhas -> {destino / (nome + '.parquet')}")
    print("\nReconciliação trusted × gold:")
    print(reconciliacao.to_string(index=False))
    return {**tabelas, "reconciliacao": reconciliacao}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--com-populacao", action="store_true", help="Incluir extensão populacional explicitamente")
    parser.add_argument("--remover-ano-dimensao", type=int, help="Teste fail-stop: simular linha de dimensão faltando")
    args = parser.parse_args()
    populacao = RAIZ / "data/trusted/populacao.parquet" if args.com_populacao else None
    try:
        construir(origem_populacao=populacao, remover_ano_dimensao=args.remover_ano_dimensao)
    except ModeloInvalido as erro:
        print(f"FAIL-STOP: {erro}\nNada foi gravado em data/gold/.", file=sys.stderr)
        sys.exit(1)
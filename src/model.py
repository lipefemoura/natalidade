"""Constrói o modelo estrela em data/gold/ a partir da trusted, conferindo tudo antes de gravar."""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import pandas as pd
import pandera.pandas as pa

from src.transform import CONTRATO, CONTRATO_POPULACAO, FAIXAS


# ============================================================
# CONFIGURAÇÕES
# ============================================================

RAIZ = Path(__file__).resolve().parents[1]
TRUSTED = RAIZ / "data/trusted/nascimentos.parquet"
TRUSTED_POPULACAO = RAIZ / "data/trusted/populacao.parquet"
DIR_GOLD = RAIZ / "data/gold"
ANOS = (2003, 2024)  # primeiro e último ano da dim_ano, os dois incluídos

TABELAS_TRUSTED = ("nascimentos", "populacao")
TABELAS_GOLD = (
    "dim_municipio", "dim_ano", "dim_faixa_idade", "dim_origem_valor",
    "fato_registros", "fato_populacao", "fato_registros_municipio_ano",
)
# Ordem das linhas de cada tabela gravada: a mesma trusted dá sempre os mesmos arquivos
ORDEM = {
    "dim_municipio": "municipio_sk", "dim_ano": "ano_sk", "dim_faixa_idade": "faixa_sk",
    "dim_origem_valor": "origem_sk", "fato_registros": "municipio_sk, ano_sk, faixa_sk",
    "fato_populacao": "municipio_sk, ano_sk", "fato_registros_municipio_ano": "municipio_sk, ano_sk",
}

# (tabela da trusted, dimensão, chave natural, chave substituta)
CHAVES = (
    ("nascimentos", "dim_municipio", "cod_municipio", "municipio_sk"),
    ("nascimentos", "dim_ano", "ano", "ano_sk"),
    ("nascimentos", "dim_faixa_idade", "faixa_idade_mae", "faixa_sk"),
    ("nascimentos", "dim_origem_valor", "valor_era_traco", "origem_sk"),
    ("populacao", "dim_municipio", "cod_municipio", "municipio_sk"),
    ("populacao", "dim_ano", "ano", "ano_sk"),
)

# (medida, consulta na trusted, consulta no gold)
CONFERENCIA = (
    ("linhas de registros", "SELECT COUNT(*) FROM nascimentos", "SELECT COUNT(*) FROM fato_registros"),
    ("nascidos", "SELECT SUM(nascidos) FROM nascimentos", "SELECT SUM(nascidos) FROM fato_registros"),
    ("células que eram traço",
     "SELECT COUNT(*) FILTER (WHERE valor_era_traco) FROM nascimentos",
     "SELECT COUNT(*) FROM fato_registros JOIN dim_origem_valor USING (origem_sk) WHERE valor_era_traco"),
    ("linhas de população", "SELECT COUNT(*) FROM populacao", "SELECT COUNT(*) FROM fato_populacao"),
    ("população", "SELECT SUM(populacao) FROM populacao", "SELECT SUM(populacao) FROM fato_populacao"),
)

# (medida, consulta na fato_registros, consulta na agregada)
CONFERENCIA_AGREGADA = (
    ("pares município-ano",
     "SELECT COUNT(*) FROM (SELECT DISTINCT municipio_sk, ano_sk FROM fato_registros)",
     "SELECT COUNT(*) FROM fato_registros_municipio_ano"),
    ("registros", "SELECT SUM(nascidos) FROM fato_registros",
     "SELECT SUM(registros) FROM fato_registros_municipio_ano"),
    ("registros com idade ignorada",
     "SELECT SUM(nascidos) FROM fato_registros JOIN dim_faixa_idade USING (faixa_sk) "
     "WHERE faixa_idade_mae = 'Ignorada'",
     "SELECT SUM(registros_idade_ignorada) FROM fato_registros_municipio_ano"),
    ("células que eram traço",
     "SELECT COUNT(*) FROM fato_registros JOIN dim_origem_valor USING (origem_sk) WHERE valor_era_traco",
     "SELECT SUM(celulas_era_traco) FROM fato_registros_municipio_ano"),
)

# Classes de tamanho do IBGE agrupadas em quatro; a população de 2003 é a do início da série
PORTE_2003 = """
    CASE WHEN p.populacao IS NULL   THEN 'sem estimativa em 2003'
         WHEN p.populacao <= 20000  THEN 'até 20 mil'
         WHEN p.populacao <= 50000  THEN '20 a 50 mil'
         WHEN p.populacao <= 100000 THEN '50 a 100 mil'
         ELSE 'mais de 100 mil' END
"""
GRUPO_IDADE = {
    "Menos de 15 anos": "menos de 20 anos", "15 a 19 anos": "menos de 20 anos",
    "20 a 24 anos": "20 a 29 anos", "25 a 29 anos": "20 a 29 anos",
    "30 a 34 anos": "30 anos ou mais", "35 a 39 anos": "30 anos ou mais",
    "40 a 44 anos": "30 anos ou mais", "45 a 49 anos": "30 anos ou mais",
    "50 anos ou mais": "30 anos ou mais", "Ignorada": "Ignorada",
}


class ModeloInvalido(ValueError):
    """Chave, granularidade ou conferência que não bate: nada é gravado."""


# ============================================================
# ENTRADA
# ============================================================

def validar_base(df: pd.DataFrame) -> pd.DataFrame:
    """Para antes de modelar uma trusted vazia, ambígua ou com município-ano incompleto."""
    try:
        base = CONTRATO.validate(df, lazy=True)
    except pa.errors.SchemaErrors as erro:
        raise ModeloInvalido(f"Trusted fora do contrato:\n{erro.failure_cases}") from erro
    if base.empty:
        raise ModeloInvalido("Trusted vazia: execute o ingest.py e o transform.py.")
    if base.groupby("cod_municipio")["municipio"].nunique().gt(1).any():
        raise ModeloInvalido("Código de município com mais de um nome.")
    if base.groupby(["cod_municipio", "ano"]).size().ne(len(FAIXAS)).any():
        raise ModeloInvalido("Município-ano sem as dez faixas: ausência não é zero.")
    return base


# ============================================================
# DIMENSÕES
# ============================================================

def dimensoes(con: duckdb.DuckDBPyConnection, anos: tuple[int, int] = ANOS) -> None:
    """Cria as quatro dimensões, cada uma com uma linha por membro."""
    con.execute(f"""
        CREATE TABLE dim_municipio AS
        WITH codigos AS (SELECT DISTINCT cod_municipio, municipio FROM nascimentos),
             p AS (SELECT cod_municipio, populacao FROM populacao WHERE ano = 2003)
        SELECT ROW_NUMBER() OVER (ORDER BY cod_municipio) AS municipio_sk,
               cod_municipio, municipio, {PORTE_2003} AS porte_2003
        FROM codigos LEFT JOIN p USING (cod_municipio)
    """)
    # Uma linha por ano do período inteiro, sem olhar os anos que aparecem nos registros
    con.execute(f"""
        CREATE TABLE dim_ano AS
        SELECT ano AS ano_sk, ano, (ano // 10) * 10 AS decada
        FROM generate_series({anos[0]}, {anos[-1]}) AS t(ano)
    """)
    faixas = pd.DataFrame({
        "faixa_sk": range(1, len(FAIXAS) + 1),
        "faixa_idade_mae": FAIXAS,
        "grupo_idade": [GRUPO_IDADE[faixa] for faixa in FAIXAS],
    })
    con.register("faixas", faixas)
    con.execute("CREATE TABLE dim_faixa_idade AS SELECT * FROM faixas")
    con.execute("""
        CREATE TABLE dim_origem_valor AS
        SELECT ROW_NUMBER() OVER (ORDER BY valor_era_traco) AS origem_sk, valor_era_traco, descricao
        FROM (VALUES (false, 'valor publicado em número'),
                     (true,  'publicado como traço, convertido em zero')) AS t(valor_era_traco, descricao)
    """)


def conferir_chaves(con: duckdb.DuckDBPyConnection) -> None:
    """Antes de montar as fatos: uma linha por membro e nenhuma chave da trusted sem dimensão."""
    for dimensao in dict.fromkeys(d for _, d, _, _ in CHAVES):
        natural, substituta = next((n, s) for _, d, n, s in CHAVES if d == dimensao)
        linhas, naturais, substitutas = con.sql(
            f"SELECT COUNT(*), COUNT(DISTINCT {natural}), COUNT(DISTINCT {substituta}) FROM {dimensao}"
        ).fetchone()
        if not linhas == naturais == substitutas:
            raise ModeloInvalido(f"{dimensao}: {linhas} linhas para {naturais} valores de {natural}")

    print("linhas cuja chave não está na dimensão, antes da troca:")
    total, faltando = 0, []
    for tabela, dimensao, natural, _ in CHAVES:
        orfas = con.sql(f"""
            SELECT t.{natural} AS chave, COUNT(*) AS linhas
            FROM {tabela} t LEFT JOIN {dimensao} d USING ({natural})
            WHERE d.{natural} IS NULL GROUP BY 1 ORDER BY 1
        """).fetchall()
        linhas = sum(n for _, n in orfas)
        print(f"  {tabela + '.' + natural:30} -> {dimensao:18} {linhas:6}")
        if orfas:
            total += linhas
            faltando.append(f"{tabela}.{natural} = {[chave for chave, _ in orfas][:5]} não está em {dimensao}")
    if faltando:
        raise ModeloInvalido(f"{total} linhas sem chave na dimensão ({'; '.join(faltando)}). "
                             "Corrija a dimensão antes de construir as fatos.")


# ============================================================
# FATOS
# ============================================================

def fatos(con: duckdb.DuckDBPyConnection) -> None:
    """Troca as chaves naturais pelas substitutas. LEFT JOIN: linha sem par fica, com chave nula."""
    con.execute("""
        CREATE TABLE fato_registros AS
        SELECT m.municipio_sk, a.ano_sk, f.faixa_sk, o.origem_sk, n.nascidos
        FROM nascimentos n
        LEFT JOIN dim_municipio m USING (cod_municipio)
        LEFT JOIN dim_ano a USING (ano)
        LEFT JOIN dim_faixa_idade f USING (faixa_idade_mae)
        LEFT JOIN dim_origem_valor o USING (valor_era_traco)
    """)
    # População é do município no ano: fica numa fato própria, sem se repetir por faixa de idade
    con.execute("""
        CREATE TABLE fato_populacao AS
        SELECT m.municipio_sk, a.ano_sk, p.populacao
        FROM populacao p
        LEFT JOIN dim_municipio m USING (cod_municipio)
        LEFT JOIN dim_ano a USING (ano)
    """)
    for fato, chaves in (("fato_registros", "municipio_sk, ano_sk, faixa_sk"),
                         ("fato_populacao", "municipio_sk, ano_sk")):
        alguma_nula = " OR ".join(f"{chave} IS NULL" for chave in chaves.split(", "))
        nulas = con.sql(f"SELECT COUNT(*) FROM {fato} WHERE {alguma_nula}").fetchone()[0]
        repetidas = con.sql(f"SELECT COUNT(*) - COUNT(DISTINCT ({chaves})) FROM {fato}").fetchone()[0]
        if nulas or repetidas:
            raise ModeloInvalido(f"{fato}: {nulas} linhas com chave nula e {repetidas} repetidas na granularidade")


def agregada(con: duckdb.DuckDBPyConnection) -> None:
    """Resume a fato_registros por município e ano, a granularidade da fato_populacao."""
    con.execute("""
        CREATE TABLE fato_registros_municipio_ano AS
        SELECT r.municipio_sk, r.ano_sk,
               SUM(r.nascidos)::BIGINT AS registros,
               COALESCE(SUM(r.nascidos) FILTER (WHERE f.faixa_idade_mae = 'Ignorada'), 0)::BIGINT
                   AS registros_idade_ignorada,
               COUNT(*) FILTER (WHERE o.valor_era_traco)::BIGINT AS celulas_era_traco
        FROM fato_registros r
        LEFT JOIN dim_faixa_idade f USING (faixa_sk)
        LEFT JOIN dim_origem_valor o USING (origem_sk)
        GROUP BY r.municipio_sk, r.ano_sk
    """)


# ============================================================
# CONFERÊNCIA
# ============================================================

def comparar(con: duckdb.DuckDBPyConnection, titulo: str, colunas: tuple[str, str], linhas) -> None:
    """Imprime as duas contas lado a lado e para se alguma não bater."""
    print(f"\n{titulo}:")
    print(f"  {'':30} {colunas[0]:>15} {colunas[1]:>15}")
    divergentes = []
    for medida, consulta_origem, consulta_gold in linhas:
        origem = con.sql(consulta_origem).fetchone()[0]
        gold = con.sql(consulta_gold).fetchone()[0]
        print(f"  {medida:30} {origem:>15} {gold:>15}")
        if origem != gold:
            divergentes.append(medida)
    if divergentes:
        raise ModeloInvalido(f"{titulo}: não bateu em {divergentes}")


def conferir_celulas(con: duckdb.DuckDBPyConnection) -> None:
    """Confere cada célula: duas trocas que se anulam passam na soma, mas não aqui."""
    diferentes = con.sql("""
        WITH gold AS (
            SELECT m.cod_municipio, a.ano, f.faixa_idade_mae, o.valor_era_traco, r.nascidos
            FROM fato_registros r
            JOIN dim_municipio m USING (municipio_sk) JOIN dim_ano a USING (ano_sk)
            JOIN dim_faixa_idade f USING (faixa_sk) JOIN dim_origem_valor o USING (origem_sk)
        )
        SELECT COUNT(*) FROM nascimentos n FULL JOIN gold g USING (cod_municipio, ano, faixa_idade_mae)
        WHERE n.nascidos IS DISTINCT FROM g.nascidos
           OR n.valor_era_traco IS DISTINCT FROM g.valor_era_traco
    """).fetchone()[0]
    diferentes += con.sql("""
        WITH gold AS (
            SELECT m.cod_municipio, a.ano, p.populacao
            FROM fato_populacao p JOIN dim_municipio m USING (municipio_sk) JOIN dim_ano a USING (ano_sk)
        )
        SELECT COUNT(*) FROM populacao t FULL JOIN gold g USING (cod_municipio, ano)
        WHERE t.populacao IS DISTINCT FROM g.populacao
    """).fetchone()[0]
    print(f"  {'células diferentes':30} {diferentes:>31}")
    if diferentes:
        raise ModeloInvalido(f"{diferentes} células do gold diferentes da trusted")


# ============================================================
# GRAVAÇÃO
# ============================================================

def publicar(tabelas: dict[str, pd.DataFrame], destino: Path) -> None:
    """Grava numa pasta temporária, relê cada arquivo e só então troca a pasta inteira."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    staging_raiz = Path(tempfile.mkdtemp(prefix=".gold-stage-", dir=destino.parent))
    staging = staging_raiz / destino.name
    staging.mkdir()
    backup = destino.parent / f".gold-backup-{staging_raiz.name.removeprefix('.gold-stage-')}"
    try:
        for nome, tabela in tabelas.items():
            caminho = staging / f"{nome}.parquet"
            tabela.to_parquet(caminho, index=False)
            pd.testing.assert_frame_equal(tabela, pd.read_parquet(caminho))
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
    origem_populacao: Path = TRUSTED_POPULACAO,
    destino: Path = DIR_GOLD,
    anos: tuple[int, int] = ANOS,
    remover_ano_dimensao: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Monta tudo em memória; só grava em data/gold/ se todas as conferências passarem."""
    for arquivo in (origem, origem_populacao):
        if not arquivo.exists():
            raise FileNotFoundError(f"Trusted não encontrada em {arquivo}: execute o transform.py.")
    nascimentos = validar_base(pd.read_parquet(origem))
    populacao = CONTRATO_POPULACAO.validate(pd.read_parquet(origem_populacao))

    with duckdb.connect() as con:
        con.register("nascimentos", nascimentos)
        con.register("populacao", populacao)

        dimensoes(con, anos)
        if remover_ano_dimensao is not None:
            # Simula uma linha de dimensão faltando, para conferir que o script para
            con.execute("DELETE FROM dim_ano WHERE ano = ?", [remover_ano_dimensao])
        conferir_chaves(con)
        fatos(con)
        comparar(con, "conferência das fatos contra a trusted", ("trusted", "gold"), CONFERENCIA)
        conferir_celulas(con)
        agregada(con)
        comparar(con, "conferência da agregada contra a fato_registros",
                 ("fato_registros", "agregada"), CONFERENCIA_AGREGADA)

        tabelas = {nome: con.sql(f"SELECT * FROM {nome} ORDER BY {ORDEM[nome]}").df() for nome in TABELAS_GOLD}

    publicar(tabelas, destino)
    print(f"\ngold -> {destino.relative_to(RAIZ).as_posix() if destino.is_relative_to(RAIZ) else destino}")
    for nome, tabela in tabelas.items():
        print(f"  {nome:30} {len(tabela):6} linhas")
    return tabelas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remover-ano-dimensao", type=int, metavar="ANO",
        help="tira um ano da dim_ano para conferir que o script para antes de gravar",
    )
    args = parser.parse_args()
    try:
        construir(remover_ano_dimensao=args.remover_ano_dimensao)
    except ModeloInvalido as erro:
        print(f"\n{erro}\nnada foi gravado em data/gold/")
        sys.exit(1)

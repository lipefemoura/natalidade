"""Etapa 1 da população: Agregados v3 → raw imutável → contrato → trusted.

Executar ``python -m src.population``; ``--offline`` reprocessa a última coleta.
Não interpola anos censitários nem mistura estimativas com contagens censitárias.
"""

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from src.ingest import requisitar, salvar


RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data/raw/ibge_agregados_6579"
BASE_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/6579"
FONTE = "IBGE/Agregados v3 — 6579, variável 9324, população residente estimada"
ANOS = tuple(ano for ano in range(2003, 2025) if ano not in (2007, 2010, 2022, 2023))
LACUNAS = (2007, 2010, 2022, 2023)
CHAVE = ["cod_municipio", "ano"]
COLUNAS = ["cod_municipio", "municipio", "ano", "populacao", "tabela", "variavel"]
SIMBOLOS = {"-": "populacao_zero", "..": "nao_aplicavel",
            "...": "nao_disponivel", "X": "suprimido"}
CONTRATO = pa.DataFrameSchema({
    "cod_municipio": pa.Column(str, pa.Check.str_matches(r"^21\d{5}$")),
    "municipio": pa.Column(str, pa.Check.str_length(min_value=1)),
    "ano": pa.Column(int, pa.Check.isin(ANOS)),
    "populacao": pa.Column(int, pa.Check.gt(0)),
    "tabela": pa.Column(str, pa.Check.eq("6579")),
    "variavel": pa.Column(str, pa.Check.eq("9324")),
}, unique=CHAVE, strict=True, coerce=True)


def validar_metadados(meta: dict, periodos: list) -> None:
    """Falhar se a consulta mudar de significado ou perder anos esperados."""
    if str(meta.get("id")) != "6579":
        raise ValueError("Agregado inesperado nos metadados.")
    variaveis = {str(v["id"]): v for v in meta["variaveis"]}
    if variaveis.get("9324", {}).get("unidade") != "Pessoas":
        raise ValueError("Variável/unidade populacional mudou.")
    if "N6" not in meta["nivelTerritorial"]["Administrativo"] or meta["classificacoes"]:
        raise ValueError("Nível municipal ou classificações da fonte mudaram.")
    disponiveis = {int(p["id"]) for p in periodos if str(p["id"]).isdigit()}
    if set(ANOS) - disponiveis:
        raise ValueError(f"Fonte perdeu anos: {sorted(set(ANOS) - disponiveis)}")
    if set(LACUNAS) & disponiveis:
        raise ValueError("Fonte passou a publicar lacunas: revisar cobertura antes de continuar.")


def coletar(raiz: Path = RAW) -> Path:
    """Uma consulta de 3.906 valores; cache diário, proveniência e payload original."""
    pasta = raiz / date.today().isoformat()

    def obter(nome: str, url: str):
        destino = pasta / f"{nome}.json"
        if destino.exists():
            envelope = json.loads(destino.read_text(encoding="utf-8"))
            if envelope["url"] != url:
                raise ValueError(f"Cache incompatível: {destino}")
            return envelope["dado"]
        dado = requisitar(url)
        salvar({"fonte": FONTE, "url": url,
                "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "dado": dado}, destino)
        return dado

    meta = obter("metadados", f"{BASE_URL}/metadados")
    periodos = obter("periodos", f"{BASE_URL}/periodos")
    validar_metadados(meta, periodos)
    anos = "%7C".join(map(str, ANOS))
    url = f"{BASE_URL}/periodos/{anos}/variaveis/9324?localidades=N6%5BN3%5B21%5D%5D"
    obter("populacao", url)
    return pasta


def normalizar(payload: list, anos: tuple[int, ...] = ANOS,
               municipios_esperados: int = 217) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Estrutura/chave conflitante: fail-stop; ausências/zero: quarentena explícita.

    Duplicatas integralmente iguais são removidas e contabilizadas; nunca se
    escolhe arbitrariamente entre populações divergentes para a mesma chave.
    """
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("Esperada exatamente uma variável na resposta.")
    variavel = payload[0]
    if str(variavel["id"]) != "9324" or variavel["unidade"] != "Pessoas":
        raise ValueError("Variável ou unidade diferente de população em Pessoas.")
    resultados = variavel["resultados"]
    if len(resultados) != 1 or resultados[0]["classificacoes"]:
        raise ValueError("Classificações inesperadas na população total.")
    linhas = []
    for item in resultados[0]["series"]:
        local = item["localidade"]
        codigo = str(local["id"])
        nome = local["nome"].removesuffix(" - MA").strip()
        if local["nivel"]["id"] != "N6" or not re.fullmatch(r"21\d{5}", codigo) or not nome:
            raise ValueError("Município inválido ou fora do Maranhão.")
        if set(item["serie"]) != set(map(str, anos)):
            raise ValueError(f"Períodos incompletos/inesperados para {codigo}.")
        for ano, bruto in item["serie"].items():
            if not isinstance(bruto, str) or not (re.fullmatch(r"\d+", bruto) or bruto in SIMBOLOS):
                raise ValueError(f"Símbolo populacional desconhecido: {bruto!r}")
            linhas.append({"cod_municipio": codigo, "municipio": nome, "ano": int(ano),
                           "valor_original": bruto, "tabela": "6579", "variavel": "9324"})
    base = pd.DataFrame(linhas)
    if base.empty or base.cod_municipio.nunique() != municipios_esperados:
        raise ValueError("Cobertura municipal inesperada; nenhuma saída foi publicada.")
    duplicatas = int(base.duplicated().sum())
    base = base.drop_duplicates().reset_index(drop=True)
    if base.duplicated(CHAVE).any() or base.groupby("cod_municipio").municipio.nunique().gt(1).any():
        raise ValueError("Chave ou nome municipal conflitante.")
    base["populacao"] = pd.array([
        int(valor) if valor.isdigit() else (0 if valor == "-" else pd.NA)
        for valor in base.valor_original
    ], dtype="Int64")
    motivos = base.valor_original.map(SIMBOLOS).fillna("")
    motivos = motivos.mask(base.populacao.eq(0).fillna(False), "populacao_zero")
    rejeitada = base.loc[motivos.ne("")].copy()
    rejeitada["motivo"] = motivos.loc[rejeitada.index]
    rejeitada["detectado_em"] = pd.Timestamp.now(tz="UTC")
    aprovada = base.loc[motivos.eq(""), COLUNAS].copy()
    aprovada["populacao"] = aprovada.populacao.astype("int64")
    # O contrato usa a janela de produção; testes com subconjuntos continuam válidos.
    aprovada = CONTRATO.validate(aprovada, lazy=True)
    aprovada = aprovada.sort_values(CHAVE).reset_index(drop=True)
    rejeitada = rejeitada.sort_values(CHAVE).reset_index(drop=True)
    resumo = {"linhas_raw": len(linhas), "duplicatas_identicas": duplicatas,
              "linhas_trusted": len(aprovada), "linhas_quarentena": len(rejeitada),
              "anos_disponiveis": list(anos), "anos_sem_publicacao": list(LACUNAS),
              "imputacoes": 0, "winsorizacoes": 0}
    if len(linhas) != duplicatas + len(aprovada) + len(rejeitada):
        raise ValueError("Reconciliação raw/trusted/quarentena falhou.")
    return aprovada, rejeitada, resumo


def perfil_temporal(base: pd.DataFrame) -> pd.DataFrame:
    """Sinaliza mudanças anualizadas >10%; não elimina extremos legítimos."""
    perfil = base.sort_values(CHAVE).copy()
    grupo = perfil.groupby("cod_municipio", sort=False)
    perfil["intervalo_anos"] = perfil.ano - grupo.ano.shift()
    perfil["variacao_anualizada_pct"] = (
        (perfil.populacao / grupo.populacao.shift()) ** (1 / perfil.intervalo_anos) - 1
    ) * 100
    perfil["revisar_variacao"] = perfil.variacao_anualizada_pct.abs().gt(10)
    return perfil.reset_index(drop=True)


def transformar(coleta: Path, raiz: Path = RAIZ) -> dict:
    """Valida integralmente antes de gravar; arquivos temporários são relidos."""
    def ler(nome):
        return json.loads((coleta / f"{nome}.json").read_text(encoding="utf-8"))["dado"]

    validar_metadados(ler("metadados"), ler("periodos"))
    base, quarentena, resumo = normalizar(ler("populacao"))
    resumo["coleta"] = coleta.name
    perfil = perfil_temporal(base)
    resumo["mudancas_sinalizadas"] = int(perfil.revisar_variacao.sum())
    arquivos = {
        raiz / "data/trusted/populacao.parquet": base,
        raiz / "data/quarentena/populacao.parquet": quarentena,
        raiz / "data/analysis/perfil_populacao.parquet": perfil,
    }
    temporarios = []
    try:
        for destino, tabela in arquivos.items():
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario = destino.with_suffix(".tmp.parquet")
            temporarios.append((temporario, destino))
            tabela.to_parquet(temporario, index=False)
            pd.testing.assert_frame_equal(tabela, pd.read_parquet(temporario))
        for temporario, destino in temporarios:
            temporario.replace(destino)
    finally:
        for temporario, _ in temporarios:
            temporario.unlink(missing_ok=True)
    salvar(resumo, raiz / "data/analysis/diagnostico_populacao.json")
    return resumo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Reprocessar última coleta local")
    args = parser.parse_args()
    coleta = max(p for p in RAW.iterdir() if p.is_dir()) if args.offline else coletar()
    print(json.dumps(transformar(coleta), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
"""Modelo estrela com dados pequenos, sem rede e sem tocar no data/gold/ do projeto."""

import tempfile
import unittest
from pathlib import Path

import duckdb
import pandas as pd

from src.model import TABELAS_GOLD, ModeloInvalido, conferir_celulas, construir, dimensoes, fatos, validar_base
from src.transform import ANOS_POPULACAO, FAIXAS

MUNICIPIOS = (("2100055", "Açailândia", 1), ("2100105", "Afonso Cunha", 2))


def registros() -> pd.DataFrame:
    linhas = []
    for codigo, nome, fator in MUNICIPIOS:
        for ano in range(2003, 2025):
            valores = [0 if faixa == "Ignorada" and ano == 2024 else fator * (ano % 7 + 1) for faixa in FAIXAS]
            linhas += [
                {"cod_municipio": codigo, "municipio": nome, "ano": ano, "faixa_idade_mae": faixa,
                 "nascidos": valor, "valor_era_traco": valor == 0, "total_municipio_ano": sum(valores)}
                for faixa, valor in zip(FAIXAS, valores)
            ]
    return pd.DataFrame(linhas)


def populacao() -> pd.DataFrame:
    return pd.DataFrame([
        {"cod_municipio": codigo, "municipio": nome, "ano": ano, "populacao": 10_000 * fator + ano}
        for codigo, nome, fator in MUNICIPIOS for ano in ANOS_POPULACAO
    ])


class ModeloTest(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        raiz = Path(self.pasta.name)
        self.origem, self.origem_populacao = raiz / "nascimentos.parquet", raiz / "populacao.parquet"
        self.destino = raiz / "gold"
        registros().to_parquet(self.origem, index=False)
        populacao().to_parquet(self.origem_populacao, index=False)

    def tearDown(self):
        self.pasta.cleanup()

    def construir(self, **kwargs):
        return construir(self.origem, self.origem_populacao, self.destino, **kwargs)

    def test_grava_as_sete_tabelas_do_desenho(self):
        tabelas = self.construir()
        self.assertEqual(sorted(p.stem for p in self.destino.glob("*.parquet")), sorted(TABELAS_GOLD))
        self.assertEqual(len(tabelas["dim_ano"]), 22)
        self.assertEqual(len(tabelas["fato_registros"]), len(registros()))
        self.assertEqual(tabelas["fato_registros"]["nascidos"].sum(), registros()["nascidos"].sum())
        self.assertEqual(len(tabelas["fato_populacao"]), len(populacao()))
        self.assertEqual(len(tabelas["fato_registros_municipio_ano"]), 2 * 22)

    def test_mesma_trusted_da_os_mesmos_arquivos(self):
        self.construir()
        primeira = {p.name: p.read_bytes() for p in self.destino.glob("*.parquet")}
        self.construir()
        self.assertEqual(primeira, {p.name: p.read_bytes() for p in self.destino.glob("*.parquet")})

    def test_ano_faltando_na_dimensao_para_antes_de_gravar(self):
        self.destino.mkdir()
        (self.destino / "anterior.txt").write_text("intacto", encoding="utf-8")
        with self.assertRaisesRegex(ModeloInvalido, r"\[2024\] não está em dim_ano"):
            self.construir(remover_ano_dimensao=2024)
        self.assertEqual([p.name for p in self.destino.iterdir()], ["anterior.txt"])

    def test_calendario_curto_tambem_para(self):
        with self.assertRaisesRegex(ModeloInvalido, "dim_ano"):
            self.construir(anos=(2003, 2023))
        self.assertFalse(self.destino.exists())

    def test_municipio_ano_incompleto_e_recusado(self):
        with self.assertRaisesRegex(ModeloInvalido, "dez faixas"):
            base = registros()
            # a faixa Ignorada de 2024 vale zero: sem ela a soma ainda bate, mas o par fica com nove faixas
            sem_uma_faixa = ~((base["ano"] == 2024) & (base["faixa_idade_mae"] == "Ignorada")
                              & (base["cod_municipio"] == "2100055"))
            validar_base(base[sem_uma_faixa])

    def test_conferencia_por_celula_pega_trocas_que_se_anulam(self):
        with duckdb.connect() as con:
            con.register("nascimentos", registros())
            con.register("populacao", populacao())
            dimensoes(con)
            fatos(con)
            filtro = "ano_sk = 2010 AND municipio_sk = 1"
            con.execute(f"UPDATE fato_registros SET nascidos = nascidos + 1 WHERE faixa_sk = 1 AND {filtro}")
            con.execute(f"UPDATE fato_registros SET nascidos = nascidos - 1 WHERE faixa_sk = 2 AND {filtro}")
            soma = con.sql("SELECT sum(nascidos) FROM fato_registros").fetchone()[0]
            self.assertEqual(soma, registros()["nascidos"].sum())
            with self.assertRaisesRegex(ModeloInvalido, "células"):
                conferir_celulas(con)


if __name__ == "__main__":
    unittest.main()

"""Testes locais do modelo estrela, sem rede e sem tocar data/gold/ real."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.model import ANOS, ModeloInvalido, construir, dimensoes, fatos, reconciliar
from src.transform import FAIXAS


def exemplo_modelo() -> pd.DataFrame:
    linhas = []
    for codigo, nome, fator in [("2100055", "Açailândia", 1), ("2100105", "Afonso Cunha", 2)]:
        for ano in ANOS:
            for faixa in FAIXAS:
                traco = ano == 2024 and faixa == "Ignorada" and fator == 1
                linhas.append({
                    "cod_municipio": codigo,
                    "municipio": nome,
                    "ano": ano,
                    "faixa_idade_mae": faixa,
                    "nascidos": 0 if traco else fator * ano % 17,
                    "valor_era_traco": traco,
                    "total_municipio_ano": sum(
                        0 if (ano == 2024 and f == "Ignorada" and fator == 1)
                        else fator * ano % 17 for f in FAIXAS
                    ),
                })
    return pd.DataFrame(linhas)


class ModeloTest(unittest.TestCase):
    def setUp(self):
        self.base = exemplo_modelo()

    def test_dimensoes_completas_e_chaves_deterministicas(self):
        dims = dimensoes(self.base)
        self.assertEqual(dims["dim_ano"].ano.tolist(), list(ANOS))
        self.assertEqual(dims["dim_faixa_idade"].faixa_idade_mae.tolist(), FAIXAS)
        self.assertEqual(set(dims["dim_origem_valor"].valor_era_traco), {False, True})
        pd.testing.assert_frame_equal(dims["dim_municipio"], dimensoes(self.base)["dim_municipio"])

    def test_ausencia_de_ano_na_dimensao_e_fail_stop(self):
        dims = dimensoes(self.base, ANOS[:-1])
        with self.assertRaisesRegex(ModeloInvalido, "sem dimensão para ano"):
            fatos(self.base, dims)

    def test_fatos_preservam_graos_e_medidas(self):
        dims = dimensoes(self.base)
        central, agregada = fatos(self.base, dims)
        self.assertEqual(len(central), len(self.base))
        self.assertEqual(central.nascidos.sum(), self.base.nascidos.sum())
        self.assertEqual(len(agregada), 2 * len(ANOS))
        self.assertEqual(agregada.registros.sum(), self.base.nascidos.sum())
        self.assertEqual(agregada.registros_idade_ignorada.sum(),
                         self.base.loc[self.base.faixa_idade_mae.eq("Ignorada"), "nascidos"].sum())
        self.assertEqual(agregada.celulas_era_traco.sum(), int(self.base.valor_era_traco.sum()))

    def test_reconciliacao_por_faixa_detecta_troca_com_total_global_igual(self):
        dims = dimensoes(self.base)
        central, agregada = fatos(self.base, dims)
        central.loc[0, "nascidos"] += 1
        central.loc[1, "nascidos"] -= 1
        self.assertEqual(central.nascidos.sum(), self.base.nascidos.sum())
        with self.assertRaisesRegex(ModeloInvalido, "município-ano-faixa"):
            reconciliar(self.base, dims, central, agregada)

    def test_falha_nao_altera_gold_existente(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "trusted.parquet"
            destino = Path(pasta) / "gold"
            destino.mkdir()
            marcador = destino / "anterior.txt"
            marcador.write_text("gold anterior intacto", encoding="utf-8")
            self.base.to_parquet(origem, index=False)
            with self.assertRaisesRegex(ModeloInvalido, "ano ausente"):
                construir(origem, destino, ANOS[:-1])
            self.assertEqual(marcador.read_text(encoding="utf-8"), "gold anterior intacto")
            self.assertEqual(list(destino.iterdir()), [marcador])

    def test_gravacao_e_releitura_de_todas_as_tabelas(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "trusted.parquet"
            destino = Path(pasta) / "gold"
            self.base.to_parquet(origem, index=False)
            tabelas = construir(origem, destino)
            esperados = {"dim_municipio", "dim_ano", "dim_faixa_idade", "dim_origem_valor",
                         "fato_registros", "fato_registros_municipio_ano", "reconciliacao"}
            self.assertEqual(set(tabelas), esperados)
            self.assertEqual(len(list(destino.glob("*.parquet"))), len(esperados) - 1)
            for nome in esperados - {"reconciliacao"}:
                pd.testing.assert_frame_equal(tabelas[nome], pd.read_parquet(destino / f"{nome}.parquet"))


if __name__ == "__main__":
    unittest.main()
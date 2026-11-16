"""Verificações locais sem rede; dados artificiais não são resultados do projeto."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.prepare import (
    ALVO, ANOS_ATRIBUTOS, ATRIBUTOS, coorte_completa, demonstrar_melt,
    executar, explorar, montar_flat, separar_xy, totais_municipais, validar_base,
)
from src.transform import FAIXAS


def exemplo() -> pd.DataFrame:
    linhas = []
    for codigo, nome, fator in [("2100055", "Açailândia", 1), ("2100105", "Afonso Cunha", 2)]:
        for ano in range(2003, 2025):
            valor = fator * (10 if ano <= 2020 else 8)
            for faixa in FAIXAS:
                linhas.append({"cod_municipio": codigo, "municipio": nome, "ano": ano,
                               "faixa_idade_mae": faixa, "nascidos": valor,
                               "valor_era_traco": False, "total_municipio_ano": valor * 10})
    return pd.DataFrame(linhas)


class PreparacaoTest(unittest.TestCase):
    def setUp(self):
        self.base = exemplo()

    def test_base_valida(self):
        pd.testing.assert_frame_equal(validar_base(self.base), self.base)

    def test_total_repetido_nao_e_somado(self):
        totais = totais_municipais(self.base)
        self.assertEqual(totais.registros.sum(), self.base.nascidos.sum())
        self.assertEqual(self.base.total_municipio_ano.sum(), 10 * totais.registros.sum())

    def test_faixa_ausente_zero_tambem_reprova(self):
        # A soma ainda fecha: o contrato antigo não basta para detectar uma faixa zero ausente.
        base = self.base.copy()
        par = base.cod_municipio.eq("2100055") & base.ano.eq(2018)
        base.loc[par, "total_municipio_ano"] -= 10
        base.loc[par & base.faixa_idade_mae.eq("Ignorada"), "nascidos"] = 0
        base = base.drop(base[par & base.faixa_idade_mae.eq("Ignorada")].index)
        with self.assertRaisesRegex(ValueError, "dez faixas"):
            validar_base(base)

    def test_codigo_com_nomes_conflitantes_reprova(self):
        self.base.loc[0, "municipio"] = "Outro nome"
        with self.assertRaisesRegex(ValueError, "mais de um nome"):
            validar_base(self.base)

    def test_base_vazia_reprova(self):
        with self.assertRaisesRegex(ValueError, "vazia"):
            validar_base(self.base.iloc[:0])

    def test_lacuna_nao_vira_zero(self):
        base = self.base[~(self.base.cod_municipio.eq("2100055") & self.base.ano.eq(2019))]
        coorte = coorte_completa(totais_municipais(base), ANOS_ATRIBUTOS)
        self.assertEqual(set(coorte.cod_municipio), {"2100105"})
        self.assertEqual(len(coorte), 3)

    def test_melt_preserva_contagem_e_soma(self):
        largo, longo = demonstrar_melt(self.base)
        self.assertEqual(len(longo), len(largo) * 3)
        self.assertEqual(longo.registros.sum(), largo[list(map(str, ANOS_ATRIBUTOS))].sum().sum())

    def test_exploracao_nao_usa_anos_posteriores(self):
        saidas = explorar(self.base)
        self.assertEqual(saidas["serie_anual"].ano.max(), 2020)
        self.assertAlmostEqual(saidas["perfil_faixas"].participacao_pct.sum(), 100)
        self.assertTrue(saidas["perfil_faixas"].pct_zeros.eq(0).all())

    def test_cobertura_variavel_e_coorte_constante(self):
        base = self.base[~(self.base.cod_municipio.eq("2100055") & self.base.ano.eq(2004))]
        serie = explorar(base)["serie_anual"].set_index("ano")
        self.assertEqual(serie.loc[2004, "municipios_observados"], 1)
        self.assertEqual(serie.loc[2003, "municipios_observados"], 2)
        self.assertTrue(serie.municipios_coorte.eq(1).all())

    def test_flat_tem_alvo_e_x_sem_futuro_nem_identificacao(self):
        flat = montar_flat(self.base)
        x, y = separar_xy(flat)
        self.assertTrue(y.all())
        self.assertEqual(list(x.columns), ATRIBUTOS)
        self.assertNotIn("registros_2021", x)
        self.assertNotIn("cod_municipio", x)
        self.assertNotIn(ALVO, x)
        self.assertEqual(len(flat), flat.cod_municipio.nunique())

    def test_alterar_alvo_nao_altera_atributos(self):
        original = montar_flat(self.base)
        base = self.base.copy()
        base.loc[base.ano.eq(2021), "nascidos"] *= 10
        alterada = montar_flat(base)
        pd.testing.assert_frame_equal(original[ATRIBUTOS], alterada[ATRIBUTOS])
        self.assertFalse(alterada[ALVO].any())

    def test_alterar_reserva_nao_muda_flat_nem_exploracao(self):
        base = self.base.copy()
        base.loc[base.ano.ge(2022), "nascidos"] *= 100
        pd.testing.assert_frame_equal(montar_flat(self.base), montar_flat(base))
        for nome, tabela in explorar(self.base).items():
            pd.testing.assert_frame_equal(tabela, explorar(base)[nome])

    def test_alvo_ausente_exclui_municipio(self):
        base = self.base[~(self.base.cod_municipio.eq("2100055") & self.base.ano.eq(2021))]
        self.assertEqual(list(montar_flat(base).cod_municipio), ["2100105"])

    def test_anos_duplicados_reprovam(self):
        with self.assertRaisesRegex(ValueError, "distintos"):
            coorte_completa(totais_municipais(self.base), (2018, 2018))

    def test_publicacao_e_releitura(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "trusted.parquet"
            destino = Path(pasta) / "analysis"
            self.base.to_parquet(origem, index=False)
            saidas = executar(origem, destino)
            self.assertEqual(len(list(destino.glob("*.parquet"))), len(saidas))
            pd.testing.assert_frame_equal(saidas["flat_municipios"], pd.read_parquet(destino / "flat_municipios.parquet"))

    def test_falha_nao_publica(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "trusted.parquet"
            destino = Path(pasta) / "analysis"
            self.base[self.base.ano.ne(2003)].to_parquet(origem, index=False)
            with self.assertRaisesRegex(ValueError, "todos os anos"):
                executar(origem, destino)
            self.assertFalse(destino.exists())


if __name__ == "__main__":
    unittest.main()
"""Testes de grão, faltantes, sinais, sensibilidade e atributos temporais."""

import unittest

import pandas as pd

from src.model import ModeloInvalido, construir, dimensoes, fato_populacao
from src.population_analysis import correlacoes, flat_temporal, integrar, parear
from src.transform import FAIXAS


def bases():
    registros, populacao = [], []
    for i, codigo in enumerate(("2100055", "2111300", "2100105")):
        for ano in (2003, 2018, 2019, 2020, 2021, 2024):
            nome = f"Cidade {i}"
            populacao.append({"cod_municipio": codigo, "municipio": nome, "ano": ano,
                              "populacao": 1000 + (ano - 2003) * (i + 1) * 10,
                              "tabela": "6579", "variavel": "9324"})
            for faixa in FAIXAS:
                registros.append({"cod_municipio": codigo, "municipio": nome, "ano": ano,
                                  "faixa_idade_mae": faixa, "nascidos": 10,
                                  "valor_era_traco": False, "total_municipio_ano": 100})
    return pd.DataFrame(registros), pd.DataFrame(populacao)


class IntegracaoPopulacaoTest(unittest.TestCase):
    def test_juncao_nao_multiplica_denominador_por_faixas(self):
        registros, populacao = bases()
        painel, cobertura = integrar(registros, populacao)
        self.assertEqual(len(painel), len(populacao))
        self.assertEqual(painel.populacao.sum(), populacao.populacao.sum())
        self.assertEqual(painel.registros.sum(), registros.nascidos.sum())
        self.assertTrue(cobertura.situacao.eq("pareado").all())

    def test_populacao_ausente_preserva_registro_e_nao_vira_zero(self):
        registros, populacao = bases()
        populacao = populacao.loc[~(populacao.cod_municipio.eq("2100055") & populacao.ano.eq(2024))]
        painel, cobertura = integrar(registros, populacao)
        self.assertEqual(painel.populacao.isna().sum(), 1)
        self.assertEqual(painel.registros_por_mil.isna().sum(), 1)
        self.assertEqual(len(parear(painel)), 2)
        self.assertEqual(cobertura.loc[cobertura.situacao.eq("registros_sem_populacao"), "pares"].sum(), 1)

    def test_pontas_sinal_positivo_queda_e_controle_denominador(self):
        painel, _ = integrar(*bases())
        pares = parear(painel)
        self.assertTrue(pares.crescimento_pop_pct.gt(0).all())
        self.assertTrue(pares.queda_indicador_por_mil.gt(0).all())
        self.assertTrue(pares.queda_registros_pct.eq(0).all())
        pd.testing.assert_series_equal(pares.queda_indicador_por_mil,
                                      pares.queda_denominador_constante_numerador, check_names=False)

    def test_correlacao_conhecida_e_amostra_constante(self):
        pares = pd.DataFrame({"crescimento_pop_pct": [1, 2, 3],
                              "queda_indicador_por_mil": [2, 4, 6],
                              "queda_registros_pct": [0, 0, 0],
                              "queda_denominador_constante_numerador": [6, 4, 2]})
        corr = correlacoes(pares, "teste")
        self.assertAlmostEqual(corr.pearson.iloc[0], 1)
        self.assertAlmostEqual(corr.spearman.iloc[2], -1)
        self.assertTrue(pd.isna(corr.pearson.iloc[1]))
        self.assertEqual(corr.status.iloc[1], "amostra_ou_variacao_insuficiente")

    def test_alvo_futuro_nao_altera_x(self):
        painel, _ = integrar(*bases())
        flat, x, y = flat_temporal(painel)
        alterado = painel.copy()
        alterado.loc[alterado.ano.eq(2021), "registros_por_mil"] *= 10
        _, novo_x, novo_y = flat_temporal(alterado)
        pd.testing.assert_frame_equal(x, novo_x)
        self.assertFalse(y.equals(novo_y))
        self.assertEqual(len(flat), 3)

    def test_flat_exclui_lacuna_sem_imputar(self):
        painel, _ = integrar(*bases())
        painel = painel.loc[~(painel.cod_municipio.eq("2100055") & painel.ano.eq(2019))]
        flat, x, y = flat_temporal(painel)
        self.assertEqual(len(flat), 2)
        self.assertEqual(len(x), len(y))

    def test_fato_populacao_reconcilia_em_grao_proprio(self):
        registros, populacao = bases()
        fato = fato_populacao(populacao, dimensoes(registros))
        self.assertEqual(len(fato), len(populacao))
        self.assertEqual(fato.populacao.sum(), populacao.populacao.sum())
        self.assertFalse(fato.duplicated(["municipio_sk", "ano_sk"]).any())

    def test_fato_populacao_orfa_interrompe(self):
        registros, populacao = bases()
        populacao.loc[0, "cod_municipio"] = "2100154"
        with self.assertRaises(ModeloInvalido):
            fato_populacao(populacao, dimensoes(registros))

    def test_carga_gold_com_populacao_e_releitura(self):
        import tempfile
        from pathlib import Path

        registros, populacao = bases()
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            registros.to_parquet(raiz / "registros.parquet", index=False)
            populacao.to_parquet(raiz / "populacao.parquet", index=False)
            tabelas = construir(raiz / "registros.parquet", raiz / "gold",
                                origem_populacao=raiz / "populacao.parquet")
            self.assertEqual(len(tabelas["fato_populacao"]), len(populacao))
            pd.testing.assert_frame_equal(tabelas["fato_populacao"],
                                          pd.read_parquet(raiz / "gold/fato_populacao.parquet"))


if __name__ == "__main__":
    unittest.main()
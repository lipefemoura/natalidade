"""Testes de mudanças pareadas: ausências, base zero e análise de sensibilidade."""

import unittest

import pandas as pd

from src.analyze import mudancas_pareadas
from src.transform import FAIXAS


def exemplo_pontas() -> pd.DataFrame:
    linhas = []
    municipios = [("2111300", "São Luís", 100), ("2100055", "Açailândia", 50)]
    for codigo, nome, base in municipios:
        for ano in (2003, 2024):
            for ordem, faixa in enumerate(FAIXAS, start=1):
                antes = 0 if codigo == "2100055" and ordem == 1 else base * ordem
                depois = antes // 2 if ano == 2024 else antes
                linhas.append({"cod_municipio": codigo, "municipio": nome, "ano": ano,
                               "faixa_idade_mae": faixa, "ordem": ordem,
                               "nascidos": antes if ano == 2003 else depois})
    return pd.DataFrame(linhas)


class AnaliseTest(unittest.TestCase):
    def test_pareia_so_cidades_com_as_duas_pontas_e_10_faixas(self):
        dados = exemplo_pontas()
        faltante = dados[~(dados.cod_municipio.eq("2100055") & dados.ano.eq(2024))]
        resumo, pareados, _, _, _, _ = mudancas_pareadas(faltante)
        self.assertEqual(resumo.loc[0, "municipios_pareados"], 1)
        self.assertEqual(len(pareados), len(FAIXAS))

    def test_variacao_percentual_indefinida_com_base_zero(self):
        _, pareados, _, _, _, _ = mudancas_pareadas(exemplo_pontas())
        linha = pareados[(pareados.cod_municipio == "2100055") & pareados.ordem.eq(1)]
        self.assertEqual(linha.registros_2003.iloc[0], 0)
        self.assertTrue(pd.isna(linha.variacao_pct.iloc[0]))
        self.assertEqual(linha.registros_2024.iloc[0], 0)

    def test_exclusao_de_sao_luis_muda_sensibilidade_sem_alterar_total_pareado(self):
        resumo, pareados, faixas, _, sem_sao, _ = mudancas_pareadas(exemplo_pontas())
        self.assertEqual(resumo.loc[0, "municipios_pareados"], 2)
        self.assertTrue(pareados.cod_municipio.eq("2111300").any())
        faixa = FAIXAS[1]
        total = faixas.loc[faixas.faixa_idade_mae.eq(faixa), "registros_2003"].iloc[0]
        sem = sem_sao.loc[sem_sao.faixa_idade_mae.eq(faixa), "registros_2003"].iloc[0]
        self.assertEqual(total - sem, 200)
        self.assertEqual(sem_sao.faixa_idade_mae.tolist(), FAIXAS)


if __name__ == "__main__":
    unittest.main()
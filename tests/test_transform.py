"""Contratos e quarentena do transform.py, com dados pequenos e sem rede."""

import unittest

import pandas as pd

from src.transform import (
    ANOS_POPULACAO, FAIXAS, conferir_fonte_populacao, higienizar_populacao, separar_populacao, validar,
)


def tabela_tratada(ano=2010):
    valores = list(range(1, len(FAIXAS) + 1))
    return pd.DataFrame([
        {"cod_municipio": codigo, "municipio": nome, "ano": ano, "faixa_idade_mae": faixa,
         "nascidos": valor, "valor_era_traco": False, "total_municipio_ano": sum(valores)}
        for codigo, nome in (("2100055", "Açailândia"), ("2100105", "Afonso Cunha"))
        for faixa, valor in zip(FAIXAS, valores)
    ])


def resposta_populacao(valores=None):
    valores = valores or {str(ano): "1000" for ano in ANOS_POPULACAO}
    return [{"id": "9324", "resultados": [{"classificacoes": [], "series": [{
        "localidade": {"id": "2100055", "nome": "Açailândia - MA", "nivel": {"id": "N6"}},
        "serie": valores,
    }]}]}]


def valores_com(ano, valor):
    valores = {str(a): "1000" for a in ANOS_POPULACAO}
    valores[str(ano)] = valor
    return valores


class ContratoTest(unittest.TestCase):
    def test_tabela_correta_passa_inteira(self):
        aprovado, reprovado = validar(tabela_tratada())
        self.assertEqual(len(aprovado), 2 * len(FAIXAS))
        self.assertTrue(reprovado.empty)

    def test_soma_diferente_do_total_reprova_o_par_inteiro(self):
        df = tabela_tratada()
        df.loc[0, "nascidos"] += 5
        aprovado, reprovado = validar(df)
        self.assertEqual(len(reprovado), len(FAIXAS))
        self.assertEqual(set(reprovado["motivo"]), {"soma_das_faixas_difere_do_total"})
        self.assertEqual(set(aprovado["municipio"]), {"Afonso Cunha"})

    def test_traco_com_valor_leva_as_outras_faixas_junto(self):
        df = tabela_tratada()
        df.loc[3, "valor_era_traco"] = True
        _, reprovado = validar(df)
        motivos = reprovado["motivo"].value_counts()
        self.assertEqual(motivos["traco_com_valor_diferente_de_zero"], 1)
        self.assertEqual(motivos["municipio_ano_com_faixa_reprovada"], len(FAIXAS) - 1)

    def test_faixa_maior_que_total(self):
        df = tabela_tratada()
        df.loc[2, "nascidos"] = df.loc[2, "total_municipio_ano"] + 1
        _, reprovado = validar(df)
        self.assertIn("faixa_maior_que_total", reprovado.loc[2, "motivo"])


class PopulacaoTest(unittest.TestCase):
    def separar(self, valores=None):
        return separar_populacao(higienizar_populacao(resposta_populacao(valores), municipios=1))

    def test_valores_viram_inteiros_e_nome_perde_a_uf(self):
        aprovado, rejeitado = self.separar()
        self.assertEqual(len(aprovado), len(ANOS_POPULACAO))
        self.assertEqual(set(aprovado["municipio"]), {"Açailândia"})
        self.assertEqual(str(aprovado["populacao"].dtype), "int64")
        self.assertTrue(rejeitado.empty)

    def test_simbolo_e_zero_vao_para_a_quarentena(self):
        for valor, motivo in (("...", "nao_disponivel"), ("X", "suprimido"), ("0", "populacao_zero")):
            with self.subTest(valor=valor):
                aprovado, rejeitado = self.separar(valores_com(2003, valor))
                self.assertEqual(len(aprovado), len(ANOS_POPULACAO) - 1)
                self.assertEqual(rejeitado["motivo"].tolist(), [motivo])

    def test_simbolo_desconhecido_para_tudo(self):
        with self.assertRaisesRegex(ValueError, "símbolos desconhecidos"):
            self.separar(valores_com(2003, "?"))

    def test_ano_faltando_para_tudo(self):
        valores = {str(ano): "1000" for ano in ANOS_POPULACAO[1:]}
        with self.assertRaisesRegex(ValueError, "anos diferentes"):
            self.separar(valores)

    def test_tabela_que_muda_de_unidade_para_tudo(self):
        metadados = {"variaveis": [{"id": 9324, "unidade": "Mil pessoas"}],
                     "nivelTerritorial": {"Administrativo": ["N6"]}, "classificacoes": []}
        periodos = [{"id": str(ano)} for ano in ANOS_POPULACAO]
        with self.assertRaisesRegex(ValueError, "população em pessoas"):
            conferir_fonte_populacao(metadados, periodos)


if __name__ == "__main__":
    unittest.main()

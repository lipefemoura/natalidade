"""Contrato e falhas da nova fonte, sem acesso à rede."""

import copy
import unittest
from unittest.mock import patch

from src.population import ANOS, coletar, normalizar, perfil_temporal, transformar, validar_metadados


def resposta(valores=("100", "120")):
    return [{"id": "9324", "unidade": "Pessoas", "resultados": [{
        "classificacoes": [], "series": [{
            "localidade": {"id": "2100055", "nome": "Açailândia - MA", "nivel": {"id": "N6"}},
            "serie": dict(zip(("2003", "2004"), valores)),
        }],
    }]}]


class PopulacaoTest(unittest.TestCase):
    def tratar(self, payload):
        return normalizar(payload, anos=(2003, 2004), municipios_esperados=1)

    def test_normaliza_codigo_nome_e_inteiro(self):
        base, rejeitada, resumo = self.tratar(resposta())
        self.assertEqual(base.municipio.tolist(), ["Açailândia"] * 2)
        self.assertEqual(base.populacao.tolist(), [100, 120])
        self.assertEqual(str(base.populacao.dtype), "int64")
        self.assertTrue(rejeitada.empty)
        self.assertEqual(resumo["linhas_trusted"], 2)

    def test_simbolos_vao_para_quarentena_nao_para_zero_imputado(self):
        for simbolo in ("..", "...", "X", "-", "0"):
            with self.subTest(simbolo=simbolo):
                base, rejeitada, resumo = self.tratar(resposta((simbolo, "120")))
                self.assertEqual(len(base), 1)
                self.assertEqual(rejeitada.valor_original.item(), simbolo)
                self.assertEqual(resumo["linhas_quarentena"], 1)
                self.assertTrue(rejeitada.motivo.notna().all())

    def test_simbolo_desconhecido_interrompe(self):
        for valor in ("?", "1.5", "-1", None):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self.tratar(resposta((valor, "120")))

    def test_duplicata_identica_auditada(self):
        payload = resposta()
        series = payload[0]["resultados"][0]["series"]
        series.append(copy.deepcopy(series[0]))
        base, _, resumo = self.tratar(payload)
        self.assertEqual(len(base), 2)
        self.assertEqual(resumo["duplicatas_identicas"], 2)

    def test_duplicata_conflitante_interrompe(self):
        payload = resposta()
        series = payload[0]["resultados"][0]["series"]
        outro = copy.deepcopy(series[0])
        outro["serie"]["2003"] = "101"
        series.append(outro)
        with self.assertRaises(ValueError):
            self.tratar(payload)

    def test_cobertura_e_unidade_interrompem(self):
        for caminho, valor in (("unidade", "Percentual"), ("id", "93")):
            payload = resposta()
            payload[0][caminho] = valor
            with self.assertRaises(ValueError):
                self.tratar(payload)
        payload = resposta()
        del payload[0]["resultados"][0]["series"][0]["serie"]["2004"]
        with self.assertRaises(ValueError):
            self.tratar(payload)
        with self.assertRaises(ValueError):
            normalizar(resposta(), anos=(2003, 2004))

    def test_extremo_legitimo_apenas_sinalizado(self):
        base, _, _ = self.tratar(resposta(("100", "200")))
        perfil = perfil_temporal(base)
        self.assertEqual(perfil.populacao.tolist(), [100, 200])
        self.assertEqual(perfil.revisar_variacao.tolist(), [False, True])

    def test_lacuna_nao_usa_crescimento_bienal_como_anual(self):
        base, _, _ = self.tratar(resposta(("100", "121")))
        base.loc[1, "ano"] = 2005
        perfil = perfil_temporal(base)
        self.assertAlmostEqual(perfil.variacao_anualizada_pct.iloc[1], 10)

    def test_metadados_perda_de_periodo(self):
        meta = {"id": 6579, "variaveis": [{"id": 9324, "unidade": "Pessoas"}],
                "nivelTerritorial": {"Administrativo": ["N6"]}, "classificacoes": []}
        periodos = [{"id": str(ano)} for ano in ANOS]
        validar_metadados(meta, periodos)
        with self.assertRaises(ValueError):
            validar_metadados(meta, periodos[:-1])

    def test_cache_diario_e_idempotente(self):
        import tempfile
        from pathlib import Path

        meta = {"id": 6579, "variaveis": [{"id": 9324, "unidade": "Pessoas"}],
                "nivelTerritorial": {"Administrativo": ["N6"]}, "classificacoes": []}
        periodos = [{"id": str(ano)} for ano in ANOS]
        with tempfile.TemporaryDirectory() as pasta:
            with patch("src.population.requisitar", side_effect=[meta, periodos, resposta()]) as get:
                coleta = coletar(Path(pasta))
                self.assertEqual(get.call_count, 3)
            arquivos = {p.name: p.read_bytes() for p in coleta.iterdir()}
            with patch("src.population.requisitar") as get:
                self.assertEqual(coletar(Path(pasta)), coleta)
                get.assert_not_called()
            self.assertEqual(arquivos, {p.name: p.read_bytes() for p in coleta.iterdir()})

    def test_falha_estrutural_preserva_trusted_anterior(self):
        import json
        import tempfile
        from pathlib import Path

        meta = {"id": 6579, "variaveis": [{"id": 9324, "unidade": "Pessoas"}],
                "nivelTerritorial": {"Administrativo": ["N6"]}, "classificacoes": []}
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            coleta = raiz / "raw"
            coleta.mkdir()
            for nome, dado in {"metadados": meta,
                               "periodos": [{"id": str(ano)} for ano in ANOS],
                               "populacao": resposta(("?", "120"))}.items():
                (coleta / f"{nome}.json").write_text(json.dumps({"dado": dado}))
            trusted = raiz / "data/trusted/populacao.parquet"
            trusted.parent.mkdir(parents=True)
            trusted.write_bytes(b"trusted-anterior-intacta")
            with self.assertRaises(ValueError):
                transformar(coleta, raiz)
            self.assertEqual(trusted.read_bytes(), b"trusted-anterior-intacta")
            self.assertFalse((raiz / "data/quarentena/populacao.parquet").exists())


if __name__ == "__main__":
    unittest.main()
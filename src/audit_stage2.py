"""Produz evidências reais para o relatório, sem simular números ou trocar a fonte.

Testa rebuild em diretório temporário e a CLI fail-stop sobre gold real. A opção
--reproduzir-coleta executa a sequência oficial em cópia limpa e com nova coleta.
"""

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.model import DIR_GOLD, construir
from src.population import RAIZ


def hashes(pasta: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pasta.glob("*.parquet"))}


def executar(reproduzir_coleta: bool = False) -> dict:
    saida = io.StringIO()
    populacao = RAIZ / "data/trusted/populacao.parquet"
    with contextlib.redirect_stdout(saida):
        tabelas = construir(origem_populacao=populacao)
    antes = hashes(DIR_GOLD)
    falha = subprocess.run([sys.executable, "src/model.py", "--com-populacao",
                            "--remover-ano-dimensao", "2024"], cwd=RAIZ,
                           text=True, capture_output=True)
    if falha.returncode != 1 or "2024" not in falha.stderr or "Nada foi gravado" not in falha.stderr:
        raise RuntimeError(f"Falha controlada não produziu o resultado esperado: {falha}")
    if hashes(DIR_GOLD) != antes:
        raise RuntimeError("A falha alterou gold: teste reprovado.")
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "gold"
        with contextlib.redirect_stdout(io.StringIO()):
            construir(destino=destino, origem_populacao=populacao)
        primeira = hashes(destino)
        shutil.rmtree(destino)
        with contextlib.redirect_stdout(io.StringIO()):
            construir(destino=destino, origem_populacao=populacao)
        segunda = hashes(destino)
        if primeira != segunda or primeira != antes:
            raise RuntimeError("Rebuild não é idêntico em bytes (SHA-256).")
    evidencia = {
        "verificado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "normal": saida.getvalue(), "falha_dimensao": falha.stderr.strip(),
        "codigo_saida_falha": falha.returncode, "gold_preservada_em_falha": True,
        "rebuild_identico_sha256": True, "sha256": antes,
        "tabelas": {nome: len(tabela) for nome, tabela in tabelas.items() if nome != "reconciliacao"},
        "conferencia": tabelas["reconciliacao"].to_dict(orient="records"),
    }
    if reproduzir_coleta:
        with tempfile.TemporaryDirectory(prefix="natalidade-repro-") as pasta:
            destino = Path(pasta)
            for nome in ("src", "analises"):
                shutil.copytree(RAIZ / nome, destino / nome,
                                ignore=shutil.ignore_patterns("__pycache__", "*.html", "*_files"))
            for nome in ("pyproject.toml", "uv.lock", "_quarto.yml", ".env.example"):
                shutil.copy2(RAIZ / nome, destino / nome)
            comandos = [
                ["uv", "sync"],
                ["uv", "run", "python", "src/ingest.py"],
                ["uv", "run", "quarto", "render", "analises/diagnostico.qmd"],
                ["uv", "run", "python", "src/transform.py"],
                ["uv", "run", "quarto", "render", "analises/exploracao.qmd"],
                ["uv", "run", "python", "src/model.py"],
            ]
            registros = []
            for comando in comandos:
                print("Reprodução limpa:", " ".join(comando), flush=True)
                processo = subprocess.run(comando, cwd=destino, text=True, capture_output=True)
                registros.append({"comando": " ".join(comando), "codigo_saida": processo.returncode,
                                  "saida_final": (processo.stdout + processo.stderr)[-3000:]})
                if processo.returncode != 0:
                    raise RuntimeError(f"Reprodução falhou: {registros[-1]}")
            evidencia["reproducao_limpa"] = registros
            evidencia["coleta_reproducao"] = max((destino / "data/raw/ibge_sidra_2609").iterdir()).name
    caminho = RAIZ / "relatorios/evidencias-etapa-2.json"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(evidencia, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidências verificadas em {caminho}")
    print(falha.stderr.strip())
    print("Gold preservada; rebuild idêntico por SHA-256.")
    return evidencia


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reproduzir-coleta", action="store_true")
    executar(parser.parse_args().reproduzir_coleta)
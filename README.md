# natalidade

Projeto da disciplina Introdução à Ciência de Dados (Sistemas de Informação, IFMA).

**Pergunta analítica:** entre 2003 e 2024, em que municípios do Maranhão e em que faixas
de idade da mãe os nascimentos registrados mais caíram?

**Fonte:** IBGE, API do SIDRA, [tabela 2609](https://sidra.ibge.gov.br/tabela/2609)
(Estatísticas do Registro Civil): nascidos vivos registrados no ano, por município do
Maranhão e idade da mãe na ocasião do parto, de 2003 a 2024.

## Chave de acesso

A fonte não exige chave nem cadastro. O `.env.example` existe apenas por convenção do
projeto e não declara variáveis.

## Como executar

Requer o [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lipefemoura/natalidade.git
cd natalidade
uv sync
uv run python src/ingest.py
uv run quarto render diagnostico.qmd
uv run python src/transform.py
```

## O que cada etapa produz

| Etapa | Saída |
|---|---|
| `src/ingest.py` | `data/raw/ibge_sidra_2609/AAAA-MM-DD/uf21_ANO.json`: um arquivo por ano, com a resposta original da API e a proveniência (fonte, URL, data da coleta). A pasta leva a data da execução. |
| `diagnostico.qmd` | `diagnostico.html`: perfil, duplicatas, tabela de decisão e tratamento do dado bruto. |
| `src/transform.py` | `data/trusted/`: dado tratado e validado pelo contrato. `data/quarentena/`: linhas reprovadas, com o motivo. |

<!-- TODO: completar com os nomes dos arquivos e as colunas quando o transform.py estiver pronto -->

## Estrutura

```
data/raw/          dado bruto, imutável (fora do git, recriado pelo ingest.py)
data/trusted/      dado tratado e validado (recriado pelo transform.py)
data/quarentena/   linhas reprovadas, com motivo (recriado pelo transform.py)
src/ingest.py      da fonte para data/raw/
src/transform.py   de data/raw/ para data/trusted/
diagnostico.qmd    diagnóstico do dado bruto
```

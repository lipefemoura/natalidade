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
| `diagnostico.qmd` | `diagnostico.html`: perfil, duplicatas, tabela de decisão e tratamento do dado bruto. Grava também `data/quarentena/atipicos-municipio-ano.csv`. |
| `src/transform.py` | `data/trusted/nascimentos.parquet` e `data/quarentena/rejeitados.parquet`, descritos abaixo. Ao final, imprime quantas linhas foram para cada arquivo e o total por motivo de rejeição. |

### `data/trusted/nascimentos.parquet`

Uma linha por município, ano e faixa de idade da mãe, validada pelo contrato do `transform.py`.

| Coluna | Tipo | Conteúdo |
|---|---|---|
| `cod_municipio` | texto | código IBGE do município (7 dígitos, começando com 21) |
| `municipio` | texto | nome do município |
| `ano` | inteiro | ano do registro, de 2003 a 2024 |
| `faixa_idade_mae` | texto | uma de dez categorias: nove faixas de idade e "Ignorada" |
| `nascidos` | inteiro | nascidos vivos registrados no ano |
| `valor_era_traco` | lógico | verdadeiro quando o IBGE publicou `-`, convertido em 0 |
| `total_municipio_ano` | inteiro | total de registros do município no ano (soma das dez faixas) |

Os valores são registros em cartório no ano, e não nascimentos ocorridos no ano: o registro tardio, de crianças nascidas em anos anteriores, explica boa parte da queda entre 2003 e 2024.

### `data/quarentena/rejeitados.parquet`

As mesmas colunas, mais `motivo` (a regra que reprovou a linha) e `detectado_em` (data e hora da execução, em UTC). Um município e ano reprovados vão inteiros, com as dez faixas. Motivos possíveis:

- `participacao_atipica_no_municipio`: participação do município no total do estado abaixo de 0,25 ou acima de 3 vezes a sua participação mediana;
- violações do contrato, com o nome da regra (por exemplo, `soma_das_faixas_difere_do_total`);
- `municipio_ano_com_faixa_reprovada`: faixas que acompanham outra faixa reprovada do mesmo município e ano.

Uma mudança de estrutura na origem (coluna nova ou faltando, símbolo desconhecido no valor) interrompe o `transform.py` sem gravar nada.

## Estrutura

```
data/raw/          dado bruto, imutável (fora do git, recriado pelo ingest.py)
data/trusted/      dado tratado e validado (recriado pelo transform.py)
data/quarentena/   linhas reprovadas, com motivo (recriado pelo transform.py)
src/ingest.py      da fonte para data/raw/
src/transform.py   de data/raw/ para data/trusted/
diagnostico.qmd    diagnóstico do dado bruto
```

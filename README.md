# natalidade

Projeto da disciplina Introdução à Ciência de Dados (Sistemas de Informação, IFMA).

**Equipe:** Gustavo dos Santos Bandeira Rocha (20231SI0006), Deusiane Pimenta Rocha (20231SI0032)
e Felipe Moura de Oliveira (20231SI0027).

**Pergunta:** há correlação entre o crescimento de um município do Maranhão e a queda da sua taxa
de natalidade? A pergunta parte da que guiou a preparação do dado: entre 2003 e 2024, em que
municípios e em que faixas de idade da mãe os nascimentos registrados mais caíram?

## Fontes

Ambas do IBGE, sem chave nem cadastro. O `.env.example` existe por convenção e não declara variáveis.

| Fonte | O que traz |
|---|---|
| [SIDRA, tabela 2609](https://sidra.ibge.gov.br/tabela/2609) (Estatísticas do Registro Civil) | nascidos vivos registrados no ano, por município e idade da mãe, de 2003 a 2024 |
| [Agregados, tabela 6579](https://sidra.ibge.gov.br/tabela/6579), variável 9324 | população residente estimada, por município, nos anos publicados (não há estimativa em 2007, 2010, 2022 e 2023) |

Os registros contam crianças registradas em cartório no ano, inclusive as nascidas em anos
anteriores, e não nascimentos ocorridos no ano. Por isso, registros por mil habitantes não é a
taxa de natalidade do IBGE.

## Como executar

Requer o [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lipefemoura/natalidade.git
cd natalidade
uv sync
uv run python src/ingest.py
uv run quarto render analises/diagnostico.qmd
uv run python src/transform.py
uv run quarto render analises/exploracao.qmd
uv run python src/model.py
```

O `_quarto.yml` faz os documentos de `analises/` rodarem a partir da raiz do projeto.

## O que cada etapa produz

| Etapa | Saída |
|---|---|
| `src/ingest.py` | `data/raw/ibge_sidra_2609/AAAA-MM-DD/uf21_ANO.json` (um arquivo por ano) e `data/raw/ibge_agregados_6579/AAAA-MM-DD/` (população, metadados e anos publicados), com a resposta original da API, a fonte, a URL e o instante da coleta. A pasta leva a data da execução. |
| `analises/diagnostico.qmd` | `diagnostico.html`: perfil das duas fontes, duplicatas, tabelas de decisão com a consulta de cada linha, tratamento e as regras do contrato. Grava também `data/quarentena/atipicos-municipio-ano.csv`. |
| `src/transform.py` | `data/trusted/` e `data/quarentena/`, descritos abaixo. Imprime quantas linhas foram para cada arquivo e o total por motivo de rejeição. |
| `analises/exploracao.qmd` | `exploracao.html`: as perguntas com as expectativas, a varredura sobre 2003–2020, a quarentena relida e as hipóteses a confirmar em 2021–2024. |
| `src/model.py` | `data/gold/`, descrito abaixo. Imprime a conferência da trusted com o gold antes de gravar. |

### `data/trusted/`

`nascimentos.parquet`: uma linha por município, ano e faixa de idade da mãe.

| Coluna | Tipo | Conteúdo |
|---|---|---|
| `cod_municipio` | texto | código IBGE do município (7 dígitos, começando com 21) |
| `municipio` | texto | nome do município |
| `ano` | inteiro | ano do registro, de 2003 a 2024 |
| `faixa_idade_mae` | texto | uma de dez categorias: nove faixas de idade e "Ignorada" |
| `nascidos` | inteiro | nascidos vivos registrados no ano |
| `valor_era_traco` | lógico | verdadeiro quando o IBGE publicou `-`, convertido em 0 |
| `total_municipio_ano` | inteiro | total do município no ano, repetido nas dez faixas: não deve ser somado entre elas |

`populacao.parquet`: uma linha por município e ano com estimativa publicada, com `cod_municipio`,
`municipio`, `ano` e `populacao` (inteiro).

### `data/quarentena/`

`rejeitados.parquet` tem as mesmas colunas de `nascimentos.parquet`, mais `motivo` (a regra que
reprovou a linha) e `coletado_em` (o instante da coleta do arquivo de origem, para que a quarentena
saia igual a cada execução). Um município e ano reprovados vão inteiros, com as dez faixas. Motivos
possíveis:

- `participacao_atipica_no_municipio`: participação do município no total do estado abaixo de 0,25
  ou acima de 3 vezes a sua participação mediana;
- uma regra do contrato, com o nome dela (por exemplo, `soma_das_faixas_difere_do_total`);
- `municipio_ano_com_faixa_reprovada`: faixas que acompanham outra faixa reprovada do mesmo
  município e ano.

`populacao.parquet` guarda os valores de população que vieram como símbolo do IBGE ou como zero,
com o valor original, o `motivo` e o `coletado_em`.

Uma mudança de estrutura em qualquer das fontes (coluna, ano ou município faltando, símbolo
desconhecido, tabela com outra unidade) interrompe o `transform.py` sem gravar nada.

### `data/gold/`

Modelo estrela, gravado só pelo `src/model.py`, um arquivo Parquet por tabela:

| Tabela | Uma linha por | Colunas |
|---|---|---|
| `dim_municipio` | município (217) | `municipio_sk`, `cod_municipio`, `municipio`, `porte_2003` |
| `dim_ano` | ano de 2003 a 2024 (22) | `ano_sk` (o próprio ano), `ano`, `decada` |
| `dim_faixa_idade` | faixa de idade da mãe (10) | `faixa_sk`, `faixa_idade_mae`, `grupo_idade` |
| `dim_origem_valor` | origem do valor (2) | `origem_sk`, `valor_era_traco`, `descricao` |
| `fato_registros` | município, ano e faixa | `municipio_sk`, `ano_sk`, `faixa_sk`, `origem_sk`, `nascidos` |
| `fato_populacao` | município e ano com estimativa | `municipio_sk`, `ano_sk`, `populacao` |
| `fato_registros_municipio_ano` | município e ano (agregada da `fato_registros`) | `municipio_sk`, `ano_sk`, `registros`, `registros_idade_ignorada`, `celulas_era_traco` |

A população se soma entre municípios do mesmo ano, mas não entre anos. A taxa de registros por mil
habitantes se calcula juntando `fato_registros_municipio_ano` e `fato_populacao` por
`municipio_sk` e `ano_sk`.

O desenho do modelo está em `analises/estrela.qmd`
(`uv run quarto render analises/estrela.qmd`, depois do `model.py`).

## Verificações

```bash
uv run python -m unittest discover -s tests
uv run python src/model.py --remover-ano-dimensao 2024
```

O primeiro comando roda os testes, que usam dados pequenos e não acessam a rede. O segundo tira
2024 da `dim_ano` e mostra o `model.py` parando antes de gravar, com a chave que falta; o
`data/gold/` fica como estava.

## Estrutura

```
data/raw/          dado bruto, imutável (fora do git, recriado pelo ingest.py)
data/trusted/      dado tratado e validado (recriado pelo transform.py)
data/quarentena/   linhas reprovadas, com motivo (recriado pelo transform.py)
data/gold/         modelo estrela (recriado pelo model.py)
src/ingest.py      das fontes para data/raw/
src/transform.py   de data/raw/ para data/trusted/ e data/quarentena/
src/model.py       de data/trusted/ para data/gold/
analises/          diagnóstico, exploração e desenho do modelo
tests/             testes do transform.py e do model.py
```

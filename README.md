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

## Etapa 2 — andamento (aproximadamente 75%)

### Nova hipótese e fonte populacional

**Hipótese:** “Há correlação entre o crescimento da cidade e a queda da taxa de
natalidade”. A população residente estimada (IBGE Agregados v3, tabela 6579,
variável 9324) foi adicionada como fonte municipal independente. A documentação
completa, contrato, limitações e decisões estão em [docs/populacao.md](docs/populacao.md)
e o diagnóstico reproduzível em [diagnostico-populacao.qmd](diagnostico-populacao.qmd).

```bash
uv run python -m src.population
uv run quarto render diagnostico-populacao.qmd
# Para reprocessar sem rede:
uv run python -m src.population --offline
```

A fonte publica 18 dos 22 anos de 2003–2024; 2007, 2010, 2022 e 2023 ficam
ausentes, **sem interpolação ou substituição por censos**. A população tem grão
município-ano e nunca deve ser somada sobre as faixas etárias dos registros.
O numerador existente mede registros (inclusive tardios), não nascimentos por
ocorrência: registros por mil habitantes **não são taxa bruta de natalidade**.
A hipótese literal depende de fonte compatível de nascimentos; uma análise do
indicador substituto deve ser explicitamente exploratória e não causal.

Escopo adotado a partir dos desafios das aulas: **1. exploração; 2. Tidy Data e
flat table; 3. desenho dimensional; 4. construção/reconciliação da gold; início
da análise descritiva pareada**. Os materiais locais contêm exercícios teóricos
da Etapa 2, não um enunciado prático próprio. Ainda faltam **inferência
confirmatória e síntese/relatório final**. Não há algoritmo treinado nem
confirmação de hipótese.

Depois de executar a primeira etapa, na raiz do projeto:

```bash
uv sync
uv run python -m src.prepare
uv run python -m src.model
uv run python -m src.analyze
uv run python -m unittest discover -s tests -v
uv run quarto render exploracao.qmd
uv run quarto render tidy.qmd
uv run quarto render estrela.qmd
uv run quarto render analise.qmd
```

| Artefato | Finalidade |
|---|---|
| `src/prepare.py` | Validação do grão, exploração 2003–2020, coorte constante, pivot/melt reversível e flat table temporal |
| `exploracao.qmd` | Cobertura, evolução, distribuições, massa no zero, idade ignorada e suspeita de São Luís em 2003 |
| `tidy.qmd` | Justificativa do formato, demonstração de melt e definição de X/y |
| `estrela.qmd` | Processo, granularidade, dimensões, medidas e verificações da carga |
| `src/model.py` | Dimensões, fato por município-ano-faixa e agregada por município-ano; valida chaves e reconcilia antes da gravação |
| `src/analyze.py` | Variações pareadas 2003–2024, rankings absolutos e sensibilidade a São Luís |
| `analise.qmd` | Avaliação descritiva dos resultados; explicita por que não há inferência confirmatória |
| `tests/` | Testes sem rede de preparação, carga dimensional, fail-stop e análise pareada |

O comando de preparação grava nove Parquets em `data/analysis/` (fora do Git):
série anual, perfil de faixas, idade ignorada, totais exploratórios, tabela larga,
tabela longa, flat table, `X` e `y`. Todos são recalculáveis, e os arquivos são
relidos e comparados depois da gravação.

A camada gold guarda seis Parquets (quatro dimensões e duas fatos), também fora
do Git. As chaves substitutas são reproduzíveis na reconstrução integral. A
fato detalhada soma 47.110 linhas e a agregada, 4.711 pares município-ano. O
modelo compara cada combinação município-ano-faixa com a trusted, além de
reconciliar linhas, registros, idade ignorada e células originalmente escritas
com traço. A dimensão anual cobre 2003–2024, mesmo quando não há fato para certo
ano ou município.

Na flat table, cada linha é um município completo em 2018–2021. `X` tem cinco
atributos calculados somente em 2018–2020; `y` indica se os registros de 2021
ficaram abaixo da média anual desse período. Nome, código e contagem futura
ficam fora de `X`. A ordem das linhas é compartilhada; a flat table preserva
identificação e contagem do alvo para auditoria. Não há treinamento.

`src/analyze.py` compara os registros de 2003 e 2024 somente para os 203
municípios com ambas as pontas aprovadas. A saída é pareada por município e
faixa; não representa o total oficial estadual. A maior redução agregada ocorre
em 25–29 anos, mas a sensibilidade retira São Luís, cuja distribuição em 2003
foi sinalizada no relatório da primeira fase. A ordem das faixas não muda, mas
o tamanho do recuo se reduz.

Essa comparação é **descritiva, não confirmatória**: os dados já haviam sido
examinados, a quarentena usa a série inteira, não há mínimo de relevância
prática definido com o gestor e não existe holdout independente. Não são
calculados valor-p ou intervalos como se fossem confirmação nova. A próxima
etapa depende de hipótese prospectiva, dados novos e limiar de decisão acordado.

### Cuidados de interpretação

- Lacunas de quarentena **não são zeros**. A cobertura anual varia; por isso a
	exploração também acompanha os mesmos municípios em todos os anos.
- `total_municipio_ano` repete-se dez vezes na trusted: somá-lo sobre as faixas
	multiplica o total por dez. As análises somam `nascidos`.
- As somas municipais aprovadas não equivalem ao total oficial do estado.
- Os anos 2022–2024 ficam fora da nova exploração, mas não são holdout intocado:
	o diagnóstico anterior já os examinou e a quarentena usa toda a série. Não
	alegar confirmação independente nem ausência de vazamento global.
- O relatório anterior apontou a concentração de São Luís/2003 em 25–29 anos
	como suspeita ainda não resolvida. Ela é reavaliada, sem correção automática.
- Registros tardios, idade ignorada, pandemia e seleção pela quarentena
	permanecem limitações; nenhuma variação é interpretada como efeito causal.

Os materiais de aula em `/docs/`, o roteiro privado e os HTML renderizados
ficam fora do versionamento. Os QMD, código e testes são os artefatos públicos
reproduzíveis. Esta etapa foi preparada com auxílio do GitHub Copilot para
leitura dos materiais, implementação e validação; decisões analíticas ainda
dependem de revisão da equipe.

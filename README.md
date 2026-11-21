# Natalidade — Maranhão

Introdução à Ciência de Dados · Sistemas de Informação · IFMA.

**Pergunta original:** entre 2003 e 2024, em que municípios do Maranhão e faixas
de idade materna os registros de nascidos vivos mais caíram?

**Equipe:** Gustavo dos Santos Bandeira Rocha (20231SI0006), Deusiane Pimenta
Rocha (20231SI0032), Felipe Moura de Oliveira (20231SI0027).

## Entrega da atividade 02

- [Relatório em PDF](relatorios/relatorio-etapa-2.pdf): cinco partes do enunciado,
  motivos das decisões, dificuldades, desenho e duas saídas reais do modelo.
- [Fonte do relatório](relatorios/relatorio-etapa-2.qmd).
- [Revisão dos requisitos e funções das aulas](relatorios/revisao-etapa-2.md).
- [Evidências de execução e SHA-256](relatorios/evidencias-etapa-2.json).

**Status:** núcleo técnico revisado, 49 testes aprovados, sequência oficial
verificada em cópia limpa com nova coleta. **Não se garante cumprimento literal
da reserva intocada:** diagnóstico, quarentena global, alvo 2021 e análises
anteriores já examinaram 2021–2024. Essa exposição não pode ser desfeita. As
previsões desta revisão são pós-exploratórias; não foram confirmadas na exploração.
O enunciado reserva confirmação à Etapa 3, não exige confirmar hipótese na Etapa 2.

Branch: **etapa-2**. Nenhum documento de /docs é rastreado nesta branch. A equipe
ainda deve conferir acesso privado do professor (`josenildosilva`) e enviar
link/PDF no Classroom. Não foi feito push nem convite automático.

## Fonte principal e chave de acesso

IBGE/SIDRA [tabela 2609](https://sidra.ibge.gov.br/tabela/2609), variável 217,
Estatísticas do Registro Civil, municípios do Maranhão (UF 21), 2003–2024.
Conta **nascidos vivos registrados no ano**, inclusive nascimentos anteriores.
Sem chave/cadastro; [.env.example](.env.example) é informativo, sem credenciais.

## Reprodução: sequência oficial do clone ao gold

Requer [uv](https://docs.astral.sh/uv/). Executar a partir da raiz:

```bash
git clone --branch etapa-2 https://github.com/lipefemoura/natalidade.git
cd natalidade
uv sync
uv run python src/ingest.py
uv run quarto render analises/diagnostico.qmd
uv run python src/transform.py
uv run quarto render analises/exploracao.qmd
uv run python src/model.py
```

Não é necessário copiar ou preencher .env. `_quarto.yml` mantém execução dos QMD
na raiz, mesmo com documentos em `analises/`. Em reprodução limpa de 21/11/2026,
todos os seis comandos pós-clone retornaram saída 0, com raw/trusted/gold novas.
Essa verificação foi de uma cópia limpa, não do acesso remoto privado.

### O que cada etapa faz

| Etapa | Artefatos e decisões |
|---|---|
| [src/ingest.py](src/ingest.py) | JSON por ano em raw/ibge_sidra_2609/AAAA-MM-DD, fonte/URL/horário UTC; timeout/retry e cache diário |
| [analises/diagnostico.qmd](analises/diagnostico.qmd) | Perfil, duplicação, decisões e diagnóstico; CSV de municípios-ano atípicos |
| [src/transform.py](src/transform.py) | Contrato Pandera, trusted e quarentena; dez faixas sem Total/idades simples; traço vira zero marcado |
| [analises/exploracao.qmd](analises/exploracao.qmd) | Views sem reserva; perguntas e expectativas; varredura, crosstabs, quarentena e previsões para depois |
| [src/model.py](src/model.py) | Dimensões/fatos/agregada, conferência de chaves e medidas, staging/releitura e Parquets gold |

### Dicionário trusted e quarentena

Grão: **município × ano × faixa materna**, 47.110 linhas na coleta de referência
16/11/2026; soma de registros aprovados = 2.773.381. Colunas:

| Coluna | Tipo e significado |
|---|---|
| cod_municipio | Texto, código IBGE de sete dígitos, prefixo 21 |
| municipio | Nome, sem sufixo UF |
| ano | Inteiro, ano do registro 2003–2024 |
| faixa_idade_mae | Nove faixas de idade e Ignorada |
| nascidos | Inteiro não negativo, registros |
| valor_era_traco | Booleano, zero originalmente publicado como traço |
| total_municipio_ano | Inteiro, total municipal repetido dez vezes; NÃO somar sobre faixas |

Quarentena tem as mesmas colunas, `motivo` e `detectado_em` UTC (630 linhas,
63 municípios-ano na referência). Reprovação de uma faixa leva o par inteiro
para evitar soma parcial. Motivos: participação atípica <0,25 ou >3 vezes a
mediana municipal; violação de contrato; faixa que acompanha outra reprovada.
Mudança estrutural/símbolo desconhecido interrompe sem publicar trusted nova.
Não se imputam lacunas nem se apagam extremos legítimos por conveniência.

## Tabelas em data/gold/

| Tabela | Grão, chave e medidas |
|---|---|
| dim_municipio | 217 municípios; municipio_sk, código/nome/UF/região |
| dim_ano | 22 anos 2003–2024 inclusive; ano_sk = ano natural, década |
| dim_faixa_idade | Dez faixas; faixa_sk, rótulo/ordem/idade conhecida |
| dim_origem_valor | Duas origens; origem_sk, indicador de traço/descrição |
| fato_registros | 47.110 células; município/ano/faixa/origem, nascidos |
| fato_registros_municipio_ano | 4.711 pares; município/ano, registros, registros_idade_ignorada, celulas_era_traco |

O comando padrão gera **seis arquivos**, sem depender da população opcional.
Somente `src/model.py` produz a gold. A dimensão anual usa `generate_series`
inclusivo independentemente de eventos. Outras SK são determinísticas para
reconstrução integral. `TABELAS_TRUSTED`, `TABELAS_GOLD`, `CHAVES`, `CONFERENCIA`
e `dimensoes()`, `fatos()`, `agregada()` seguem a organização da aula 09.
`fatos()` preserva a API anterior de retorno central/resumo, delegando o resumo
à função `agregada()`. Medidas são conferidas por soma e por grupo, não só globalmente.

## Verificações e documentos complementares

```bash
uv run python -m unittest discover -s tests -v
uv run python -m src.prepare
uv run quarto render analises/tidy.qmd
uv run quarto render analises/estrela.qmd
# Falha esperada: ano ausente; encerra com código 1 e preserva gold
uv run python src/model.py --remover-ano-dimensao 2024
```

[src/prepare.py](src/prepare.py) publica tabelas exploratórias, pivot/melt
reversível e flat temporal em data/analysis/. X usa 2018–2020, y indica queda
em 2021. Código/nome/futuro não entram em X; não há treinamento. Essa separação
local não desfaz a seleção global da quarentena nem o uso anterior da reserva.

## Extensão populacional (opcional, além do núcleo da atividade)

**Hipótese adicional:** há correlação entre crescimento da cidade e queda da
taxa de natalidade. Crescimento aqui significa população residente, não
urbanização/PIB. A fonte IBGE Agregados v3
[6579/9324](https://servicodados.ibge.gov.br/api/v3/agregados/6579/metadados)
fornece 3.906 células (217 municípios × 18 anos publicados), coleta 19/11/2026.
Não publica 2007/2010/2022/2023; sem interpolação/mistura com censos. Nenhuma
linha rejeitada; 78 saltos anualizados >10% apenas sinalizados.

```bash
uv run python -m src.population
# Ou, se a raw já existe e não se deseja nova coleta:
uv run python -m src.population --offline
uv run quarto render analises/diagnostico-populacao.qmd
uv run python src/model.py --com-populacao
uv run python -m src.population_analysis
uv run quarto render analises/hipotese-populacao.qmd
```

`--com-populacao` gera a **sétima tabela** `fato_populacao`, no grão município-ano,
com população e identificadores tabela/variável; compartilha dim_municipio e
dim_ano. População é somável entre municípios do mesmo ano, não ao longo do
tempo; nunca é repetida por faixa. `src.population_analysis` chama a construção
do próprio `src/model.py`, não gera gold por outro meio. O painel agrega primeiro
registros e depois audita LEFT/OUTER JOIN 1:1. Saídas: painel, cobertura, pontas,
correlações, correlações anuais, flat, X e y em data/analysis/hipotese_populacao/.

O [relatório de extensão](analises/hipotese-populacao.qmd) preserva análises
**anteriores/pós-exploratórias**, não confirmação nova da reserva desta atividade.
2003–2024 (203 municípios): Pearson 0,2886, p bilateral 0,00002973, IC95%
nominal [0,1571; 0,4100]; Spearman 0,1678, p=0,01669. Holm em 24 testes de pontas
produz p=0,0003271/0,09558; anuais têm família separada. Em 2011–2021 os valores-p
são 0,8518/0,2825. Testes nominais não corrigem seleção, dependência espacial ou
acoplamento matemático (controle numerador fixo: Pearson 0,8436).

**Não se confirma natalidade literal** com o indicador de registros por mil:
registro tardio, migração, estrutura etária e revisões são limitações. Testar
correlação nula não prova mecanismo causal. A aula 10 ensina comparação por
bootstrap/permutação; esses laços de grupos não foram alegados como implementados.
Os testes SciPy são complemento explicitamente nominal, não requisito da atividade 02.

## Gerar PDF e evidências da entrega

```bash
# Requer a trusted de população para documentar também a extensão
uv run python -m src.audit_stage2 --reproduzir-coleta
uv run quarto render relatorios/relatorio-etapa-2.qmd
```

O gerador audit usa a CLI real do modelo com ano 2024 removido só em memória,
compara hashes antes/depois e reconstrói após apagar gold temporária. Também
executa a sequência oficial com nova coleta em cópia limpa. Não muda os JSON
da coleta de referência. O PDF usa Typst fornecido pelo Quarto; não exige LaTeX.

## Estrutura e interpretação

raw é imutável por coleta; trusted é validada; quarentena preserva reprovados;
gold contém tabelas dimensionais; data/analysis contém auxiliares recalculáveis.
QMD em analises/, PDF/evidências em relatorios/. Dados, HTML, .env, .venv e
material privado em /docs ficam fora do Git. Um documento de docs antes rastreado
foi retirado do índice nesta branch, mantendo cópia local; commits passados não
foram reescritos. [analises/analise.qmd](analises/analise.qmd) conserva o ranking
descritivo antigo, com sensibilidade a São Luís/2003, não confirmação independente.

Uso de IA: GitHub Copilot auxiliou revisão, implementação e relatório; a equipe
é responsável por validar interpretação, evidências e submissão acadêmica.
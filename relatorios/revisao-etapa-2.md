# Revisão contra o enunciado da Atividade 02 — 21/11/2026

## Critérios e evidências

| Critério | Evidência implementada/verificada | Situação |
|---|---|---|
| Sequência clone → gold | Cópia limpa sem dados, nova coleta e seis comandos oficiais com saída 0; evidências JSON | Técnica verificada; clone remoto/permissão do professor não verificados |
| Organização | QMD em analises/, _quarto.yml com execute-dir: project, README, env.example e uv.lock | Atendido |
| Exploração | Views excluem 2021–2024, três perguntas/colunas/expectativas, univariadas → duas/três colunas → crosstabs; quarentena relida; previsões e perguntas para depois | Estrutura atendida; reserva já exposta e expectativas pós-exploratórias impedem cumprimento literal de independência |
| Modelo | Seis itens de desenho no PDF; dimensoes/fatos/agregada e TABELAS_TRUSTED/GOLD, CHAVES, CONFERENCIA explícitas | Atendido, com adaptação anual e API fatos compatível documentadas |
| Gold | Gerada exclusivamente por src/model.py; reconciliação por célula e por soma; falha controlada 2024 sem publicar; rebuild byte a byte SHA-256 | Atendido |
| Relatório | PDF de cinco partes, identificação completa, antes/depois, modelo e saídas reais | Produzido e relido com pdftotext |
| Mesma fonte | SIDRA 2609 permanece núcleo; população opcional com comando adicional documentado | Extensão declarada, não exigida no enunciado |
| /docs privado | Nenhum arquivo de docs rastreado na branch; cópias locais preservadas | Retirada de rastreamento, sem apagar histórico anterior |

## Funções recomendadas e uso real

- Aulas 02–03: uv sync/lock, requests.get, timeout, retry/backoff 429/5xx,
  proveniência JSON e cache idempotente em src/ingest.py e src/population.py.
- Aulas 04–05: isna, duplicated, diagnóstico por município, Pandera
  DataFrameSchema/Check, quarentena com motivo/detectado_em e fail-stop estrutural.
- Exploração (enunciado): DuckDB CREATE VIEW/read_parquet, SUMMARIZE no diagnóstico;
  pandas describe/value_counts/groupby/agg/crosstab e matplotlib hist/boxplot/plot/barh.
  As consultas novas do documento obrigatório nunca leem a reserva para conferir previsões.
- Aula 07: groupby/agg, pivot/melt reversível e merge com validate/indicator.
  A trusted já é tidy; não transformar sem necessidade nem repetir população por faixa.
- Aulas 08–09: dimensoes/fatos/agregada; DuckDB ROW_NUMBER e generate_series
  inclusivo; LEFT JOIN + verificações prévias, listas de tabelas/chaves/conferência;
  contagem e soma trusted/gold; Parquet relido antes de publicação.
  Grão anual usa ano natural, não data fictícia. Fatos retornam tupla central/resumo
  para preservar API, mas resumo é calculado pela função agregada separada.
- Aula 10: interpretação de intervalo, hipótese nula, p e mínimo relevante;
  o núcleo da atividade 02 NÃO executa confirmação na reserva. Bootstrap/permutação
  de grupos ensinados na aula não foram alegados como implementados: a extensão
  de correlações usa SciPy pearsonr/spearmanr, IC Fisher e Holm nominal, com suposições
  explícitas. Não misturar esse complemento com confirmação prospectiva.

## Pendências que código não resolve

1. Os anos de reserva e a série global já foram examinados: não é honesto dizer
   que a reserva ficou intocada. Necessária revisão com professor e novo período/dado
   para confirmação futura; não podemos garantir pontuação máxima nesse critério.
2. Não há retorno docente da Etapa 1 localizado; não inventar correções feitas.
3. Suspeita de distribuição em São Luís/2003 e compatibilidade de numerador
   natalidade/denominador permanecem questões de domínio.
4. Acesso do professor josenildosilva ao repositório privado e submissão do PDF/link
   no Classroom dependem de ações da equipe. Não foram feitos push ou convite.

## Artefatos de entrega

- PDF: relatorios/relatorio-etapa-2.pdf; fonte: relatorios/relatorio-etapa-2.qmd.
- Saídas reais e hashes: relatorios/evidencias-etapa-2.json.
- Núcleo: analises/diagnostico.qmd, analises/exploracao.qmd, analises/estrela.qmd, src/model.py.
- Extensão: analises/diagnostico-populacao.qmd, analises/hipotese-populacao.qmd,
  src/population.py e src/population_analysis.py. Mantém resultados antigos como
  exploratórios pós-seleção, não novas verificações da reserva da atividade.
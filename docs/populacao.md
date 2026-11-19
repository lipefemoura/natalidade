# Nova fonte — população residente estimada (Etapa 1)

## Pergunta e operacionalização

Hipótese proposta: **“Há correlação entre o crescimento da cidade e a queda da
taxa de natalidade”**. Crescimento será operacionalizado como variação da
população residente do município; não mede expansão da área urbana nem atividade
econômica. Com a fonte atual de registros civis, somente a associação com
**registros por mil habitantes** pode ser explorada, sem chamar isso de taxa
bruta de natalidade. Nascimentos ocorridos no ano por residência materna são
necessários para avaliar a hipótese literalmente.

## Referências oficiais verificadas

- [Documentação Agregados v3](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3)
- [Tabela SIDRA 6579](https://sidra.ibge.gov.br/tabela/6579)
- [Metadados](https://servicodados.ibge.gov.br/api/v3/agregados/6579/metadados)
- [Períodos](https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos)
- [Consulta exemplo](https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/2003%7C2024/variaveis/9324?localidades=N6%5BN3%5B21%5D%5D)

Agregado 6579, variável 9324, Pessoas, estimativa de população residente total;
sem classificação de sexo/idade; N6 dos municípios da UF 21 (Maranhão).
Sem cadastro, token ou pacote novo. Os metadados e períodos consultados também
são preservados na raw: uma futura atualização não apaga a evidência utilizada.

## Alinhamento às aulas 02–05

1. **Infraestrutura:** ambiente uv existente, dependências declaradas, raw
   separada de trusted/quarentena; comandos reproduzíveis na raiz.
2. **Coleta:** `src/population.py` reaproveita o cliente HTTP com timeout 120 s,
   quatro tentativas e backoff exponencial (429 respeita Retry-After numérico;
   401/403 e demais 4xx são terminais). Três chamadas: metadados, períodos e
   valores. Consulta de 3.906 valores, abaixo do limite de 100.000 da API,
   sem paginação. Cache por dia, envelope de fonte/URL/horário UTC/payload;
   reexecução não duplica nem sobrescreve os arquivos existentes.
3. **Diagnóstico:** `diagnostico-populacao.qmd` mostra perfil, nulos, duplicatas,
   cobertura, decisões e saltos sinalizados. Não imputa, não winsoriza e não
   elimina municípios grandes. Mudanças anualizadas >10% em módulo apenas
   sinalizam revisão: não há evidência suficiente de erro para excluí-las.
4. **Contrato:** Pandera estrito na fronteira, população inteira positiva,
   chave única município-ano, domínio anual e proveniência da medida;
   verificações estruturais antes do contrato e reconciliação antes da publicação.

## Cobertura temporal e decisões

2003–2024 contém **18 anos publicados** e **217 municípios**: 3.906 células
esperadas. A tabela não fornece 2007, 2010, 2022 ou 2023. Não é erro de rede:
esses anos não constam do endpoint de períodos. Não completar por interpolação,
nem misturar automaticamente Censo/Contagem (referências e métodos distintos).
Para análises longitudinais, somente pares explicitamente presentes são válidos;
variações anuais só podem usar anos consecutivos. Pontas 2003/2024 existem.

Estimativas de diferentes anos podem incorporar bases censitárias, revisões e
mudanças territoriais distintas. Não se trata de uma série retrospectivamente
harmonizada. Crescimento calculado entre pontas é descritivo da série publicada,
não uma estimativa livre dessas quebras. Não inferir causalidade.

## Dicionário trusted

| Coluna | Tipo | Regra |
|---|---|---|
| cod_municipio | texto | Sete dígitos, prefixo 21; chave junto com ano |
| municipio | texto | Nome, acentos preservados; sem sufixo da UF |
| ano | inteiro | Ano publicado dentro de 2003–2024 |
| populacao | inteiro | Pessoas, estritamente positivo |
| tabela | texto | Constante 6579 |
| variavel | texto | Constante 9324 |

Grão: município × ano. População é aditiva entre municípios no **mesmo ano**,
mas não ao longo do tempo. Nunca duplicar população nas dez faixas de registros.
Zero numérico ou `-` (zero real) é preservado em quarentena como denominador
inválido. `..`, `...`, `X` recebem motivos distintos e valor original; não viram
zero. Símbolo desconhecido, unidade/nivel/classificação inesperada, perda de
cobertura e duplicata conflitante interrompem antes de publicar trusted nova.
Duplicatas idênticas são removidas e contadas. Mudanças na lista de anos
exigem revisão explícita, não ampliação silenciosa da janela analítica.

## Artefatos e reprodução

- `uv run python -m src.population`: coleta e transformação.
- `uv run python -m src.population --offline`: reprocessa a última coleta local.
- `uv run quarto render diagnostico-populacao.qmd`: diagnóstico completo.
- `uv run python -m unittest discover -s tests -v`: testes sem rede.

Raw: `data/raw/ibge_agregados_6579/AAAA-MM-DD/{metadados,periodos,populacao}.json`.
Trusted: `data/trusted/populacao.parquet`. Quarentena:
`data/quarentena/populacao.parquet`, com valor original, motivo e detectado_em.
Auditoria: `data/analysis/diagnostico_populacao.json` e
`data/analysis/perfil_populacao.parquet`. Publicação só após validar/reler todos
os Parquets em staging de arquivo; não se promete transação atômica entre
diretórios em caso de falha física durante as substituições.

## Resultado verificado em 2026-11-19

Coleta real: **3.906 células**, 217 municípios, 18 anos; nenhuma duplicata,
nenhum nulo/símbolo/zero e nenhuma linha em quarentena. Trusted com 3.906 linhas;
zero imputações e winsorizações. Foram sinalizadas **78 mudanças anualizadas**
acima de 10% em módulo, mantidas para sensibilidade/revisão. Coleta online e
reprocessamento offline produziram as mesmas contagens; diagnóstico renderizado
com sucesso. Os testes cobrem símbolos, cobertura, duplicação, unidade, cache
diário e anualização de intervalos não consecutivos.

## Critérios de parada e hipótese pendente

Erro de rede persistente, perda de cobertura, mudança de semântica/schema ou
chave conflitante interrompe a execução com mensagem. Os quatro anos ausentes
estão documentados e não impedem análises de pares disponíveis. A hipótese
literal permanece pendente de numerador compatível: o indicador de registros
é apresentado separadamente, nunca como natalidade medida ou confirmação.

## Etapa 2 — integração e resultados exploratórios

Executar `uv run python -m src.population_analysis` e
`uv run quarto render hipotese-populacao.qmd`. O primeiro comando reconstrói
a gold e grava o painel e análises em `data/analysis/hipotese_populacao/`.
O relatório reproduzível `hipotese-populacao.qmd` documenta Tidy/flat, dimensões,
fatos, junções, definições e limitações. O grão populacional permanece em fato
própria, com dimensões conformadas; nunca há população por faixa artificial.

Auditoria real: 3.850 pares município-ano com ambas as fontes; 56 populações
sem registros aprovados; 861 registros agregados sem população (anos não
publicados). Nenhum caso é substituído por zero. Há 203 municípios nas pontas
2003/2024. Queda positiva = indicador inicial menos final.

| Cenário | n | Pearson crescimento × queda do indicador | Spearman |
|---|---:|---:|---:|
| 2003–2024, todos pareados | 203 | 0,2886 | 0,1678 |
| 2003–2024, sem São Luís | 202 | 0,2887 | 0,1694 |
| 2003–2024, sem saltos populacionais sinalizados | 153 | 0,2059 | 0,1398 |
| 2011–2021, pareados | 212 | 0,0129 | −0,0741 |

O sinal/tamanho depende da janela. Ademais, mantendo os registros iniciais
constantes e variando somente o denominador, Pearson é **0,8436** nas pontas:
isso ilustra forte associação matemática mesmo sem queda do numerador.
No contraste com queda percentual dos próprios registros (sem população no
desfecho), Pearson é **−0,3009**, e Spearman **−0,2989** em 2003–2024.
Não atribuir a associação observada a comportamento reprodutivo ou urbanização.

A flat temporal usa atributos de 2018–2020 e alvo de queda do indicador em
2021, mantendo identificação e valor futuro fora de X. Não há treinamento,
inferência confirmatória nem teste de significância. Correlações anuais usam
apenas pares consecutivos publicados, separadamente por intervalo.

**Conclusão:** a fonte populacional foi integrada com sucesso; a hipótese
literal de natalidade não foi confirmada nem refutada e continua dependendo
de um numerador de nascimentos ocorridos por residência materna. Não foi
introduzida outra fonte sem revisão da equipe.
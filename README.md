# natalidade

Projeto da disciplina Introdução à Ciência de Dados (IFMA).

## Requisitos

- Instalar o gerenciador de pacotes [uv](https://docs.astral.sh/uv/)

## Como rodar

```bash
git clone <url-do-repositorio>
cd natalidade
uv sync
uv run python src/ingest.py
```

## Configuração

Crie um arquivo `.env` na raiz do projeto com a variável `CSV_PATH`, que aponta para
o CSV a ser lido. O jeito mais simples é copiar o modelo:

```bash
cp .env.example .env
```

O `.env` não é versionado. Se `CSV_PATH` não estiver definida, o script para com
`KeyError`.

## Dados

O conteúdo de `data/raw/` não é versionado, então o clone chega com a pasta vazia.
Coloque ali o CSV indicado em `CSV_PATH`. Para o exemplo padrão, crie
`data/raw/exemplo.csv` com:

```csv
ano,nascidos
2022,100
2023,95
2024,90
```

## Estrutura

```
data/raw/       dado bruto, imutável: nunca editar, nunca deletar
data/trusted/   dado limpo e checado
src/ingest.py   da fonte para data/raw/
src/transform.py  de data/raw/ para data/trusted/
docs/           análise
```

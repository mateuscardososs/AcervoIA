# AcervoIA

Aplicação web para consultar manuais e procedimentos técnicos com respostas apoiadas por trechos verificáveis.

## Estado do projeto

- [x] Escopo da primeira entrega documentado.
- [x] Acervo demonstrativo fictício preparado.
- [x] Amostra inicial de 30 perguntas definida: 25 respondíveis e 5 sem evidência.
- [x] API mínima com endpoint de saúde e teste HTTP.
- [ ] Banco e persistência.

Veja [`docs/escopo-mvp.md`](docs/escopo-mvp.md) e [`docs/avaliacao-inicial.md`](docs/avaliacao-inicial.md).

## Acervo demonstrativo

Os manuais em [`data/demo/`](data/demo/) descrevem equipamentos inventados exclusivamente para testes. Não use seus valores ou procedimentos em equipamentos reais. Cada arquivo TXT tem seções estáveis para que a avaliação continue válida mesmo se a estratégia de divisão em trechos mudar.

## Executar a API mínima

Requer Python 3.12 ou superior dentro da faixa declarada em `pyproject.toml`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn acervo_ia.main:app --reload --app-dir src
```

Abra `http://127.0.0.1:8000/health`. A documentação interativa da API fica em `http://127.0.0.1:8000/docs`.

Em outro terminal, com o ambiente virtual ativado:

```bash
pytest
```

O endpoint atual confirma apenas que a API está respondendo. Ainda não verifica PostgreSQL nem Ollama.

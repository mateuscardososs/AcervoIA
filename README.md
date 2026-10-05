# AcervoIA

Aplicação web para consultar manuais e procedimentos técnicos com respostas apoiadas por trechos verificáveis.

## Estado do projeto

- [x] Escopo da primeira entrega documentado.
- [x] Acervo demonstrativo fictício preparado.
- [x] Amostra inicial de 30 perguntas definida: 25 respondíveis e 5 sem evidência.
- [x] API mínima com endpoint de saúde e teste HTTP.
- [x] Persistência inicial e base de autenticação.

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

`/health` confirma que a API está respondendo; `/health/database` verifica o PostgreSQL. A API ainda não verifica Ollama.

## Autenticação

O login usa `POST /auth/token` com formulário OAuth2 (`username` recebe o e-mail e `password` a senha). O endpoint retorna um bearer token JWT válido por 30 minutos. Envie-o no cabeçalho `Authorization: Bearer <token>`; `GET /auth/me` retorna o ID e o e-mail da conta autenticada.

As senhas são armazenadas com hash Argon2. Configure `AUTH_SECRET_KEY` no ambiente do processo com uma chave aleatória de pelo menos 32 bytes. Gere uma com `openssl rand -hex 32`; mantenha o resultado fora do Git e nunca o compartilhe. Para carregar variáveis do `.env` local ao iniciar a API, use `uvicorn acervo_ia.main:app --reload --app-dir src --env-file .env`.

Para criar uma conta local sem rota de cadastro público, execute `.venv/bin/python -m acervo_ia.cli`. O comando pede o e-mail e solicita a senha duas vezes sem exibi-la.

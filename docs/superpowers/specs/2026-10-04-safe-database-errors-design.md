# Tratamento seguro de erros de conexão

## Objetivo

Impedir que `DATABASE_URL`, senhas ou strings de conexão apareçam em respostas
HTTP, logs ou tracebacks registrados pela aplicação quando uma conexão com o
PostgreSQL falhar.

## Escopo

A alteração cobre o caminho de verificação de banco já existente:
`GET /health/database` → `ping_database()` → SQLAlchemy/Psycopg. Não adiciona
autenticação, rotas de coleções, filtros globais de logging ou mudanças no
Alembic.

## Desenho

`acervo_ia.db.connection` definirá `DatabaseUnavailableError`, uma exceção da
aplicação cuja mensagem não contém dados da conexão. `ping_database()`
capturará `SQLAlchemyError` e a converterá para essa exceção usando
`raise ... from None`, removendo a exceção potencialmente sensível do traceback
apresentado.

A ausência de `DATABASE_URL` também produzirá `DatabaseUnavailableError` com
mensagem genérica. A URL continuará sendo usada somente para construir o
engine e não será registrada.

`acervo_ia.api.routes.health` capturará somente
`DatabaseUnavailableError`. A rota registrará um aviso constante, sem incluir
a exceção, argumentos, traceback ou `exc_info`. A resposta continuará sendo
`503` com a mensagem genérica atual e será levantada com `from None`.

## Teste de segurança

Um teste integrado substituirá o engine por um objeto que lança
`sqlalchemy.exc.OperationalError` contendo uma senha sentinela. O teste fará
uma requisição real com `TestClient` e verificará simultaneamente:

- status HTTP `503`;
- corpo com apenas a mensagem genérica;
- ausência da senha sentinela no corpo da resposta;
- ausência da senha sentinela nos registros capturados por `caplog`;
- presença do aviso seguro e constante.

O teste não carregará nem exibirá o `.env`.

## Verificação

A implementação será validada com o novo teste isolado, a suíte completa e
`git diff --check`. A revisão final também procurará usos de `exc_info`,
interpolação de exceções e encadeamento inseguro no caminho de conexão.

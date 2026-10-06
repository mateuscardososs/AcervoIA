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

`/health` confirma que a API está respondendo; `/health/database` verifica o PostgreSQL.

## Autenticação

O login usa `POST /auth/token` com formulário OAuth2 (`username` recebe o e-mail e `password` a senha). O endpoint retorna um bearer token JWT válido por 30 minutos. Envie-o no cabeçalho `Authorization: Bearer <token>`; `GET /auth/me` retorna o ID e o e-mail da conta autenticada.

As senhas são armazenadas com hash Argon2. Configure `AUTH_SECRET_KEY` no ambiente do processo com uma chave aleatória de pelo menos 32 bytes. Gere uma com `openssl rand -hex 32`; mantenha o resultado fora do Git e nunca o compartilhe. Para carregar variáveis do `.env` local ao iniciar a API, use `uvicorn acervo_ia.main:app --reload --app-dir src --env-file .env`.

Para criar uma conta local sem rota de cadastro público, execute `.venv/bin/python -m acervo_ia.cli`. O comando pede o e-mail e solicita a senha duas vezes sem exibi-la.

## Processar documentos e buscar trechos

O PostgreSQL do Compose usa a imagem `pgvector/pgvector`; após aplicar as migrações, cada trecho pode guardar um vetor de 768 dimensões e o nome do modelo que o gerou. A configuração padrão usa o Ollama local em `http://127.0.0.1:11434` e o modelo `embeddinggemma` (Ollama 0.11.10 ou superior). Inicie o Ollama, baixe o modelo com `ollama pull embeddinggemma` e configure `OLLAMA_BASE_URL` ou `OLLAMA_EMBEDDING_MODEL` no ambiente da API se necessário. A dimensão do modelo precisa continuar em 768 nesta versão; mudar essa dimensão exige uma migração de banco correspondente.

No `/docs`, autentique-se com o botão **Authorize** usando o token obtido em `POST /auth/token`. Crie uma coleção e envie um PDF, DOCX ou TXT pela rota de documentos. Processe-o em `POST /collections/{collection_id}/documents/{document_id}/process`; depois gere ou atualize um vetor por trecho em `POST /collections/{collection_id}/documents/{document_id}/embeddings`. Por fim, envie `{ "query": "sua pergunta", "limit": 5 }` para `POST /collections/{collection_id}/search`. A estratégia padrão é híbrida; o campo opcional `strategy` permite escolher `vector`, `text` ou `hybrid`. A resposta inclui nome do documento, página quando disponível e pontuação. Esta etapa só recupera evidências; não gera resposta com modelo de chat. As rotas verificam a propriedade da coleção pelo usuário autenticado.

Para perguntas com resposta fundamentada, configure `OLLAMA_CHAT_MODEL` (padrão `qwen2.5:3b`) e baixe esse modelo no Ollama, por exemplo `ollama pull qwen2.5:3b`. Depois de processar e vetorizar os documentos, use `POST /collections/{collection_id}/ask` no `/docs` com `{ "question": "Como calibro o equipamento?", "limit": 5 }`. A resposta contém marcadores `[S1]` e a lista `sources` com documento, página quando disponível e trecho, montada pelo backend. Se nenhum trecho for recuperado, a API informa que não há evidência suficiente sem chamar o modelo de chat. Respostas com fontes desconhecidas ou não citadas são rejeitadas.

### Estratégias de busca e benchmark

`POST /collections/{collection_id}/search` aceita `strategy`: `vector`, `text` ou `hybrid`; o padrão é `hybrid`. A busca textual combina full-text search do PostgreSQL (configuração `simple`, índice GIN) com correspondência literal normalizada de códigos, siglas e modelos, usando Reciprocal Rank Fusion (RRF). A busca híbrida combina os rankings textual e vetorial por RRF. O `/ask` também usa a busca híbrida. Os três modos validam primeiro a propriedade da coleção; `text` não precisa chamar o Ollama de embeddings.

Após iniciar PostgreSQL e Ollama, instalar o modelo configurado e aplicar as migrações com `.venv/bin/alembic upgrade head`, execute a avaliação reproduzível:

```bash
.venv/bin/python scripts/evaluate_retrieval.py
```

O comando reutiliza os manuais fictícios e as 30 perguntas de `data/demo/`. Gera embeddings com o Ollama configurado e executa as três estratégias no PostgreSQL local. Usuário, coleções, documentos, trechos e vetores da avaliação ficam em uma única transação que é sempre revertida; nada do benchmark é persistido. Os testes automatizados simulam o provedor e não precisam do Ollama: `.venv/bin/python -m pytest`.

O resultado de referência da execução local de 2026-10-05 está registrado em [`docs/avaliacao-inicial.md`](docs/avaliacao-inicial.md). É um diagnóstico dos 25 exemplos respondíveis, não uma alegação de qualidade geral; a métrica não mede a qualidade de respostas geradas.

## Interface web

A SPA React/TypeScript fica em `web/`. O Vite serve a interface em `http://127.0.0.1:5173` e encaminha `/api` para a API local em `http://127.0.0.1:8000`; para outro destino de desenvolvimento, configure `VITE_DEV_API_TARGET` no ambiente do Vite. O navegador guarda o bearer token somente em `sessionStorage`; a API continua responsável por autenticar cada requisição e filtrar coleções e documentos pela conta do token.

Em um terminal, inicie a API e o Ollama conforme as instruções acima. Crie a primeira conta pelo comando privado `.venv/bin/python -m acervo_ia.cli`. Em outro terminal:

```bash
cd web
npm install
npm run dev
```

Abra `http://127.0.0.1:5173`, entre com essa conta e crie uma coleção. Dentro dela, envie um PDF, DOCX ou TXT de até 20 MiB, abra os detalhes e escolha **Processar documento**. A interface extrai os trechos e solicita os vetores ao Ollama; se o Ollama estiver indisponível, o documento processado permanece e os vetores podem ser tentados novamente.

Na tela **Consultar coleção**, faça uma pergunta. É possível selecionar busca vetorial, textual ou híbrida; a vetorial é a opção inicial porque obteve os melhores resultados neste benchmark local específico (25 perguntas respondíveis e dois manuais fictícios), sem indicar superioridade geral. A resposta só apresenta fontes devolvidas e validadas pelo backend, com documento, página quando disponível e trecho recuperado.

Valide a interface com `cd web && npm test`, `npm run typecheck` e `npm run build`. O comando `npm run build` executa a verificação de tipos antes de gerar os arquivos em `web/dist/`.

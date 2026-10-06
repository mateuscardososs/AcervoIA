# Busca híbrida e benchmark reproduzível — plano de implementação

> **Execução:** inline nesta sessão; sem commit nem push, conforme solicitação.

**Objetivo:** adicionar busca textual PostgreSQL e literal normalizada, fundir rankings com Reciprocal Rank Fusion e comparar vetor, texto e híbrida em corpus fictício reproduzível.

**Arquitetura:** manter o pgvector existente; consultar full-text com `to_tsvector('simple', content)` e `websearch_to_tsquery`, indexando a expressão com GIN. Uma lista lexical combina FTS e identificadores literais por RRF; a modalidade híbrida combina essa lista com ranking vetorial por RRF. O endpoint de busca expõe `vector`, `text` e `hybrid`; `/ask` usa híbrida. O benchmark usa os dois manuais e as 30 perguntas já existentes e reverte a transação que semeia registros temporários.

**Tecnologias:** FastAPI, SQLAlchemy, PostgreSQL 18, pgvector, Ollama para embeddings apenas no benchmark, pytest e JSON.

## Restrições

- Preservar `README.md`, `src/acervo_ia/config.py`, `src/acervo_ia/main.py` e arquivos RAG não commitados existentes.
- Não abrir/exibir `.env`; não fazer commit nem push.
- Testes automatizados não dependem do Ollama.
- O benchmark só usa `data/demo/manual-orion-b20-v1.txt`, `manual-atlas-t30-v2.txt` e `questions.json`; nunca documentos internos.
- Toda inserção do benchmark deve ser revertida mesmo se ocorrer exceção.

## Arquivos previstos

- Modificar `src/acervo_ia/services/semantic_search.py`: busca vetorial/textual/literal, RRF e funções reutilizáveis.
- Modificar `src/acervo_ia/db/models.py` e criar migração apenas para índice GIN de expressão.
- Modificar `src/acervo_ia/api/routes/embeddings.py`: estratégia `vector|text|hybrid`, com `hybrid` padrão.
- Modificar `src/acervo_ia/api/routes/qa.py`: recuperar contexto pelo ranking híbrido.
- Criar/atualizar testes em `tests/test_hybrid_search.py`, `tests/test_embeddings.py` e `tests/test_qa.py`.
- Criar `src/acervo_ia/services/retrieval_evaluation.py` e `scripts/evaluate_retrieval.py`.
- Atualizar `docs/avaliacao-inicial.md` e `README.md` com métricas, resultados medidos e comando local.

## Tarefas

### 1. RRF e identificadores literais

Escrever testes determinísticos para normalizar `E-17`, `B20`, `AT-24`, siglas e acentos; verificar RRF por ranking, desempate estável e limite. Rodar os testes em RED. Implementar helpers puros em `semantic_search.py` e rodar GREEN.

### 2. PostgreSQL textual e modos da API

Escrever testes para consultas FTS, busca textual sem Ollama, combinação FTS+literal e híbrida vetorial+lexical. Compilar consultas com dialeto PostgreSQL e verificar operador full-text/GIN e filtro de coleção. Adicionar índice de expressão GIN ao metadata e migração; revisar a migração antes de aplicá-la. Expor modo na rota `/search`, validar propriedade antes de qualquer consulta e fazer `/ask` usar `search_hybrid_chunks`. Atualizar os testes de isolamento e RAG sem serviço externo.

### 3. Benchmark de recuperação

Criar métricas testáveis para `Recall@5` e `MRR`, calculadas sobre as 25 perguntas respondíveis, e relatório separado de resultados das cinco perguntas sem evidência. Criar CLI que lê os TXT fictícios por seção, gera embeddings em lote, cria usuário/coleções/documentos/trechos em uma transação sem commit, avalia os três modos com filtros de modelo e chama `rollback()` em `finally`. Emitir JSON com contagens, métrica por modo e modelo de embeddings.

### 4. Medição e documentação

Com PostgreSQL/pgvector e Ollama locais disponíveis, aplicar a migração revisada, rodar o benchmark e registrar valores reais sem extrapolar vencedor. Documentar dependências, comando, semântica das métricas e limitações. Rodar suíte completa, verificações de estilo e `git diff --check`; conferir que os arquivos RAG anteriores continuam no worktree.

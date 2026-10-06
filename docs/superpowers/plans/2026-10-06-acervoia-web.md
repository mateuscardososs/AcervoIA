# Interface web do AcervoAI — plano de implementação

> Execução inline nesta sessão. Sem commit ou push, conforme solicitado.

**Objetivo:** construir uma SPA React/TypeScript para autenticação, organização do acervo, gestão de documentos e consulta com fontes.

**Arquitetura:** manter o frontend em `web/`, com Vite proxy `/api` para a API existente. Centralizar autenticação Bearer e chamadas REST num cliente; preservar autorização no FastAPI. Estender `POST /collections/{collection_id}/ask` com `strategy` (`vector`, `text`, `hybrid`), padrão `vector`, antes de conectar o seletor da interface.

**Tecnologias:** React, TypeScript, Vite, React Router, Vitest, Testing Library, FastAPI/Pydantic e pytest.

## Restrições globais

- Preservar mudanças existentes; não ler nem imprimir valores do `.env`.
- Não fazer commit nem push.
- Não introduzir cadastro público, OCR, novo histórico de conversa nem alteração no isolamento por usuário.
- A interface envia somente IDs de coleção/documento e nunca escolhe ou envia `user_id`.
- Formatos de upload PDF/DOCX/TXT; limite 20 MiB.
- Testes não dependem do Ollama real.
- Busca vetorial selecionada inicialmente; métricas do benchmark são contexto local, não alegação geral.

---

### Tarefa 1: Contrato de estratégia no `/ask`

**Arquivos:** `src/acervo_ia/api/routes/qa.py`, `tests/test_qa.py`.

- [x] Adicionar testes para `vector` como padrão, `text` sem gerar embedding, `hybrid` e isolamento antes da recuperação.
- [x] Rodar os testes novos e confirmar falha pelo contrato ainda inexistente.
- [x] Adicionar `strategy: Literal['vector', 'text', 'hybrid'] = 'vector'`; vetor/híbrido geram embedding, texto chama busca textual, híbrido combina ambos.
- [x] Rodar `tests/test_qa.py` e garantir fontes/erros existentes sem regressão.

### Tarefa 2: Estrutura React/Vite e cliente autenticado

**Arquivos:** criar `web/package.json`, lockfile, `index.html`, `vite.config.ts`, `tsconfig*.json`, `src/main.tsx`, `src/api/client.ts`, `src/auth/AuthProvider.tsx` e testes associados.

- [x] Escrever testes do cliente para bearer token, formulário OAuth2, JSON/multipart e 401.
- [x] Confirmar o estado RED antes da implementação.
- [x] Criar SPA e proxy Vite para `http://127.0.0.1:8000`; não colocar segredos em arquivos frontend.
- [x] Implementar cliente e estado de sessão em `sessionStorage`; validar sessão com `/auth/me`.
- [x] Rodar testes do cliente.

### Tarefa 3: Acervo e gestão de documentos

**Arquivos:** `web/src/App.tsx`, `web/src/pages/LibraryPage.tsx`, `web/src/pages/CollectionPage.tsx`, `web/src/components/*`, testes em `web/src/**/*.test.tsx` e CSS.

- [x] Cobrir acervo vazio, criar/editar/excluir coleção, envio validado e estados da lista.
- [x] Implementar fluxo por coleção usando somente os endpoints existentes e token autenticado.
- [x] Ao processar, chamar `/process` e então `/embeddings`; reportar etapas e erro Ollama sem mascarar falha de extração.
- [x] Garantir responsividade, foco visível, rótulos acessíveis e os tokens visuais aprovados.
- [x] Rodar testes do fluxo de acervo/documentos.

### Tarefa 4: Consulta, respostas e fontes

**Arquivos:** `web/src/pages/AskPage.tsx`, `web/src/components/SourceCard.tsx`, testes e estilos.

- [x] Testar seleção dos três modos, padrão vetorial, loading, erro Ollama e fonte com/sem página.
- [x] Enviar `question`, `limit` e `strategy` ao `/ask` da coleção selecionada.
- [x] Renderizar resposta e apenas metadados/snippets retornados pelo backend; nunca sintetizar fontes no cliente.
- [x] Rodar suíte Vitest e build `npm run build`.

### Tarefa 5: Validação integrada e documentação

**Arquivos:** README.

- [x] Documentar instalações, execução local do backend e Vite, proxy, login com conta criada pelo CLI e fluxo upload/processamento/consulta.
- [x] Rodar suíte completa do backend, testes do frontend, build e `git diff --check`.
- [x] Revisar estado Git para confirmar preservação dos arquivos existentes e ausência de commit/push.

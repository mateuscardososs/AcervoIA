# Interface web do AcervoAI

## Objetivo

Entregar uma interface React, TypeScript e Vite para entrar no AcervoAI, organizar coleções próprias, enviar e processar documentos, acompanhar seus estados e fazer perguntas com fontes visíveis.

## Arquitetura

A aplicação web vive em `web/`, separada da API FastAPI. Em desenvolvimento, o Vite encaminha `/api/*` para o backend local e remove o prefixo antes de encaminhar, evitando CORS no fluxo local. Um cliente HTTP central anexa o bearer token mantido em `sessionStorage`; uma resposta 401 limpa a sessão e retorna a pessoa ao login. A API continua responsável pela autorização e pelo isolamento por usuário.

## Fluxos

- Login usa `POST /auth/token` como formulário OAuth2 e valida a sessão com `GET /auth/me`.
- Acervo lista, cria, renomeia e exclui somente as coleções retornadas para a conta autenticada.
- Detalhes da coleção lista, envia e exclui documentos. O upload aceita os formatos configurados no MVP (PDF, DOCX e TXT) até 20 MiB. O processamento chama `/process` e, em seguida, `/embeddings`, mostrando separadamente falha de extração e indisponibilidade do Ollama.
- Consulta envia pergunta, limite e `strategy` para `/ask`. O seletor oferece `vector`, `text` e `hybrid`, iniciando em `vector`. A API valida a propriedade da coleção antes da recuperação. Metadados e snippets das fontes permanecem construídos e validados pelo backend.
- Loading, coleção vazia, lista vazia, processamento, erro de API, sessão expirada e Ollama indisponível têm mensagens e ações próprias.

## Direção visual

Interface de arquivo técnico: navegação lateral em tinta escura; área de trabalho clara; documentos apresentados em linhas compactas com estado visível; nomes e metadados técnicos usam uma pilha monoespaçada. O detalhe memorável é a apresentação de evidências em cartões `[S1]`, com documento/página e trecho alinhados para conferir a resposta. Layout colapsa a navegação e empilha painéis em telas estreitas, mantém foco de teclado visível e respeita redução de movimento.

## Testes e limites

Vitest e Testing Library cobrem cliente/API e fluxos principais com respostas simuladas, sem servidor Ollama. Pytest cobre seleção de estratégia, modo vetorial padrão e isolamento no endpoint `/ask`. Build Vite valida o bundle. Não serão adicionados cadastro público, armazenamento de conversa, mudança de modelo ou autorização no frontend como substituto das verificações do backend.

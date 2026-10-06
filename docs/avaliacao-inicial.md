# Avaliação inicial da recuperação

## Objetivo

Comparar busca textual, busca vetorial e busca híbrida sobre a mesma amostra, sem usar o conjunto final para ajustar configurações. Esta amostra é um ponto de partida; depois vamos separar perguntas de ajuste e de avaliação final.

## Fontes e referência

As respostas esperadas apontam para IDs de seção dos TXT em `data/demo/`. Seções funcionam como localizadores estáveis. O produto deve mostrar nome do arquivo, seção e trecho; não deve inventar páginas para TXT.

## Métricas e benchmark local

O benchmark executável é `scripts/evaluate_retrieval.py`. Para cada pergunta respondível, há um acerto quando pelo menos uma seção esperada aparece entre os cinco primeiros: `Recall@5 = perguntas respondíveis com fonte relevante no top 5 / total de perguntas respondíveis`. `MRR` é a média do inverso da posição do primeiro resultado relevante (zero quando nenhum aparece). As cinco perguntas sem evidência são reportadas à parte como número de consultas que ainda receberam algum resultado no top 5; isso não mede se o `/ask` efetivamente se abstém.

O modo `text` combina full-text search e correspondência literal por RRF. O modo `hybrid` combina esse ranking textual com o ranking vetorial por RRF. Os vetores de documentos e perguntas são gerados pelo modelo Ollama configurado; os três modos consultam o PostgreSQL local. As linhas temporárias são criadas numa única transação e revertidas no `finally`, sem commit.

### Resultado observado

Execução local em 2026-10-05, com `embeddinggemma`, os 14 trechos dos dois manuais fictícios e as 30 perguntas atuais. Os valores são reproduzíveis apenas com as mesmas versões/configurações do modelo, PostgreSQL e corpus.

| Estratégia | Recall@5 (25 respondíveis) | MRR | Sem evidência: consultas com algum resultado no top 5 (5) |
|---|---:|---:|---:|
| Vetorial | 1,00 | 0,960 | 5 |
| Textual (FTS + literal) | 0,36 | 0,238 | 3 |
| Híbrida (RRF) | 0,92 | 0,861 | 5 |

Nesta amostra e nesta execução, a busca vetorial teve as maiores métricas de recuperação; a híbrida ficou entre a vetorial e a textual. Isso não demonstra superioridade geral de nenhuma abordagem: são apenas 25 perguntas respondíveis, sobre dois manuais inventados. A avaliação não mede precisão factual das respostas geradas. As consultas sem evidência mostram que receber resultados não equivale a encontrar evidência suficiente, portanto a política de abstenção merece avaliação própria.

Para executar novamente: iniciar o PostgreSQL do Compose e o Ollama local, garantir disponível o modelo `OLLAMA_EMBEDDING_MODEL` (padrão `embeddinggemma`), aplicar `.venv/bin/alembic upgrade head` e rodar `.venv/bin/python scripts/evaluate_retrieval.py`. Os testes (`.venv/bin/python -m pytest`) simulam Ollama e não exigem que ele esteja ativo.

## Benchmark de respostas ponta a ponta

O comando `.venv/bin/python scripts/evaluate_answers.py` executa o serviço compartilhado pelo endpoint `/ask` para as 30 perguntas, em `vector`, `text` e `hybrid`, usando PostgreSQL/pgvector e o Ollama local. A lista `modes` do relatório apresenta contagens por modo: abstenções corretas para perguntas sem evidência, respostas com fontes pertencentes aos hits reais (ID e metadados conferidos pelo benchmark), respostas às perguntas respondíveis que citam seção esperada, falhas após a única correção, fontes inválidas, erros de formato do modelo e latência média/p95.

Uma resposta com fonte esperada não equivale a uma avaliação semântica do texto gerado: o benchmark confirma proveniência e alinhamento com a seção anotada, mas não avalia paráfrase, completude ou segurança operacional da resposta. Os cinco casos sem evidência são uma amostra pequena para medir abstenção. O relatório não inclui perguntas, documentos, trechos, saídas brutas do modelo, credenciais ou valores de configuração. Se PostgreSQL ou Ollama falhar, o comando retorna um código de erro e mensagem genérica sem apresentar os resultados parciais como aprovação. Usuários, coleções, documentos e trechos ficam numa única transação revertida em `finally`.

### Execução observada em 2026-10-06

Uma execução com PostgreSQL local, `embeddinggemma` e `qwen3:4b-instruct-2507-q4_K_M` produziu os seguintes agregados nos 30 itens (25 respondíveis, 5 sem evidência):

| Modo | Abstenções corretas (de 5) | Respostas com fontes válidas (de 30) | Respondíveis com fonte esperada (de 25) | Falha após correção | Latência média / p95 |
|---|---:|---:|---:|---:|---:|
| vector | 5 (100%) | 17 | 17 | 5 | 5,75 s / 12,69 s |
| text | 5 (100%) | 7 | 7 | 2 | 2,48 s / 9,62 s |
| hybrid | 5 (100%) | 14 | 14 | 6 | 4,48 s / 11,21 s |

Não houve fontes inválidas aceitas nem erros de formato nessa execução. As falhas após correção indicam respostas cuja segunda tentativa ainda não validou as referências; o backend omitiu suas fontes. Os valores são de uma única execução local, em corpus sintético pequeno, dependente dos modelos e do hardware usados; não estabelecem superioridade geral nem correção semântica das respostas.

## Critérios de aceite da recuperação

- Para pergunta com filtro de modelo, nenhum resultado do outro modelo aparece como fonte autorizada.
- A consulta por E-17 retorna a seção correta quando o modelo é informado.
- Busca sem geração mostra texto e metadados do resultado.
- Perguntas sem evidência recebem indicação de ausência; não se completam lacunas com conhecimento geral.
- O backend valida que cada referência pertence aos resultados recuperados e aos documentos permitidos naquela consulta.

## Banco de perguntas

`questions.json` contém 30 itens. `expected_sections` registra evidência conhecida para as 25 perguntas respondíveis; as cinco perguntas sem resposta têm `answerable: false` e lista vazia. As referências são rótulos de avaliação, não IDs de chunks produzidos pelo sistema.

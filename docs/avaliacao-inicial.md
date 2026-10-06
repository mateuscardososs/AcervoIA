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

## Critérios de aceite da recuperação

- Para pergunta com filtro de modelo, nenhum resultado do outro modelo aparece como fonte autorizada.
- A consulta por E-17 retorna a seção correta quando o modelo é informado.
- Busca sem geração mostra texto e metadados do resultado.
- Perguntas sem evidência recebem indicação de ausência; não se completam lacunas com conhecimento geral.
- O backend valida que cada referência pertence aos resultados recuperados e aos documentos permitidos naquela consulta.

## Banco de perguntas

`questions.json` contém 30 itens. `expected_sections` registra evidência conhecida para as 25 perguntas respondíveis; as cinco perguntas sem resposta têm `answerable: false` e lista vazia. As referências são rótulos de avaliação, não IDs de chunks produzidos pelo sistema.

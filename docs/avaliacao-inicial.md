# Avaliação inicial da recuperação

## Objetivo

Comparar busca textual, busca vetorial e busca híbrida sobre a mesma amostra, sem usar o conjunto final para ajustar configurações. Esta amostra é um ponto de partida; depois vamos separar perguntas de ajuste e de avaliação final.

## Fontes e referência

As respostas esperadas apontam para IDs de seção dos TXT em `data/demo/`. Seções funcionam como localizadores estáveis. O produto deve mostrar nome do arquivo, seção e trecho; não deve inventar páginas para TXT.

## Métrica planejada

Para cada pergunta respondível, considerar recuperado o resultado quando pelo menos uma seção esperada aparecer entre os cinco primeiros. `Recall@5 = perguntas respondíveis com fonte relevante no top 5 / total de perguntas respondíveis`. Também registrar separadamente falsos resultados de modelo, sustentação da resposta, abstenção nas perguntas sem resposta e latência.

Com apenas 30 exemplos, os números servem para diagnóstico do protótipo, não para alegações gerais de qualidade. Toda avaliação com geração deve ser revisada contra as fontes.

## Critérios de aceite da recuperação

- Para pergunta com filtro de modelo, nenhum resultado do outro modelo aparece como fonte autorizada.
- A consulta por E-17 retorna a seção correta quando o modelo é informado.
- Busca sem geração mostra texto e metadados do resultado.
- Perguntas sem evidência recebem indicação de ausência; não se completam lacunas com conhecimento geral.
- O backend valida que cada referência pertence aos resultados recuperados e aos documentos permitidos naquela consulta.

## Banco de perguntas

`questions.json` contém 30 itens. `expected_sections` registra evidência conhecida para as 25 perguntas respondíveis; as cinco perguntas sem resposta têm `answerable: false` e lista vazia. As referências são rótulos de avaliação, não IDs de chunks produzidos pelo sistema.

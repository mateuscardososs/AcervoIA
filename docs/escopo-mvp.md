# Escopo da primeira entrega

## Problema

Encontrar instruções em vários manuais é lento e pode levar à consulta de um modelo ou versão diferente. O AcervoIA deve responder somente com base nos documentos selecionados, mostrar os trechos usados e admitir quando não houver evidência suficiente.

## Usuários e cenário

O MVP atende um usuário individual por conta. Cada pessoa verá apenas as próprias coleções e documentos. O cenário demonstrativo é uma equipe de suporte que consulta manuais de balanças fictícias.

## Acervo de demonstração

| Coleção | Documento | Tipo | Conteúdo de teste |
|---|---|---|---|
| Indicadores fictícios | `manual-orion-b20-v1.txt` | TXT | Inicialização, alimentação, instalação, erro E-17, calibração e restrição de manutenção |
| Indicadores fictícios | `manual-atlas-t30-v2.txt` | TXT | Inicialização, alimentação, instalação, erro E-17, conexão e restrição de manutenção |

Os dois documentos usam deliberadamente o mesmo código E-17 com significados diferentes. Isso permite testar seleção de documento/modelo e evitar misturar versões. São textos inventados, sem relação com instruções de fabricantes reais.

## Dentro da primeira entrega executável

1. API FastAPI com endpoint de saúde.
2. Organização modular mínima, sem camadas ou abstrações prematuras.
3. Teste HTTP automatizado sem banco nem modelo de IA.
4. README com comandos reproduzíveis.

O primeiro incremento de código termina no endpoint de saúde e na inicialização local. Depois adicionaremos persistência, autenticação e domínio em etapas pequenas. PostgreSQL e Docker Compose entram junto com a etapa de persistência para evitar infraestrutura sem uso no incremento atual.

## Fora da primeira entrega

Upload, login, CRUD, extração de PDF, processamento em segundo plano, embeddings, busca híbrida, geração, interface React, OCR e uso de documentos internos. Esses itens permanecem no plano do MVP, mas não entram no primeiro incremento de código.

## Critérios de aceite desta etapa

- O acervo usa apenas conteúdo fictício e informa isso claramente.
- Há 30 perguntas registradas, com 25 respondíveis e 5 sem evidência.
- Cada pergunta respondível aponta para uma seção-fonte previamente conhecida.
- Há perguntas que distinguem os dois modelos, incluindo o E-17.
- O próximo incremento técnico tem escopo pequeno e verificável.

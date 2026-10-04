# Configuração do Alembic e migração inicial

## Objetivo

Configurar o Alembic para obter `DATABASE_URL` do arquivo `.env`, localizar o
metadata dos modelos SQLAlchemy e criar a primeira migração de `users` e
`collections`.

## Escopo

- Adicionar `python-dotenv` às dependências da aplicação.
- Carregar `.env` em `migrations/env.py` sem imprimir variáveis ou valores.
- Interromper a execução com uma mensagem segura quando `DATABASE_URL` não
  estiver configurada.
- Usar `Base.metadata`, definido em `acervo_ia.db.models`, como
  `target_metadata` do Alembic.
- Manter a URL real fora de `alembic.ini`.
- Gerar e revisar a migração antes de aplicá-la.
- Iniciar somente o serviço PostgreSQL necessário, aplicar a migração e
  verificar as tabelas no catálogo do banco.
- Executar os testes existentes ao final.

Não fazem parte desta etapa login, autenticação, rotas de coleções ou uma nova
inicialização de `migrations`.

## Desenho técnico

`migrations/env.py` localizará o `.env` a partir da raiz do projeto, chamará
`load_dotenv` e lerá `DATABASE_URL` por `os.getenv`. A ausência da variável
produzirá um erro que cita somente seu nome, nunca seu valor.

Nos modos online e offline, a URL será fornecida diretamente à configuração do
Alembic. Ela não será gravada na configuração nem registrada explicitamente.
No modo online, o engine será criado com `NullPool`. O metadata será obtido por
meio de `Base.metadata`.

## Migração e revisão

A migração será gerada com `alembic revision --autogenerate`. Antes de qualquer
`upgrade`, o arquivo gerado será inspecionado para confirmar:

- criação exclusiva das tabelas `users` e `collections`;
- UUIDs, tamanhos de strings, timestamps e nulabilidade correspondentes aos
  modelos;
- unicidade de `users.email`;
- chave estrangeira `collections.owner_id -> users.id` com `ON DELETE CASCADE`;
- restrição única de nome por proprietário;
- índices declarados pelos modelos;
- `downgrade` na ordem inversa, sem operações estranhas ao escopo.

Se a autogeração produzir algo divergente, a migração será corrigida e
revisada antes da aplicação.

## Verificação

Após o PostgreSQL estar saudável, `alembic upgrade head` aplicará a revisão. A
verificação consultará o banco sem exibir credenciais para confirmar `users`,
`collections` e `alembic_version`. Por fim, serão executados o estado do
Alembic e a suíte completa de testes.

## Preservação do repositório

As mudanças locais existentes serão mantidas. Nenhum arquivo será recriado,
nenhum segredo será exibido e `alembic init migrations` não será executado.

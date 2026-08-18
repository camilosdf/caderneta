# Débitos e pendências remanescentes — pós B.2 (DT-CC-01)

**Natureza:** achado técnico. Registra o que **não** foi resolvido pela
sequência B.2 (`docs/adr/regularizacao-governanca-adr011-dtcc01-b2.md`),
para não ser confundido com escopo já fechado nem esquecido por ausência
de registro. Nenhum item aqui foi implementado ou corrigido nesta sessão.
**Data:** 2026-08-18
**Branch:** `feature/cartao-credito`, HEAD `847382c`

---

## DT-CC-01-R1 — `CartaoCreditoORM.conta_codigo` sem FK

**Status:** débito técnico remanescente, deliberadamente fora do escopo de B.2 (não é falha de B.2).

`CartaoCreditoORM.conta_codigo` (`core/infra/db/models.py:429`) permanece
referência textual, sem FK — mesmo padrão que `SplitORM.conta_codigo`
tinha antes de B.2. O comentário de módulo que precede a classe
(`core/infra/db/models.py:395-403`) ainda descreve o estado pré-B.2 ("DT-CC-01: ContaContabil não tem persistência própria no sistema... nenhuma tabela contas_contabeis, nenhum ContaContabilORM") — **desatualizado**: `ContaContabilORM` existe desde B.2.1. A migration `c9d1f6a3e8b2` confirma explicitamente essa exclusão de escopo ("`cartoes_credito.conta_codigo` permanece fora do escopo desta FK... já documentado em models.py como 'referência textual, sem FK'").

**Ação sugerida (não decidida aqui):** (a) corrigir o comentário de módulo desatualizado; (b) decidir se `CartaoCreditoORM.conta_codigo` entra em um plano B.3 análogo, ou se a decisão é mantê-lo fora por natureza (cartão referencia uma conta de forma distinta de `Split`).

## R2 — Terceiro caminho de criação de `SessionFactory` (comando `dry-run`) roda sem enforcement de FK

**Status:** pendência arquitetural, comportamento confirmado — impacto não avaliado.

Existem três pontos de criação de `SessionFactory` no sistema, com configuração distinta:

| Local | `enforce_foreign_keys` | Fonte do schema |
|---|---|---|
| `core/cli.py:63` (`_session_factory`, bootstrap real do CLI) | `True` (explícito) | `criar_tabelas()` — ver R3 |
| `core/infra/db/session.py:149` (`session_factory_from_env`, usado por `api/main.py`/`api/dependencies.py`) | `True` (explícito) | nenhuma criação de schema própria — depende do banco já existir |
| `core/cli.py:368` (comando `dry-run`) | **`False`** (default do construtor, `session.py:45` — não passado explicitamente) | `criar_tabelas()` em banco SQLite temporário (`{tmp}/dry_run.db`) |

O default de `SessionFactory.__init__` é `enforce_foreign_keys: bool = False` (`core/infra/db/session.py:45`), documentado como intencional para não quebrar a suíte hermética. O comando `dry-run` não sobrescreve esse default. Ou seja: a única simulação do sistema que declara explicitamente "sem gerar arquivos ou eventos" roda **sem** enforcement de FK, ao contrário dos dois bootstraps de execução real — uma inconsistência entre o que o `dry-run` promete simular e as garantias de integridade que o caminho real aplica. Este terceiro caminho não é mencionado no inventário original do ADR 011 (DT-CC-01.2, que lista origens de `conta_codigo`, não caminhos de criação de sessão) nem em B.2.

## R3 — `criar_tabelas()` (`Base.metadata.create_all()`) usado no bootstrap real do CLI, em vez de Alembic

**Status:** achado arquitetural, potencialmente mais relevante que R1/R2 — reportado com evidência para avaliação da Direção/Arquiteto, sem implementação.

`core/cli.py:63-65` (`_session_factory`, chamada por todos os comandos do
CLI que processam documentos — não apenas `dry-run`) executa:

```python
factory = SessionFactory(url, enforce_foreign_keys=True)
factory.criar_tabelas()
```

`criar_tabelas()` (`core/infra/db/session.py:113-115`) chama
`Base.metadata.create_all(self._engine)`. Não há, em nenhum ponto de
`core/cli.py`, chamada a `alembic upgrade` ou equivalente — confirmado por
busca (`grep -n alembic core/cli.py` não retorna nenhuma ocorrência).

**Por que isso é relevante, com evidência (não inferência sobre dado real — não há banco de produção a inspecionar, ver DT-CC-01.3):** `Base.metadata.create_all()` é documentado no SQLAlchemy como operação que cria apenas as tabelas **ausentes** no banco de destino; não altera colunas ou constraints de tabelas já existentes. Isso tem duas implicações diretas para o caminho de bootstrap real do CLI:

1. Um banco SQLite criado pelo CLI em uma versão anterior do schema (por exemplo, antes de B.2.1) e reaberto após o upgrade do código para HEAD `847382c` **não recebe** as alterações incrementais das migrations (`f2b8d5e3a1c7`, `a4c7f19e2b6d`, `b7e4a2c9f1d3`, `c9d1f6a3e8b2`) — `create_all()` não executa `ALTER TABLE`. O `splits` desse banco permaneceria sem a FK composta e sem `NOT NULL`, apesar do código em execução assumir esse contrato.
2. O histórico de versão do schema (Alembic `alembic_version`) nunca é populado nem avançado por esse caminho — o schema efetivo de um banco criado assim não tem correspondência rastreável com uma revisão Alembic específica.

Isto é exatamente o padrão que a instrução do projeto assinala: "`create_all()` não é substituto para migrations de produção." Não foi verificado nesta sessão se este caminho é usado apenas em desenvolvimento/homologação local ou também no fluxo de implantação real — essa verificação é pré-requisito antes de classificar este item como bloqueador ou como limitação aceita.

**Ação sugerida (não decidida aqui):** ARQUITETO/SRE avaliar se o bootstrap real do CLI deve passar a invocar `alembic upgrade head` em vez de (ou além de) `criar_tabelas()`, e sob qual condição `criar_tabelas()` continua legítimo (ex.: exclusivamente para banco novo/vazio, com checagem prévia de que não há schema pré-existente).

---

## Resumo de estado

| Item | Estado |
|---|---|
| `ContaContabilORM` | Resolvido (B.2.1) |
| Cadastro persistente de contas | Resolvido (B.2.1/B.2.3) |
| `Split.empresa_id NOT NULL` | Resolvido (B.2.4) |
| FK composta de `Split` | Resolvido (B.2.4) |
| Enforcement PostgreSQL | Resolvido — nativo |
| Enforcement SQLite | Resolvido — opt-in (`enforce_foreign_keys=True`) |
| `CartaoCredito.conta_codigo` sem FK | Débito remanescente (DT-CC-01-R1) |
| Terceiro `SessionFactory` (dry-run) roda sem enforcement de FK | Confirmado, impacto não avaliado (R2) |
| `criar_tabelas()` × Alembic no bootstrap real do CLI | Achado arquitetural, avaliação pendente (R3) |

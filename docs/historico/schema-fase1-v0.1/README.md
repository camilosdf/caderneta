# Schema Fase 1 (v0.1) — Arquivo Histórico

Este diretório contém o schema SQL cru usado na Fase 1 do projeto (v0.1),
antes da reescrita como monorepo por camadas de maturidade (v2).

**Este schema não corresponde ao estado atual do sistema.** Tabelas como
`fornecedores` com coluna `embedding vector(768)` (pgvector) refletiam um
design anterior à separação `core/` (determinístico) vs `ai/` (plugins).

O schema atual é definido pelos modelos ORM em `core/infra/db/models.py`
e versionado via Alembic em `infra/migrations/`.

Mantido aqui apenas como referência histórica — não usar para provisionar
bancos novos.
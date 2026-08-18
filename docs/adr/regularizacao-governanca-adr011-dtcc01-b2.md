# Regularização de Governança — ADR 011 / DT-CC-01, Opção B (plano B.2)

**Natureza:** registro formal de regularização de governança. **Não é** uma
reconstrução retroativa da decisão original — complementa `ADR 011`, não o
substitui, e não altera o texto original desse documento (Contexto,
DT-CC-01.2, DT-CC-01.3, Seção "Decisão"), que permanece como registro
histórico fiel do estado em que a decisão ainda estava pendente.
**Data do registro:** 2026-08-18
**Branch:** `feature/cartao-credito` (não mesclada em `main`)
**Commit final da sequência:** `847382c`

---

## 1. O que este documento reconhece

`ADR 011` (texto original, inalterado) registra explicitamente:

> **Status:** Em aberto — decisão pendente entre Opção A e Opção B.
> **Decisão:** Ainda não tomada.

Os cinco commits da sequência B.2 (`3ea589d`, `6e5a93e`, `772bccb`,
`9d26bdb`, `847382c`) implementam integralmente a Opção B e referenciam em
suas mensagens "aprovada em ADR 011" e um "sub-desenho D-B.2" / "Plano
B.2". **Nenhum artefato do repositório contém esse plano ou essa
aprovação** — busca em `docs/` e `core/` por essas expressões não retorna
nenhum documento formal, apenas as próprias mensagens de commit e
comentários de código (`core/infra/db/models.py:109-112`, `core/infra/db/
session.py:56-60`, `infra/migrations/versions/c9d1f6a3e8b2_...py:19-25`).

Ou seja: a decisão foi tomada e implementada **fora do fluxo formal**
descrito nas instruções do projeto (decisão de mérito deve preceder e ser
registrada antes da implementação). Este documento não afirma que a
decisão foi tomada no ADR 011 original — afirma que foi tomada
**posteriormente**, fora dele, e regulariza esse registro agora.

**Lacuna que permanece em aberto:** não há, em nenhum artefato acessível
neste repositório, o nome de quem na Direção autorizou a Opção B nem a
data exata dessa autorização — apenas a atribuição genérica "Direção" nas
mensagens de commit. Se essa informação existir fora do repositório
(e-mail, ata, conversa), recomenda-se anexá-la aqui ou em documento
próprio; na ausência dela, este registro descreve o que o código e os
testes comprovam, não quem decidiu.

---

## 2. Decisão efetivamente implementada

**Opção B** do ADR 011 — cadastro persistente de `ContaContabil` + FK real
em `Split` — executada em quatro unidades sequenciais ("plano B.2"):

| Unidade | Commit | Escopo |
|---|---|---|
| B.2.1 | `3ea589d` | `ContaContabilORM` + `ContaContabilRepository`, `UniqueConstraint(empresa_id, codigo)` — cadastro aditivo, sem FK ativa ainda |
| B.2.2 | `6e5a93e` | `splits.empresa_id` sempre derivado de `Lancamento.empresa_id` (nunca parâmetro independente); backfill retroativo (migration `a4c7f19e2b6d`) |
| B.2.3 | `772bccb` | Cadastro das contas já em uso (migration `b7e4a2c9f1d3`) + comando `caderneta conta criar`/`conta listar` — pré-requisito para não quebrar splits existentes ao ativar a FK |
| B.2.4 | `9d26bdb`, `847382c` | `splits.empresa_id` passa a `NOT NULL`; FK composta `(empresa_id, conta_codigo) → contas_contabeis(empresa_id, codigo)` (migration `c9d1f6a3e8b2`); segundo commit corrige 19 falhas de regressão em testes que exercitam bootstrap real |

**Escopo técnico:**

- `SplitORM.(empresa_id, conta_codigo)` → `contas_contabeis.(empresa_id, codigo)`, FK `fk_splits_conta_contabil` (`core/infra/db/models.py:126-132`).
- `splits.empresa_id`: `NOT NULL` (era nullable).
- Migration `c9d1f6a3e8b2`: valida ausência de órfãos (`empresa_id NULL` e `conta_codigo` não cadastrado) antes de aplicar a constraint — aborta com `RuntimeError` em vez de aplicar schema parcialmente íntegro; `downgrade()` simétrico (remove FK, reverte `NOT NULL`).
- Enforcement: nativo e sempre ativo no PostgreSQL; opt-in no SQLite via `SessionFactory(enforce_foreign_keys=True)` (`core/infra/db/session.py:149`), usado no bootstrap real do CLI (`core/cli.py:63`) e em `session_factory_from_env()` (usada por `api/main.py`/`api/dependencies.py`). A suíte hermética **não** ativa a flag — medição documentada em `c9d1f6a3e8b2` (ativação global quebraria 126 testes fora do escopo de DT-CC-01).
- Regressão: suíte completa executada nesta verificação (`/tmp/venv`, Python 3.11) — 1006 testes coletados, 1 falha (`test_sentence_transformer_provider::test_satisfaz_protocolo`), de causa ambiental (tentativa de download de modelo via rede, bloqueada por `pytest_socket` no sandbox de verificação — não é regressão de código). Todos os testes de migration/backfill/FK relacionados a B.2 passam: `test_migration_fk_composta_b24.py`, `test_backfill_splits_empresa_id.py`, `test_backfill_cadastro_contas_em_uso.py`, `test_schema_alembic_integracao.py`.

## 3. Linguagem de implantação — restrição deliberada

**Não se afirma implantação em produção.** Conforme `ADR 011`, Seção
DT-CC-01.3, e confirmado nesta verificação: não há ambiente de produção
real em uso; a branch `feature/cartao-credito` não está mesclada em
`main`. A formulação correta é:

> Implementada na branch `feature/cartao-credito` e validada em ambiente
> de desenvolvimento/teste (SQLite local, suíte automatizada). Não há
> evidência de implantação ou validação em PostgreSQL de produção.

## 4. Efeito sobre o Gate

Esta regularização remove o bloqueador de rastreabilidade identificado
(ADR desatualizado frente ao código). Não constitui, por si só,
autorização de merge para `main` nem fechamento de Gate — isso depende de
avaliação separada dos demais itens do inventário de Gate 0 (ver
`docs/adr/deliberacao-pos-fase6.md`, `docs/adr/atualizacao-gate0-pos-
reconciliacao.md`) e do documento de débitos remanescentes desta mesma
data (`docs/adr/dt-cc-01-r1-debitos-remanescentes.md`).

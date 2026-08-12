# Artefato Formal de Autorização — Fase 6 (Conciliação de Cartão de Crédito)
### ADR 010 · Etapas 6.1 (A×B) e Gate B6 consolidadas

**Status:** Matriz fechada, arquiteturalmente coerente. **Implementação
NÃO autorizada por este documento.** Este artefato é o objeto que, uma
vez revisado, pode receber autorização explícita — a autorização em si
é um ato separado, posterior a esta entrega.

Nenhum código foi alterado para produzir este artefato.

---

## 1. Decisões consolidadas

### Etapa 6.1 — A × B
**B aprovada.** Tabela de vínculo dedicada (`pagamentos_faturas_cartao`),
`Lancamento`/`LancamentoORM` permanecem intocados. Consistente com o
padrão já usado por `CompraCartao.lancamento_id` (Fase 0/1) e com
DT-CC-01/DT-CC-02 (não alterar entidades centrais para necessidade
específica de cartão).

### B6-0 — Geração/persistência dos lançamentos (pré-requisito)
**APROVADO**, com guardrails abaixo. Não é scope creep — é o elo de
orquestração que torna executáveis D7/D8 (Fase 3, já implementados e
testados, mas nunca chamados por nenhum use case até hoje).

---

## 2. Guardrails obrigatórios (confirmados)

1. Não alterar `Lancamento` nem `LancamentoORM`.
2. Não alterar a lógica de `construir_lancamento_compra_cartao`/
   `construir_lancamento_pagamento_fatura` (Fase 3) — B6-0 apenas
   orquestra chamadas a eles, não modifica seu comportamento interno.
3. `FaturaCartao` com `status_fechamento != FECHADA` não gera lançamentos
   automaticamente.
4. B6-0 idempotente — reprocessar a mesma fatura não cria lançamentos
   novos, **e** reutiliza corretamente o vínculo já existente (não
   apenas detecta duplicidade após já ter produzido efeito parcial —
   ver Seção 4).
5. `CompraCartao.lancamento_id` passa a ser efetivamente preenchido.
6. Pagamento continua sendo um único lançamento agregado (D8).
7. Compras individuais continuam fora das candidatas à conciliação
   (B6-2, via `CompraCartao.lancamento_id`, não via `categoria`).
8. Pagamento de cartão continua sem FITID/Camada 1 (D15, Fase 5,
   inalterada).
9. Restrição 1:1/N:1 materializada também no banco (constraints
   `UNIQUE` em `pagamentos_faturas_cartao`, não apenas em memória).
10. Nenhuma alteração em `main`. Nenhuma entrada automática na
    implementação da Fase 6 a partir deste artefato.
11. **B6-0 transacional** — geração dos lançamentos + persistência +
    atualização de `CompraCartao.lancamento_id` ocorrem na mesma
    `UnitOfWork`. Falha em qualquer item reverte tudo — nunca uma
    fatura parcialmente contabilizada.

---

## 3. Matriz formal

| Bloco | Decisão / implementação | Arquivos prováveis | Migration |
|---|---|---|---|
| **B6-0** | Gerar e persistir lançamentos D7/D8 a partir de `FaturaCartao` `FECHADA`; gravar `CompraCartao.lancamento_id`; transacional | `core/application/use_cases/gerar_lancamentos_fatura_cartao.py` (novo); `core/infra/repositories/cartao_repository.py` (novo método de atualização de item — `FaturaCartaoRepository` hoje só tem `salvar_se_nova`, sem update parcial de `CompraCartao`) | Não |
| **B6-1** | Identificar o `Lancamento` único de pagamento da fatura (via `FaturaCartaoRepository`, após B6-0) | `core/application/...` | Não |
| **B6-2** | Excluir compras individuais via `CompraCartao.lancamento_id` (populado por B6-0) | `core/application/...`, eventualmente CLI | Não |
| **B6-3** | Conciliar somente pagamento agregado ↔ transação bancária — **CONCLUÍDA**: `ConciliarPagamentoFaturaCartaoUseCase`, candidato único por construção (não por filtro), 9 testes, 721/721 sandbox + 814 VM, zero migration, `MotorConciliacao`/`core/cli.py`/domínio confirmados intocados por diff/timestamp | `MotorConciliacao` (inalterado) + novo use case de orquestração | Não |
| **B6-4** | Preservar matching 1:1 — **CONCLUÍDA**: 2 testes (não 6, após verificar que a maior parte já era coberta genericamente desde a Fase 5 — `TestUnicidade`); fronteira cross-call de B6-3 documentada no ADR como nota de escopo (não é débito técnico novo) | Motor existente (Fase 5, inalterado) | Não |
| **B6-5** | Persistir vínculo Fatura ↔ Lançamento ↔ Transação | `core/infra/db/models.py` (novo `PagamentoFaturaCartaoORM`), novo repositório | **Sim** |
| **B6-6** | Registrar método/resultado da conciliação | mesmo modelo de B6-5 | **Sim** (mesma migration) |
| **B6-7** | Auditoria | `core/audit/chain.py` (novos `TipoEvento`, se necessário) + use case | Não |
| **B6-8** | Publicar `PagamentoCartaoIdentificado` | `core/events/catalog.py` (já cadastrado, Fase 4) + use case | Não |
| **B6-9** | Não publicar evento para divergência/ambiguidade | use case + testes negativos | Não |
| **B6-10** | Não permitir compra individual como candidata | filtro por `CompraCartao.lancamento_id` | Não |
| **B6-11** | Não permitir N:1 | Motor (inalterado) + testes negativos obrigatórios | Não |
| **B6-12** | FITID restrito a lançamentos com `documento_id` | Motor existente (Fase 5, inalterado) | Não |
| **B6-13** | Pagamento de cartão não usa FITID | teste negativo explícito | Não |
| **B6-14** | Idempotência da conciliação | chave única em `pagamentos_faturas_cartao` | **Sim** (mesma migration) |

**Uma única migration** cobre B6-5/B6-6/B6-14 — nenhuma migration
adicional em nenhum outro bloco, incluindo B6-0.

---

## 4. Idempotência de B6-0 — critério refinado

Não basta "não duplicou". O teste precisa comprovar **reutilização**:

| Verificação | Antes do reprocessamento | Depois do reprocessamento |
|---|---|---|
| `fatura_id` | X | mesmo X |
| `CompraCartao.lancamento_id` de cada item | preenchidos | **idênticos**, não regravados |
| `Lancamento` de pagamento | 1, com id Y | **mesmo** id Y |
| Quantidade total de `Lancamento` no banco | N | **mesma** N |
| Novas linhas contábeis criadas | — | **zero** |

Isso evita uma implementação que detecte duplicidade *depois* de já ter
produzido efeitos parciais (ex.: criar 3 dos 5 lançamentos, falhar no
4º, e na reexecução criar os 2 faltantes com estado inconsistente) — daí
o requisito de transacionalidade (Guardrail 11) ser tratado como
condição de aceite, não como detalhe de implementação.

---

## 5. Schema — `pagamentos_faturas_cartao`

```text
pagamentos_faturas_cartao
├── id
├── fatura_cartao_id       UNIQUE
├── lancamento_id          UNIQUE
├── transacao_bancaria_id  UNIQUE
├── metodo_matching
├── score
├── status
├── criado_em
└── atualizado_em
```

As três unicidades materializam a restrição 1:1 em nível de banco:
nenhuma fatura com dois pagamentos, nenhum pagamento com duas
transações, nenhuma transação liquidando duas faturas.

---

## 6. Fluxo de execução

```text
FaturaCartao (FECHADA, persistida — Fase 4)
        │
        ▼
      B6-0  (transacional)
        │
        ├── N × CompraCartao → Lancamento D/C → persistido
        │                         │
        │                         └→ CompraCartao.lancamento_id
        │
        └── 1 × pagamento → Lancamento D Cartão / C Banco → persistido
                                      │
                                      ▼
                                  B6-1 — localizar pagamento
                                      │
                                      ▼
                                  B6-2 — excluir compras
                                      │
                                      ▼
                             MotorConciliacao (inalterado, 1:1)
                                      │
                                      ▼
                            TransacaoBancaria
                                      │
                                      ▼
                       pagamentos_faturas_cartao (B6-5/6/14)
                                      │
                            ┌─────────┴─────────┐
                            ▼                    ▼
                       AuditEvent          EventBusPort
                                                  │
                                                  ▼
                                 PAGAMENTO_CARTAO_IDENTIFICADO (B6-8/9)
```

---

## 7. Testes obrigatórios (bloqueantes, não apenas cobertura)

### B6-0 (novo)
1. Fatura `FECHADA` gera N lançamentos de compra + 1 de pagamento, todos persistidos.
2. `CompraCartao.lancamento_id` corretamente gravado para cada item.
3. Fatura `DIVERGENTE`/`PENDENTE` **não** gera lançamentos automaticamente.
4. Idempotência conforme critério da Seção 4 (reutilização, não apenas ausência de duplicata).
5. Transacionalidade: falha simulada no meio da geração não deixa fatura parcialmente contabilizada (rollback completo).

### Positivos (B6-1 a B6-9)
6. Pagamento da fatura encontra sua transação bancária.
7. Valor/data compatíveis → `CONCILIADO`.
8. Vínculo persistido em `pagamentos_faturas_cartao`.
9. Método de matching persistido.
10. `PagamentoCartaoIdentificado` publicado (dois catálogos).
11. Auditoria registrada.
12. Reexecução da conciliação é idempotente.

### Negativos obrigatórios — N:1 (bloqueantes)
13. Fatura R$1.000 (compras R$400+R$300+R$300) + transação R$1.000 → nenhuma compra é candidata; só o pagamento.
14. Transação R$1.000 + compra R$1.000 (mesmo valor/data do pagamento) → compra é eliminada **antes** de chegar ao motor, nunca escolhida por empate.

### Outros negativos obrigatórios
15. Duas faturas tentando usar a mesma transação.
16. Duas transações tentando liquidar a mesma fatura.
17. Pagamento já conciliado (reprocessamento não duplica vínculo).
18. Transação já conciliada.
19. Fatura `DIVERGENTE` no momento da conciliação.
20. Pagamento inexistente (B6-0 não rodou / falhou).
21. Ambiguidade entre duas transações candidatas.
22. Pagamento de cartão tentando usar Camada 1/FITID — deve permanecer impossível (Fase 5).
23. Reprocessamento completo (B6-0 + conciliação) não duplica vínculo nem evento.

---

## 8. Critério de aceite do Gate 6

1. Migration (B6-5/6/14) aplicada e revertida com sucesso (upgrade→downgrade→upgrade).
2. Vínculo 1:1 persistido e restrito por `UNIQUE` no banco.
3. `Lancamento`/`LancamentoORM` permanecem sem alteração.
4. Compras individuais excluídas por `CompraCartao.lancamento_id`, não por `categoria`.
5. Nenhum N:1 possível — comprovado pelos testes 13/14.
6. FITID permanece fora do caminho do pagamento de cartão.
7. Conciliação persistida.
8. Auditoria persistida.
9. `PagamentoCartaoIdentificado` publicado somente para conciliação efetiva (`CONCILIADO`), nunca para `DIVERGENTE`/`AMBIGUO`/`SEM_DOCUMENTO`.
10. Reprocessamento idempotente conforme critério refinado (Seção 4).
11. B6-0 transacional — testado com falha simulada.
12. Todos os testes negativos obrigatórios presentes e passando.
13. Regressão completa da suíte passando.
14. Isolamento arquitetural (`core`/`ai`/`api`) verde.
15. `ruff` limpo nos arquivos efetivamente novos/alterados.
16. `main` permanece intocado.

---

## 9. Estado final da deliberação

| Bloco | Estado |
|---|---|
| Etapa 6.1 (A×B) | **B aprovada** |
| B6-0 — geração/persistência | **Concluída** — implementada, testada, commitada (`43e1898`) |
| B6-1 — localizar pagamento | **Concluída** — implementada, testada, identidade determinística comprovada por teste (impostor) |
| B6-2 — excluir compras | **Concluída** — implementada, testada, filtro via `compras_cartao.lancamento_id`, DT-CC-03 registrada |
| B6-3 — conciliação agregada | **Concluída** — `ConciliarPagamentoFaturaCartaoUseCase`, candidato único por construção, nota de rastreabilidade DT-CC-03 aplicada |
| B6-4 — 1:1 | **Concluída** — 2 testes, contrato já majoritariamente coberto genericamente desde a Fase 5; fronteira cross-call de B6-3 documentada |
| B6-5/6/14 — vínculo persistente | Mantido, uma migration |
| FITID | Restrito à Fase 5, inalterado |
| `Lancamento` central | Intocado |
| Migration | Uma, para B6-5/6/14 |
| **Implementação** | **Ainda não autorizada** |

---

**Regra de parada.** Este artefato consolida a deliberação e está pronto
para receber autorização explícita de implementação — mas essa
autorização não está concedida por este documento. Nenhum código será
alterado até instrução explícita sua para iniciar a Fase 6.

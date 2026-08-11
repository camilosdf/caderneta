# Pauta Técnica Complementar ao ADR 010 — Gate pré-Fase 6

**Escopo:** três decisões de orquestração necessárias para a Fase 6
(Conciliação) poder ser implementada **mantendo `MotorConciliacao`
exatamente como está** (nenhuma alteração ao arquivo tocado na Fase 5) e
**preservando a proibição absoluta de N:1** (ADR 010, Seção 19).

Nenhum código foi alterado para produzir esta pauta.

---

## B6-1 — Como os lançamentos de cartão (D7/D8) alcançam `APROVADO`

**Evidência:**
- `Lancamento.aprovar(aprovador, nivel)` já existe no domínio
  (`core/domain/entities.py`) e promove `status` para `APROVADO` quando
  `nivel_aprovacao == UM_APROVADOR` — exatamente o valor que
  `construir_lancamento_compra_cartao`/`construir_lancamento_pagamento_fatura`
  (Fase 3) já atribuem. **Nenhuma alteração de domínio necessária.**
- A aprovação já é exposta genericamente via `api/routers/lancamentos.py`
  (`lancamento.status = StatusLancamento.APROVADO`) — fora de `core/`,
  já reaproveitável por qualquer `Lancamento`, cartão ou não.
- `core/cli.py` **não tem** comando de aprovação para nenhum tipo de
  lançamento hoje (nem os não-cartão) — não é uma lacuna específica de
  cartão.
- `conciliacao_executar` só considera `status=APROVADO`
  (`core/cli.py:937`).

**Decisão proposta:** a aprovação de lançamentos de cartão ocorre pelo
mecanismo genérico já existente (API), **fora do escopo da Fase 6**. Não
criar comando CLI de aprovação dedicado a cartão — seria resolver, para
cartão, uma lacuna que já existe igualmente para todos os outros tipos de
lançamento, contrariando "nenhuma refatoração não relacionada".

**Decisão necessária:** confirmar.

---

## B6-2 — Como excluir lançamentos de compra (D7) da conciliação, preservando N:1=proibido

**Evidência:**
- `conciliacao_executar` consulta **todos** os `Lancamento` `APROVADO` no
  período, sem distinguir origem. Uma vez aprovados, lançamentos de
  compra de cartão (D7) e o lançamento de pagamento (D8) ficariam
  **igualmente elegíveis** para entrar no motor.
- Nenhum campo atual marca "isto é um pagamento de fatura de cartão"
  de forma exclusiva: `construir_lancamento_compra_cartao` seta
  `categoria=compra.tipo.value` (`"compra"`, `"iof"`, `"juros"`, etc.);
  `construir_lancamento_pagamento_fatura` **não seta `categoria`**.
- **Risco real, não hipotético:** se um lançamento de compra (D7) entrar
  na consulta, ele tem `valor_total`/`data_lancamento` como qualquer
  outro — pode coincidir por acaso com uma transação bancária dentro da
  tolerância da Camada 2 e ser conciliado individualmente. Isso violaria
  a intenção da Seção 19 do ADR (nenhuma `CompraCartao`/lançamento de
  compra individual é candidato a conciliação bancária) **sem que o
  motor precise fazer nada de errado** — o problema estaria inteiramente
  no conjunto de entrada montado pelo chamador.

**Alternativas:**

| Alternativa | Descrição | Migration | Risco |
|---|---|---|---|
| **A** | Filtrar no chamador (CLI/use case da Fase 6): excluir lançamentos cujo `categoria` esteja em `{compra, iof, juros, multa, encargo, anuidade, estorno}` — usa dado já existente | Não | Frágil se `categoria` for reaproveitada por outro tipo de documento no futuro com os mesmos valores |
| **B** | Novo campo em `Lancamento` (ex.: `origem_tipo`) marcando explicitamente "pagamento_fatura_cartao" | **Sim** | Viola "nenhuma alteração em Lancamento... nenhuma migration" já vedado nos limites da Fase 5/6 |
| **C** | Não filtrar — aceitar o risco | Não | Viola a proibição de N:1 por via indireta; inaceitável |

**Recomendação:** Alternativa A. É a única compatível com os limites já
impostos (sem migration, sem alterar `Lancamento`/ORM, `MotorConciliacao`
inalterado — o filtro acontece **antes** de chamar `conciliar()`, no
chamador, exatamente como o mapa de FITID já fez na Fase 5).

**Decisão necessária:** confirmar Alternativa A, ou apontar lista de
`categoria` diferente da proposta.

---

## B6-3 — Disparo de `PagamentoCartaoIdentificado`

**Evidência:**
- Evento já existe nos dois catálogos (`core/events/catalog.py`,
  `core/audit/chain.py`) desde a Fase 4, com disparo **explicitamente
  adiado** para "a fase de conciliação" (autorização da Fase 4).
- `MotorConciliacao.conciliar()` retorna `RelatorioConciliacao` com
  `ConciliacaoItem.status` (`CONCILIADO`/`DIVERGENTE`/`AMBIGUO`/etc.) e
  `lancamento_id` — dado suficiente para o chamador saber quais itens
  conciliados correspondem a pagamentos de cartão (cruzando com a lista
  filtrada da B6-2).

**Decisão proposta:** o disparo ocorre **no chamador** (não no motor,
que permanece genérico e sem conhecimento de cartão), imediatamente após
`conciliar()` retornar, para cada `ConciliacaoItem` com
`status=CONCILIADO` cujo `lancamento_id` esteja na lista de pagamentos
de cartão (B6-2). Publicado nos mesmos dois canais já usados na Fase 4
(`EventBusPort` + `TipoEvento`), mesmo padrão de
`ProcessarFaturaCartaoUseCase`.

**Decisão necessária:** confirmar o ponto de disparo (no chamador, pós
`conciliar()`) e o critério de seleção (cruzamento com lista B6-2).

---

## Resumo

| Decisão | Recomendação | Requer migration | Requer alterar `MotorConciliacao` | Requer alterar `Lancamento` |
|---|---|---|---|---|
| B6-1 | Aprovação via mecanismo já existente (API), fora de escopo | Não | Não | Não |
| B6-2 | Filtro por `categoria` no chamador | Não | Não | Não |
| B6-3 | Disparo no chamador, pós-`conciliar()`, cruzando com B6-2 | Não | Não | Não |

Todas as três recomendações preservam `MotorConciliacao` exatamente como
está e não introduzem nenhum caminho N:1 — o filtro de B6-2 é
precisamente o mecanismo que impede compras individuais de cartão de
sequer chegarem ao motor.

---

**Regra de parada.** Nenhum código alterado. Aguardando fechamento formal
de B6-1/B6-2/B6-3 antes de qualquer inspeção adicional ou autorização de
código para a Fase 6.

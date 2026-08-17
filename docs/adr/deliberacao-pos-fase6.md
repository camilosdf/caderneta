# Deliberação Pós-Fase 6 — ADR 010 / Estado do Roadmap

**Natureza:** etapa de governança, não de desenvolvimento. Nenhum código
alterado para produzir este documento.

---

## 1. Baseline congelado

```
feature/cartao-credito @ f94bd44d10a936be57200542ceabf74cedb51f34
```

Este é o commit de referência validado: 836/836 testes, isolamento,
hermeticidade e autenticação verdes, validado em PostgreSQL real.
Qualquer trabalho futuro parte daqui — este documento não reabre nada
anterior a este hash.

## 2. `main` — confirmação

Intocado desde o início desta esteira (`7deee47`). Nenhuma ação deste
documento o altera.

## 3. Estado real do roadmap/Gate 0 — revalidado com evidência atual

A `Matriz de Prontidão v0.999` original (`docs/caderneta_matriz_prontidao_v0999.docx`)
foi escrita em `v0.014.003` (668 testes), **antes** de toda a Fase 6 desta
feature. Revalidei os itens críticos contra o código real agora:

| Item da matriz original | Status na matriz original | Status real agora (evidência) |
|---|---|---|
| Migration Alembic `transacoes_bancarias` | ✗ BLOQUEADOR | ✓ **RESOLVIDO** — é exatamente o "B2" desta esteira, commitado (`03a2fd8`), validado em Postgres real |
| `TipoEvento.VERSAO_HOMOLOGADA` | ✗ BLOQUEADOR | ✗ **AINDA BLOQUEADOR** — `grep VERSAO_HOMOLOGADA core/audit/chain.py` não retorna nada |
| Versão declarada vs. etapas concluídas | ⚠ DECISÃO | ⚠ **AINDA PENDENTE, mais grave** — `VERSAO_ATUAL="0.9.0"` inalterado, e agora toda a Fase 6 de cartão foi adicionada sem nenhum reflexo na versão |
| Segregação de funções (criador≠aprovador) | ⚠ DECISÃO CRÍTICA | ⚠ **AINDA PENDENTE** — `api/routers/lancamentos.py:123`, `criador_id=""` confirmado no código atual |
| Ruff zerado | ⚠ DECISÃO (183 erros) | ⚠ **PIOR** — `ruff check .` agora acusa **304 erros** em todo o repositório (aumento esperado, mais código; nunca foi objetivo desta feature corrigir débito pré-existente) |
| `.env.example` | ⚠ DECISÃO | ⚠ **AINDA PENDENTE** — arquivo não existe |
| Backup/recuperação | ⚠ DECISÃO | Não revalidado nesta etapa (fora do escopo de cartão, sem evidência nova) |
| Modelo de embedding (benchmark) | ⚠ DECISÃO | Não revalidado nesta etapa |
| Testes de propriedade (Hypothesis) | ⚠ DECISÃO | Não revalidado nesta etapa |
| Open Finance | ◯ FORA v1.0.0 | Inalterado — `ADR 009` continua reservado para isso, confirmado nesta esteira |

**Achado central:** dos 2 bloqueadores originais do Gate 0, **1 foi
resolvido por esta feature** (como efeito do trabalho de B2, não como
objetivo original) e **1 continua sem nenhuma ação** —
`VERSAO_HOMOLOGADA`, que o próprio parecer original já classificava como
trivial ("uma linha de código, zero impacto em testes existentes").

## 4. Pendências reais — inventário consolidado

Une o achado acima com o levantamento já feito na pauta anterior
(débitos específicos de cartão).

### ✗ BLOQUEADOR (impede a tag `v0.999`, por definição do próprio Gate 0)

| # | Item | Evidência | Esforço estimado (fonte: matriz original) |
|---|---|---|---|
| 1 | `TipoEvento.VERSAO_HOMOLOGADA` ausente | `core/audit/chain.py`, `ADR 007:175-177` | "uma linha de código" |

### ⚠ DECISÃO (requer deliberação formal, não é implementação trivial sem decisão prévia)

| # | Item | Quem decide | Evidência |
|---|---|---|---|
| 2 | Segregação de funções criador≠aprovador | Especialista em Controles Internos | `api/routers/lancamentos.py:123`, `ADR 007:180` |
| 3 | `VERSAO_ATUAL` desatualizada (agora inclui toda a Fase 6) | Equipe/Direção | `core/versao.py:20` |
| 4 | Ruff — 304 erros, zerar ou não antes de v0.999 | Equipe/Direção | `ruff check .` |
| 5 | `.env.example` ausente | Equipe/Direção (implementação simples, mas requer levantar variáveis reais de produção) | `find . -iname .env.example` (vazio) |
| 6 | Backup/recuperação não documentado | Direção/Ops | Não revalidado agora — herdado da matriz original |
| 7 | Modelo de embedding — MiniLM vs. bert-large | Direção técnica | Não revalidado agora — herdado |
| 8 | Testes de propriedade (Hypothesis) para v1.0.0 | Equipe | Não revalidado agora — herdado |
| 9 | D12 (competência de parcelas, cartão) — parecer CRC pendente | Contador CRC | Registrado no ADR 010, sem confirmação de que o parecer ocorreu |
| 10 | B3 (classificação de tipo de item, cartão) — validação contra fatura real | Equipe (precisa de dado real) | Sem exemplo real disponível, registrado no ADR 010 |
| 11 | D19/exigência de CRC para D9/D10/D12 (cartão) | Direção | Registrado como "recomendação a deliberar", não fechado |

### ▷ IMPLEMENTAÇÃO (sem decisão pendente — só falta codificar, quando priorizado)

| # | Item | Evidência |
|---|---|---|
| 12 | CLI para B6-0/B6-3/B6-5–8 (cartão) — nenhum comando aciona esses use cases hoje | `core/cli.py`, levantado na pauta anterior |
| 13 | DT-CC-01 — persistência de `ContaContabil` | ADR 010 |
| 14 | DT-CC-02 — `confidence` de `CompraCartao` não sobrevive ao round-trip | ADR 010 |
| 15 | DT-CC-03 — `limit=100` sem filtro temporal nativo | ADR 010 |
| 16 | Migration para `usuarios` (mesma classe de B2, nunca gerada) | `core/infra/db/models.py:286`, confirmado nesta sessão |
| 17 | Teste de validação do mapeamento GnuCash para conta de Passivo do cartão (Fase 7 original) | ADR 010, D18 |

### ◯ PÓS-v1.0.0 (fora de escopo por decisão já formal)

| # | Item | Evidência |
|---|---|---|
| 18 | Open Finance | ADR 009 (reservado), Matriz de Prontidão original |
| 19 | Ajustes de fatura pós-fechamento (cartão) | ADR 010, D11 |

## 5. O que este documento NÃO resolve

Nenhum item acima foi decidido aqui. Isto é levantamento de evidência e
classificação, não deliberação de mérito — especialmente os itens 2, 6,
7, 9 e 11, que dependem de pessoas/papéis fora desta conversa
(Especialista em Controles, Contador CRC, Direção).

## 6. Proposta de próxima unidade de trabalho — uma só

Entre os 19 itens, **apenas o item 1 (`VERSAO_HOMOLOGADA`)** reúne todas
as características que o Caderneta exige para ser a próxima unidade:

- É o único **bloqueador real** de todo o inventário.
- Não depende de decisão de terceiro (Especialista, Contador CRC,
  Direção) — é puramente técnico.
- O próprio parecer original já o descreve como trivial e de impacto
  zero em testes existentes.
- Resolvê-lo fecha **os dois bloqueadores originais do Gate 0** — o
  outro já foi resolvido por esta feature.

**Proposta (não decisão):** a próxima unidade de trabalho seja
exclusivamente adicionar `VERSAO_HOMOLOGADA` a `TipoEvento`
(`core/audit/chain.py`), sem qualquer outra alteração — mesmo padrão de
"menor alteração arquiteturalmente correta" já usado em toda a esteira.
Isso não resolve os itens de DECISÃO (que continuam exigindo
deliberação própria, de pessoas fora desta conversa), mas fecha
definitivamente a categoria BLOQUEADOR.

---

**Regra de parada.** Nenhum código foi alterado. Aguardando sua decisão
sobre a classificação acima e, especificamente, se a próxima unidade de
trabalho proposta (item 1) é a que deve prosseguir.

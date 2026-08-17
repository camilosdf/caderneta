# ADR 011 — Persistência de `ContaContabil` (DT-CC-01)

**Status:** Em aberto — decisão pendente entre Opção A e Opção B (ver Seção "Decisão"). Nenhuma implementação autorizada por este documento.
**Data:** 2026-08
**Decisores:** Direção do projeto
**Origem:** DT-CC-01 (ADR 010, Seção "Débito técnico registrado — DT-CC-01"), aprofundado em `docs/adr/revisao-deliberativa-dtcc-d18.md` e na inspeção formal DT-CC-01.1 (branch `feature/cartao-credito`, HEAD `e710d63`).
**Branch:** `feature/cartao-credito` — não mesclado em `main`

---

## Contexto

`ContaContabil` (`core/domain/entities.py:282-301`) existe como entidade de
domínio completa — com `permite_lancamento`, `centro_custo_obrigatorio` e
demais regras de negócio — mas **não tem persistência própria em nenhuma
parte do sistema**. Não há `ContaContabilORM`, tabela `contas_contabeis`,
nem integridade referencial de contas contábeis.

Toda referência de conta efetivamente persistida é string livre, sem FK:

- `SplitORM.conta_codigo` (`core/infra/db/models.py:106`) — usado por
  **todo** lançamento do sistema (NF-e, OFX, CSV, cartão).
- `CartaoCreditoORM.conta_codigo` (`core/infra/db/models.py:370`) — mesmo
  padrão, herdado deliberadamente do primeiro.

Confirmado por conteúdo de migration
(`infra/migrations/versions/3c164a335ab2_...py:1-6`): "Não há tabela
contas_contabeis nem ContaContabilORM neste projeto — fora de escopo do
ADR 010".

**Efeito prático hoje:** `LancamentoService.__init__(contas_por_codigo=...)`
é o único consumidor de `ContaContabil` como tipo, e recebe `{}` por
default em todo caminho de produção. `_validar_contas_e_centro_custo` só
age quando `conta is not None` — hoje sempre `None`. As validações
`permite_lancamento`/`centro_custo_obrigatorio` estão **inertes em
produção**, não por bug, mas porque nada popula esse dict a partir de uma
fonte persistida real. O próprio teste `test_conta_nao_cadastrada_nao_bloqueia`
(`tests/unit/core/test_lancamento_service.py`) formaliza esse
comportamento como esperado hoje.

O sistema opera, portanto, com **duas semânticas paralelas** para conta:
`ContaContabil` como conceito de domínio com regras, e `CodigoConta` como
string persistida sem vínculo com esse cadastro. Não é uma lacuna que uma
tabela nova resolva sozinha — depende de qual nível de integridade se
decide adotar.

Descoberto durante o trabalho de cartão (D6), mas **não específico de
cartão** — mesma classe de tratamento já dada ao débito técnico do FITID
(D14): descoberto durante uma feature, não causado por ela, não resolvido
como efeito colateral.

---

## Decisão

**Ainda não tomada.** Este ADR registra duas alternativas tecnicamente
válidas, sem meio-termo artificial entre elas, para deliberação da Direção.

### Opção A — Cadastro aditivo, sem FK

Criar `ContaContabilORM` + `conta_contabil_repository.py`, espelhando o
padrão já existente e comprovado em `CentroCustoORM` /
`centro_custo_repository.py`. `SplitORM.conta_codigo` permanece string
livre, sem alteração.

- **Resolve:** a inércia das validações de negócio — `contas_por_codigo`
  passa a poder ser populado a partir de um cadastro real.
- **Não resolve:** integridade referencial. Um `Split.conta_codigo`
  continua podendo referenciar um código inexistente no cadastro, sem
  erro.
- **Risco de regressão:** Baixo — estritamente aditivo, não toca
  `SplitORM` nem nenhuma query existente.
- **Impacto arquitetural:** Baixo.
- **Isolável:** Sim — schema, repository, migration nova, sem mudança de
  domínio (`ContaContabil` já está correto).
- **Risco de percepção:** Alto se comunicada como "resolução de DT-CC-01"
  — resolve o cadastro, não a integridade que dá nome ao débito técnico
  original. Deve ser registrada como correção parcial, não como
  fechamento do item.

### Opção B — Cadastro + FK real em `Split`

Tudo da Opção A, mais `SplitORM.conta_codigo` como chave estrangeira
obrigatória para `contas_contabeis`.

- **Resolve:** a lacuna de integridade referencial por completo.
- **Exige:** inventário de todo `conta_codigo` já em uso em produção
  (todos os tipos de lançamento, não só cartão), migração de dados para
  popular `contas_contabeis` a partir desse histórico, validação de
  ausência de códigos órfãos, e só então a constraint.
- **Risco de regressão:** Alto — toca o núcleo contábil usado por todos
  os fluxos do sistema, não uma tabela isolada.
- **Impacto arquitetural:** Alto — muda o modelo, não é "uma tabela a
  mais".
- **Isolável:** Não.

### Tabela comparativa

| | Opção A | Opção B |
|---|---|---|
| Resolve DT-CC-01 por completo | Não | Sim |
| Risco de regressão | Baixo | Alto |
| Impacto arquitetural | Baixo | Alto |
| Isolável | Sim | Não |
| Migração de dados históricos | Não | Sim |
| Exige ADR próprio para execução | Este documento basta | Sim, plano de migração de dados detalhado antes de implementar |

### Registrado explicitamente

- A Opção A **não está autorizada por omissão**. Implementá-la sem
  deliberação da Direção correria o risco de ser tratada como fechamento
  de DT-CC-01 quando, na prática, seria uma correção parcial.
- A Opção B, se escolhida, requer plano de migração de dados detalhado
  (inventário de códigos em uso, tratamento de órfãos, sequência
  upgrade/downgrade) antes de qualquer implementação — não é escopo
  deste ADR, é pré-requisito para abrir esse escopo.
- Nenhuma das duas opções altera D18 (validação de mapeamento GnuCash via
  `ExportadorCSV`) ou reabre DT-CC-02/DT-CC-03, já implementados e
  publicados (`e710d63`). D18 é teste de exportação, sem relação com
  schema de conta — permanece deliberadamente separado.

---

## Testes necessários (quando uma opção for autorizada)

**Opção A:** round-trip de `ContaContabilORM`; regressão completa de
`test_lancamento_service.py` com `contas_por_codigo` agora populável a
partir de persistência real.

**Opção B:** todos os da Opção A, mais: migração de dados testada em
banco representativo (não só limpo), verificação de órfãos pré-migração,
sequência upgrade → downgrade → upgrade, regressão completa de todos os
módulos que geram `Lancamento` (NF-e, OFX, CSV, cartão).

---

## Decisão necessária da Direção

Escolher: Opção A (isolada, correção parcial, registrada como tal) |
Opção B (abrir plano de migração de dados antes de implementar) |
manter DT-CC-01 em deliberação sem prazo definido.

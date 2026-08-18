# ADR 011 — Persistência de `ContaContabil` (DT-CC-01)

**Status:** Em aberto — decisão pendente entre Opção A e Opção B (ver Seção "Decisão"). Nenhuma implementação autorizada por este documento.
**Data:** 2026-08
**Decisores:** Direção do projeto
**Origem:** DT-CC-01 (ADR 010, Seção "Débito técnico registrado — DT-CC-01"), aprofundado em `docs/adr/revisao-deliberativa-dtcc-d18.md`, na inspeção formal DT-CC-01.1 (branch `feature/cartao-credito`, HEAD `e710d63`), no inventário de código-fonte DT-CC-01.2 e no achado de estado de produção DT-CC-01.3 (ambos abaixo).
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

## DT-CC-01.2 — Inventário de código-fonte (sem alteração de código)

Todas as origens de `conta_codigo`/`CodigoConta` no sistema, não só cartão:

| Fonte | Arquivo | Natureza |
|---|---|---|
| Motor tributário | `core/rule_engine/tax_engine.py:139-155` | Catálogo fixo hardcoded — `CONTAS_TRIBUTARIAS_PADRAO`, 8 códigos em dict Python |
| Regras de classificação | `core/cli.py:81-105` | Carregadas de `dados/regras/regras_padrao.json` — arquivo opcional, **fora do controle de versão** (não existe no repo) |
| Fallback de classificação | `core/rule_engine/classification_impl.py:41-42` | Configurável por construtor, livre |
| Cartão — conta do cartão (D6) | `core/cli.py:1136` | Persistida em `CartaoCreditoORM.conta_codigo`, atribuída como string livre na primeira identificação |
| Cartão — despesas/banco/estorno | `core/cli.py:1261-1280` | 8 parâmetros de CLI, **não persistidos**, redigitados a cada execução |
| Parsers (NF-e, OFX, CSV, Nubank) | `core/parsers/` | Nenhuma referência a conta — não decidem conta |

`CodigoConta.__post_init__` valida só formato (1-5 níveis numéricos). Não há catálogo central editável nem validação de existência em nenhum ponto. **Formato válido ≠ conta cadastrada ≠ conta contabilmente válida.**

## DT-CC-01.3 — Achado de estado de produção (sem alteração de código)

O inventário de valores de `conta_codigo` efetivamente persistidos exigiria consulta a uma base real. Diagnóstico na VM de homologação (`caderneta-test`) confirmou: `DATABASE_URL` aponta para um Postgres local (`postgresql+psycopg://...localhost:5432/caderneta`) que **não está instalado nem em execução** nesse ambiente (sem unit systemd, sem cluster, sem container) — só o cliente `psql`.

Questionada diretamente, a Direção do projeto confirmou: **não existe base de produção real em uso hoje**, em nenhum ambiente — o sistema está exclusivamente em homologação/desenvolvimento (`feature/cartao-credito`, não mesclada a `main`).

**Efeito sobre a avaliação de risco da Opção B:** o principal risco atribuído à Opção B — migração de histórico de `conta_codigo` já em produção, com possíveis códigos órfãos — **não se materializa hoje**, por ausência do próprio histórico produtivo a migrar. A implementação da Opção B, se autorizada agora, seria essencialmente greenfield: catálogo e FK podem ser definidos antes de existir dado real a conciliar.

Isso **não elimina** o impacto arquitetural da Opção B — `Split.conta_codigo` continua sendo usado por todo lançamento do sistema (NF-e, OFX, CSV, cartão), e uma FK obrigatória é um compromisso de modelo permanente daqui em diante, independente de haver ou não dado histórico agora. Também não é uma condição permanente: se o sistema for para produção antes de uma decisão sobre DT-CC-01, esta seção deixa de refletir o estado real e precisa ser reverificada antes de qualquer implementação de Opção B.

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
- **Exige (se houver produção com histórico):** inventário de todo
  `conta_codigo` já em uso, migração de dados para popular
  `contas_contabeis` a partir desse histórico, validação de ausência de
  códigos órfãos, e só então a constraint.
- **Risco de regressão — condicional, ver DT-CC-01.3:** confirmado hoje
  (Direção, DT-CC-01.3) que **não existe produção real em uso** — logo o
  risco de migração de histórico/órfãos, que classificava este item como
  Alto, **não se materializa no estado atual**. Reavaliar antes de
  qualquer produção real existir.
- **Impacto arquitetural:** Alto, independente de dado histórico — toca
  o núcleo contábil usado por todos os fluxos do sistema (`Split`, logo
  NF-e/OFX/CSV/cartão), é um compromisso de modelo permanente daqui em
  diante.
- **Isolável:** Não, arquiteturalmente (toca `SplitORM` e todo consumidor
  de `Split.conta_codigo`) — mas hoje, sem histórico a migrar, a
  implementação em si é tecnicamente mais simples que uma migração de
  legado.

### Tabela comparativa

| | Opção A | Opção B |
|---|---|---|
| Resolve DT-CC-01 por completo | Não | Sim |
| Risco de regressão | Baixo | **Baixo hoje** (sem produção — DT-CC-01.3) / Alto se já houver produção com histórico |
| Impacto arquitetural | Baixo | Alto (independente de haver dado histórico) |
| Isolável | Sim | Não, arquiteturalmente — mas sem histórico a migrar hoje |
| Migração de dados históricos | Não | Não hoje (sem produção) — Sim, se produção existir antes da implementação |
| Exige ADR próprio para execução | Este documento basta | Este documento basta **enquanto a condição de DT-CC-01.3 se mantiver**; se houver produção real antes da implementação, exige plano de migração de dados detalhado à parte |

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
Opção B (hoje, greenfield — sem plano de migração de dados necessário,
condicionado à ausência de produção confirmada em DT-CC-01.3) |
manter DT-CC-01 em deliberação sem prazo definido.

Se a decisão for adiada e o sistema for para produção antes de uma
implementação, a condição de DT-CC-01.3 deve ser reverificada — a
avaliação de risco da Opção B registrada aqui deixa de valer assim que
existir histórico produtivo de `conta_codigo`.

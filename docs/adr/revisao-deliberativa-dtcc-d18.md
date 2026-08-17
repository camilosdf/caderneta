# Revisão Deliberativa — Itens de Implementação Restantes

**Escopo:** DT-CC-01, DT-CC-02, DT-CC-03, D18. D1–D7 e D12/D19
permanecem explicitamente fora — dependem de deliberação de
Especialista em Controles, Direção ou Contador CRC, não desta revisão.

Nenhum código foi alterado para produzir este documento.

---

## DT-CC-01 — Persistência de `ContaContabil`

### Evidência atual
`class ContaContabil` existe **só como entidade de domínio**
(`core/domain/entities.py:282`) — nenhum `ContaContabilORM`. Toda
referência a conta no banco é string livre sem FK:
`SplitORM.conta_codigo` (`models.py:109`) e `CartaoCreditoORM.conta_codigo`
(`models.py:370`) — o **mesmo padrão em ambos**, não uma peculiaridade
de cartão.

### Dependências
Nenhuma decisão externa pendente — é puramente técnico. Mas
tecnicamente depende de decidir **o que fazer com todo o histórico de
`Split.conta_codigo`** já persistido como string livre em produção
(se existir), não só o de cartão.

### Risco de regressão
**Alto.** `conta_codigo` é usado por **todo** lançamento do sistema —
NF-e, OFX, CSV, cartão — não é uma tabela isolada como `usuarios` ou
`transacoes_bancarias`. Migrar de string livre para FK obrigatória
exigiria: (a) popular `contas_contabeis` a partir de todo código já em
uso, (b) validar que nenhum `conta_codigo` órfão existe, (c) só então
adicionar a constraint. Cada uma dessas etapas tem superfície de
regressão real.

### Impacto arquitetural
**Alto.** Não é "uma tabela a mais" — é uma mudança de modelo que toca
o núcleo contábil (`Split`, `Lancamento`) usado por todos os fluxos,
não só cartão.

### Relação com ADR 010
Descoberto durante o trabalho de cartão (D6), mas **não é específico
de cartão** — o próprio ADR já registra isso: "criação de infraestrutura
persistente de contas contábeis fica fora do escopo do ADR 010".

### Execução isolada?
**Não.** Por natureza, qualquer correção real toca `SplitORM` — usado
por todo o sistema. Não é isolável ao módulo de cartão.

### Testes necessários (se autorizado no futuro)
Migração de dados (não só schema), validação de integridade retroativa,
regressão completa de todos os módulos que geram `Lancamento`.

### Arquivos que seriam tocados
`core/domain/entities.py`, `core/infra/db/models.py`, `core/infra/repositories/*`
(múltiplos), nova migration, potencialmente script de migração de dados.

---

## DT-CC-02 — `confidence` de `CompraCartao` no round-trip

### Evidência atual
`CompraCartaoORM` não tem coluna `confidence`. Confirmado o efeito
prático: `GerarLancamentosFaturaCartaoUseCase` (B6-0) sempre recarrega
a fatura via `uow.faturas_cartao.buscar_por_id(...)` **antes** de
chamar `LancamentoService.construir_lancamento_compra_cartao`
(`core/rule_engine/lancamento_service.py:283`, que lê
`compra.confidence.valor if compra.confidence else None`). Como
`FaturaCartaoRepository._item_para_dominio` sempre retorna
`confidence=None`, **isso significa que, no fluxo real de produção
(B6-0), a confiança já está perdida antes mesmo de chegar ao
lançamento** — não é um risco teórico, é o comportamento atual sempre
que B6-0 roda sobre uma fatura persistida (que é o único jeito real de
rodar B6-0).

### Dependências
Nenhuma.

### Risco de regressão
**Baixo.** Nova coluna nullable em `compras_cartao`, só populada — não
altera nenhum campo existente, não altera nenhuma query de outra
tabela.

### Impacto arquitetural
**Baixo/nenhum.** Estritamente aditivo, contido em uma tabela já
específica de cartão.

### Relação com ADR 010
Diretamente — é o débito técnico já nomeado (DT-CC-02), com o efeito
prático confirmado nesta revisão (a perda já acontece no fluxo real de
B6-0, não é hipotética).

### Execução isolada?
**Sim.** Toca só `CompraCartaoORM`, `FaturaCartaoRepository`
(`_item_para_orm`/`_item_para_dominio`), e a migration correspondente.

### Testes necessários
Round-trip: salvar `CompraCartao` com `confidence` preenchido, recarregar,
confirmar que sobrevive. Teste de regressão em B6-0 confirmando que o
`Lancamento` gerado agora carrega a confiança correta quando presente.

### Arquivos que seriam tocados
`core/infra/db/models.py` (coluna nova em `CompraCartaoORM`),
`core/infra/repositories/cartao_repository.py` (`_item_para_orm`/`_item_para_dominio`),
nova migration.

---

## DT-CC-03 — `limit=100` sem filtro temporal em `listar_por_empresa`

### Evidência atual
`LancamentoRepository.listar_por_empresa` (`core/infra/repositories/lancamento_repository.py:55`)
já aceita `data_inicio`/`data_fim` nativamente. **Dois pontos de
chamada no CLI:**
- `core/cli.py:621` (comando de listagem genérica) — já expõe
  `--limite` ajustável ao usuário, risco menor.
- `core/cli.py:936` (`conciliacao_executar`) — chama sem
  `data_inicio`/`data_fim`, filtra em Python **depois** do fetch já
  limitado a 100. É este o ponto real do débito.

### Dependências
Nenhuma decisão externa. Mas **não é específico de cartão** —
`conciliacao_executar` é usado por qualquer tipo de lançamento
(NF-e, OFX, CSV, cartão).

### Risco de regressão
**Médio.** É um caminho já testado (Fases 5/6, B6-2/B6-4 dependem
diretamente deste método). Mudar a chamada para passar
`data_inicio`/`data_fim` nativamente é uma alteração pequena, mas em
um arquivo compartilhado por múltiplos fluxos já em produção — exige
regressão completa de toda a suíte de conciliação, não só cartão.

### Impacto arquitetural
**Baixo.** Não muda modelo nem contrato — só passa parâmetros já
existentes no método, hoje não utilizados nessa chamada específica.

### Relação com ADR 010
Descoberto durante B6-2, mas **não é específico de cartão** — afeta
qualquer empresa com mais de 100 lançamentos aprovados no período,
independente de ter cartão ou não.

### Execução isolada?
**Parcialmente.** A mudança em si é isolada (uma chamada em
`core/cli.py`), mas o teste de regressão necessário não pode ficar
restrito a cartão — precisa confirmar que `conciliacao_executar`
continua correto para todos os tipos de lançamento.

### Testes necessários
Cenário com >100 lançamentos aprovados no período, confirmando que
todos os relevantes ao período aparecem (hoje truncariam antes do
filtro de data). Regressão completa da suíte de conciliação (Fase 5/6).

### Arquivos que seriam tocados
`core/cli.py` (só a chamada em `conciliacao_executar`), teste novo.

---

## D18 — Teste de validação do mapeamento GnuCash

### Evidência atual
**Não existe exportador dedicado a GnuCash** — o único mecanismo de
exportação é `ExportadorCSV` (`core/adapters/csv_exporter.py`),
genérico, sem nenhuma referência a `guid_gnucash`. O campo
`Lancamento.guid_gnucash` existe e é vinculável manualmente via CLI
(`core/cli.py:687`, comando de vínculo de GUID), mas o exportador CSV
em si não o usa.

D18 (ADR 010) decide **"sem alteração no exportador; validar mapeamento
via teste"** — ou seja, a decisão já tomada é que o exportador genérico
deveria funcionar sem modificação para lançamentos de cartão, porque
eles são `Lancamento`/`Split` comuns (D7/D8 não criam nenhum campo novo
em `Split`). O que falta é **só o teste que comprove isso**, não código
de produção novo.

### Dependências
Nenhuma decisão pendente — D18 já está deliberada e aprovada
(`docs/adr/010-fatura-cartao-credito.md:521`). Só falta a evidência de
teste.

### Risco de regressão
**Nenhum** — se a hipótese de D18 estiver correta (nenhuma alteração
de código), é só teste novo. Se o teste **revelar** que o exportador
não lida bem com algo específico de cartão (ex.: `conta_codigo` do
Passivo do cartão exportado incorretamente), isso vira um achado a
reportar, não uma correção silenciosa dentro desta unidade.

### Impacto arquitetural
Nenhum, por definição de D18 (nenhuma alteração de exportador).

### Relação com ADR 010
Direta — é a própria D18, ainda com sua condição de aceite ("validar
mapeamento via teste") não cumprida.

### Execução isolada?
**Sim, total.** Só teste novo, usando a suíte de fixtures já existente
de `test_csv_exporter.py` (178 linhas, já testa o exportador
genericamente) mais um lançamento de cartão real (D7 ou D8) como
entrada.

### Testes necessários
Gerar um `Lancamento` de compra e um de pagamento (D7/D8, via
`LancamentoService` já testado), exportar via `ExportadorCSV`, e
confirmar que a conta de Passivo do cartão (D6) aparece corretamente
mapeada na saída — sem nenhuma alteração no exportador.

### Arquivos que seriam tocados
Só teste novo (`tests/unit/core/...`), nenhum arquivo de produção.

---

## Tabela comparativa

| | DT-CC-01 | DT-CC-02 | DT-CC-03 | D18 |
|---|---|---|---|---|
| Específico de cartão | Não | Sim | Não | Sim |
| Risco de regressão | **Alto** | Baixo | Médio | **Nenhum** |
| Impacto arquitetural | **Alto** | Baixo | Baixo | Nenhum |
| Isolável | **Não** | Sim | Parcial | **Sim, total** |
| Migration necessária | Sim | Sim | Não | Não |
| Depende de decisão externa | Não | Não | Não | Não |
| Efeito real já confirmado nesta revisão | Não medido | **Sim — perda já ocorre em B6-0 hoje** | Sim — 2º call site confirmado | N/A (só teste) |
| Código de produção novo | Muito | Pouco | Pouco | **Zero** |

## Critérios de parada (comuns aos quatro, se algum for autorizado)

Regressão completa · isolamento · hermeticidade · ruff · nenhum item
fora do escopo autorizado tocado · nenhuma migration além da
estritamente necessária ao item escolhido · relatório com evidência
antes/depois.

## Recomendação de prioridade — não é decisão

Do menor para o maior risco/esforço:

1. **D18** — zero código de produção, zero risco, fecha uma decisão já
   aprovada que só espera evidência.
2. **DT-CC-02** — isolado, baixo risco, e esta revisão já confirmou que
   o efeito prático (perda de confiança) **já está ocorrendo hoje** em
   todo uso real de B6-0, não é hipotético.
3. **DT-CC-03** — precisa de regressão mais ampla (toca caminho
   compartilhado com não-cartão), mas mudança de código pequena e já
   comprovadamente testável.
4. **DT-CC-01** — maior risco, maior impacto, não isolável a cartão;
   recomendaria tratar como uma iniciativa própria, fora do ritmo de
   "uma unidade pequena por vez" que guiou tudo até aqui, não como
   próximo item desta lista.

---

**Nenhuma implementação autorizada por este documento.** Aguardando
sua decisão sobre qual(is) item(ns) prosseguir, e em que ordem.

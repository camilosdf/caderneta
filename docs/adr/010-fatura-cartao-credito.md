# ADR 010 — Faturas de Cartão de Crédito

**Status:** Aprovado e congelado documentalmente. Implementação em andamento — Fases 0 a 5 concluídas (schema, domínio, PDF/OCR, contabilidade D7/D8, idempotência/eventos/CLI, correção do FITID via B4-B). Fase 6 (Conciliação) aguardando gate de inspeção/autorização.
**Numeração:** originalmente redigido sob o número ADR 009; corrigido para **ADR 010** por colisão identificada — `ADR 009` permanece reservado para o registro de Open Finance como escopo pós-`v1.0.0` (`docs/caderneta_matriz_prontidao_v0999.docx`, Sequência Recomendada para v0.999, item 4). O ADR 009 de Open Finance não foi alterado nem renumerado.
**Data:** 2026-08
**Decisores:** Direção do projeto (deliberação arquitetural e contábil registrada nesta consolidação, com parecer contábil específico para D9/D10/D12 — ver Seção "Requisito externo/CRC")
**Branch:** `feature/cartao-credito` — não mesclado em `main`

---

## Contexto

O Caderneta não possui, hoje, nenhum tratamento para faturas de cartão de
crédito. Um Parecer Técnico de Prontidão (Fase A/B, branch
`feature/cartao-credito`) confirmou com evidências:

- Nenhum ADR, item da Matriz de Prontidão ou da Pauta do Gate 0 menciona
  cartão ou fatura.
- Existe um parser CSV de fatura Nubank (`core/parsers/csv/nubank.py`) que
  trata cada linha da fatura como uma transação bancária isolada — não como
  item de uma fatura vinculada a um passivo.
- `Documento` é 1:1 com uma transação; incompatível com uma fatura de N itens.
- `LancamentoService._gerar_splits` gera um único par Débito/Crédito por
  documento — sem suporte a "compra gera passivo" e "pagamento baixa
  passivo" como dois lançamentos distintos.
- Campos de parcelamento (`e_parcelado`, `parcela_atual`, `total_parcelas`,
  `lancamento_pai_id`) já existem em `Lancamento`, mas nenhum parser ou
  serviço os popula a partir de um documento real.
- Não há parser de PDF registrado em `ParserFactory` (só `NFE_XML`, `OFX`,
  `CSV`); `OCRPlugin` existe mas está desconectado do pipeline real.
- **Achado novo desta fase:** o matching por FITID em
  `MotorConciliacao._fitid_do_lancamento` está quebrado — verifica um campo
  (`numero_documento_origem`) que não existe em `Lancamento`. Confirmado por
  ausência de qualquer teste que exercite esse caminho. Isto não é causado
  pela proposta de cartão, mas qualquer solução de conciliação de pagamento
  de fatura não pode assumir que esse caminho funciona.

Este ADR propõe a arquitetura para incorporar a funcionalidade **sem**
alterar o motor contábil de forma incompatível com o restante do sistema,
**sem** duplicar componentes existentes, e **sem** comprometer o Gate 0.

Nenhum código foi alterado para produzir este documento.

---

## 3.1 — Modelo de domínio

### Alternativa A — Agregado dedicado

```text
Documento
   └── FaturaCartao
          └── CompraCartao (N)
```

`FaturaCartao` e `CompraCartao` como entidades novas no domínio, com
relação explícita a `CartaoCredito` e a `ContaContabil` (Passivo).

### Alternativa B — Documento com itens

```text
Documento
   ├── item 1
   ├── item 2
   └── item N
```

Estender `Documento` para carregar uma lista de itens internos, sem criar
agregado novo.

### Alternativa C — Documento pai/filhos via `Lancamento.lancamento_pai_id`

Cada item da fatura vira um `Documento` próprio (como hoje o CSV Nubank já
faz), e o vínculo entre eles e o "documento fatura" original é feito via um
campo de referência cruzada (análogo ao uso já existente de
`lancamento_pai_id` para estornos/parcelas), sem criar `FaturaCartao` como
classe de domínio.

| Alternativa | Vantagens | Desvantagens | Impacto | Recomendação |
|---|---|---|---|---|
| **A — Agregado dedicado** | Modela o domínio real (fatura tem identidade própria: período, vencimento, titular); permite validação de fechamento da fatura (itens + encargos − créditos = total) como invariante do agregado; caminho natural para múltiplos emissores futuros | Entidade nova = migration nova, repositório novo, mais superfície de código | Alto no curto prazo, menor dívida técnica no médio prazo | **Recomendada** |
| **B — Documento com itens** | Menor superfície de mudança aparente | `Documento` hoje é 1:1 com transação em todo o pipeline (`ProcessarDocumentoUseCase`, `ParserFactory`, auditoria); forçar N itens dentro dele quebra essa invariante implícita em múltiplos pontos não isolados | Alto e disperso — risco de regressão em fluxos que assumem `Documento` = 1 transação | Rejeitada |
| **C — Pai/filhos via referência cruzada** | Reaproveita padrão já existente (`lancamento_pai_id`); menor entidade nova | Documento não tem hoje campo equivalente (`lancamento_pai_id` é de `Lancamento`, não de `Documento`); mistura conceito de fatura com conceito de parcelamento, que são coisas diferentes; validação de fechamento da fatura fica difícil de expressar sem uma entidade agregadora | Médio, mas semanticamente incorreto | Rejeitada |

**Decisão proposta:** Alternativa A. Justificativa: o domínio real tem uma
fatura como unidade com invariantes próprias (fechamento, vencimento,
validação de total). Modelar isso como uma entidade de primeira classe é
consistente com o padrão já usado para `TransacaoBancaria` (entidade de
domínio própria, não uma variação de `Documento`).

> **D1 — DELIBERADO: APROVADA (Alternativa A).**

---

## 3.2 — Modelo contábil

```text
COMPRA (por item da fatura)
  D — Despesa/Ativo (conforme classificação do item)
  C — Conta do Cartão (Passivo)

PAGAMENTO (da fatura, valor total)
  D — Conta do Cartão (Passivo)
  C — Conta Bancária
```

**Por que o pagamento não é nova despesa:** a despesa já foi reconhecida no
momento da compra (regime de competência), contra o passivo "Cartão". O
pagamento é a liquidação desse passivo — uma transferência entre uma conta
de Passivo e uma conta de Ativo (banco), não um novo fato gerador de
despesa. Lançar `D Despesa / C Banco` no pagamento duplicaria a despesa.

**Tratamento de itens especiais:**

| Item | Tratamento aprovado | Observação |
|---|---|---|
| Juros | `D Despesas Financeiras — Juros / C Passivo — Cartão`, item separado da compra original | **D10 — APROVADO (Alternativa B).** Não incorporado à compra. |
| IOF | `D Despesas Financeiras — IOF / C Passivo — Cartão de Crédito`, item separado da compra original | **D9 — APROVADO (Alternativa 2).** IOF não incorporado ao valor da compra. |
| Multa | `D Despesas Financeiras — Multas / C Passivo — Cartão` | **D10 — APROVADO (Alternativa B).** |
| Encargos financeiros/tarifa | `D Despesas Financeiras — Encargos / C Passivo — Cartão` | **D10 — APROVADO (Alternativa B).** Segregável por natureza (juros, multa e encargos em contas de despesa financeira distintas, não uma única conta genérica). Sem criação de sub-passivo de rotativo nesta etapa. |
| Anuidade | Despesa administrativa (D Despesa / C Cartão) | Trata-se como item normal da fatura — não revisado nesta deliberação, mantido como já proposto |
| Estorno/crédito | Reduz o saldo do passivo (D Cartão / C Despesa, invertido) | Reaproveitar padrão de `core/rule_engine/estorno.py` — **D11, já aprovado anteriormente** |
| Compra parcelada | **D12 — APROVADO (Alternativa C).** Uma compra, valor total lançado no passivo no momento da aquisição; parcelamento é metadado informativo (`e_parcelado`/`parcela_atual`/`total_parcelas`), não gera lançamento mensal adicional nem distribui a despesa pelas parcelas. Alternativa B (reconhecimento por parcela) rejeitada formalmente. | Ver Seção 3.7 |
| Cancelamento de compra | Estorno do item específico, não da fatura inteira | — |
| Ajuste de fatura (ex.: erro do emissor) | Não há evidência suficiente nas fontes disponíveis sobre como o sistema deveria tratar ajustes pós-fechamento; requer decisão contábil explícita antes da implementação | Permanece fora de escopo explícito, conforme D11 |

> **D9 — IOF: APROVADO (Alternativa 2 — despesa financeira independente).**
> **D10 — Juros/multa/encargos: APROVADO (Alternativa B — despesas financeiras independentes, segregadas por natureza; sem sub-passivo de rotativo nesta etapa).**

---

## 3.3 — Conta do cartão

> **Correção pós-achado (Fase 0 de implementação, DT-CC-01 — ver Débito
> Técnico Registrado abaixo):** o texto original desta seção presumia
> `ContaContabil` como componente já persistido. Essa premissa foi
> refutada pelo código durante a Fase 0. O texto abaixo reflete a
> formulação corrigida, mantendo D6 aprovado sem reabrir a deliberação.

- `CartaoCredito` **mantém referência lógica 1:1 à conta contábil de
  Passivo por meio de `conta_codigo`**, reaproveitando o padrão textual já
  existente no modelo persistente (`SplitORM.conta_codigo`, uma string
  livre sem chave estrangeira). `ContaContabil` permanece uma entidade de
  domínio **sem persistência própria** nesta etapa — não é criada
  `ContaContabilORM` nem tabela `contas_contabeis`.
- Criação da referência: na primeira vez que um cartão é identificado,
  atribuir um `conta_codigo` (dentro do range de Passivo já em uso
  informalmente pelo domínio, não fixo).
- Reuso: identificação do cartão deve ser idempotente — mesmo cartão nunca
  gera duas referências de conta. Chave de identidade natural: ver B1
  (Deliberação Complementar — Gate de Implementação).
- `guid_gnucash`: persistido diretamente em `CartaoCreditoORM` (não em
  `ContaContabil`, que não tem tabela própria).
- **Não assumir código fixo de plano de contas** — nenhuma decisão de
  código numérico é tomada neste ADR.
- **Fora de escopo deste ADR:** criação de infraestrutura persistente de
  contas contábeis (`contas_contabeis`, `ContaContabilORM`, FK de conta).
  Isso é dívida técnica pré-existente e afeta o sistema inteiro, não
  apenas cartão — não deve ser resolvida como efeito colateral desta
  feature.

> **D6 — Conta de Passivo do cartão: DELIBERADO — APROVADA, formulação de
> implementação corrigida (referência lógica via `conta_codigo` textual,
> não relação 1:1 persistida com `ContaContabil`).**

---

## Débito técnico registrado — DT-CC-01

**Persistência de `ContaContabil` inexistente.** `ContaContabil`
(`core/domain/entities.py:282`) existe apenas como entidade de domínio;
não há `ContaContabilORM`, tabela `contas_contabeis`, nem integridade
referencial de contas contábeis em nenhuma parte do sistema —
`SplitORM.conta_codigo` (`core/infra/db/models.py:106`) já opera hoje como
string livre, sem FK, para qualquer tipo de lançamento, não apenas cartão.

A feature de cartão utiliza `conta_codigo` como referência textual,
seguindo esse mesmo padrão já existente. A criação de uma infraestrutura
persistente de contas contábeis fica **fora do escopo do ADR 010** e
deverá ser objeto de decisão arquitetural independente — mesma classe de
tratamento já dada ao débito técnico do FITID (D14): descoberto durante o
trabalho de cartão, mas não específico dele, e não resolvido como efeito
colateral.

---

## Débito técnico registrado — DT-CC-02

**Perda de `confidence` no round-trip de `CompraCartao`.** A migration da
Fase 0 (`3c164a335ab2_adr010_cartao_credito_schema.py`) criou
`compras_cartao` sem coluna para `confidence` — campo que existe na
entidade de domínio `CompraCartao` (`ConfidenceScore`, Fase 1/2) e que é
central para a regra de revisão humana (D9/D10 dependem dele para decidir
o que cai abaixo do limiar `ConfidenceScore.e_confiavel`). O gap foi
descoberto na Fase 4: `CartaoCreditoRepository`/`FaturaCartaoRepository`
persistem e recuperam `CompraCartao`, mas `_item_para_dominio` retorna
sempre `confidence=None` — o valor calculado na extração (Fase 2) não
sobrevive a um ciclo salvar→reler.

**Impacto:** qualquer fluxo que reler uma `CompraCartao` já persistida
(em vez de trabalhar com o objeto recém-extraído em memória, como os
testes de Fase 2/4 fazem) perde a informação de confiança — a extração
volta a parecer "certa" mesmo tendo sido classificada abaixo do limiar.
Isso é particularmente sensível dado que B3 (classificação de tipo de
item) já está registrado como não validado contra fatura real, com a
confiança sub-threshold como única salvaguarda contra lançamento
automático incorreto — perder essa informação no reload esvazia essa
salvaguarda para qualquer consumidor que dependa da persistência.

**Correção:** exige nova coluna em `compras_cartao` (`confidence` ou
campo equivalente) — portanto **nova migration**, fora do escopo já
concluído da Fase 0/4. Fica registrada como pré-requisito a resolver
antes de qualquer fluxo de produção que dependa de reler `CompraCartao`
do banco para decidir revisão humana (ainda não é o caso — Fases 2/4
operam com o objeto em memória, recém-extraído, onde `confidence` está
presente). Mesma classe de tratamento de DT-CC-01/D14: descoberto durante
o trabalho de cartão, registrado, não resolvido como efeito colateral de
outra fase.

---

## 3.4 — Fatura (ciclo proposto)

```text
PDF
 ↓
Documento (tipo = FATURA_CARTAO_PDF)
 ↓
FaturaCartao (agregado — período, vencimento, cartão, total declarado)
 ↓
CompraCartao (N itens — estabelecimento, valor, data, parcela)
 ↓
Classificação (por item, via ClassificationPort existente)
 ↓
Lancamento (compra) — um por item, D Despesa / C Cartão
 ↓
Conta do Cartão (Passivo) — acumula saldo
 ↓
Pagamento (identificado via extrato OFX)
 ↓
Lancamento (pagamento) — D Cartão / C Banco
 ↓
Conciliação (MotorConciliacao — pagamento × extrato, não compras × extrato)
```

**Definições:**

- **Documento** — o PDF bruto recebido, como hoje para qualquer tipo.
- **Fatura** — agregado que representa um ciclo de faturamento de um
  cartão (`FaturaCartao`).
- **Item** — cada linha extraída da fatura, antes de virar lançamento.
- **Compra** — item classificado como despesa/ativo (`CompraCartao`).
- **Parcela** — metadado de uma compra que se estende por múltiplos meses
  (não gera split contábil próprio — ver 3.7).
- **Lançamento** — registro contábil gerado a partir de uma compra ou do
  pagamento.
- **Pagamento** — liquidação do passivo, identificado via conciliação
  bancária, não via leitura da fatura.

> **D2 — `CartaoCredito`: DELIBERADO — APROVADA (entidade própria).**
> **D3 — `FaturaCartao`: DELIBERADO — APROVADA.**
> **D4 — `CompraCartao`: DELIBERADO — APROVADA.**
> **D5 — Relação fatura→itens: DELIBERADO — APROVADA (Alternativa A, com fallback de revisão humana em caso de divergência de fechamento).**

---

## 3.5 — PDF/OCR

```text
PDF texto → pdfplumber (extração direta) → parser de fatura
PDF imagem → OCRPlugin (extensão de campos) → parser de fatura
```

**Detector:** `core/parsers/detector.py` precisa reconhecer
`FATURA_CARTAO_PDF` como subtipo de `PDF_TEXTO`/`PDF_IMAGEM` — não um tipo
paralelo desconectado. Proposta: manter `TipoDocumento.PDF_TEXTO` e
`PDF_IMAGEM` como estão (não quebrar o contrato existente, usado por NF-e
em PDF e outros fluxos futuros); adicionar uma etapa de **identificação de
emissor de fatura** após a detecção de tipo, antes do roteamento ao parser
— análogo ao que `nubank.py` já faz para CSV, mas agora operando sobre o
resultado da extração de texto/OCR. Isso evita introduzir um segundo
mecanismo de seleção de parser concorrente com `ParserFactory`.

---

## Débito técnico pré-existente — mecanismo FITID desconectado do modelo atual

Classificação formal: **débito técnico pré-existente**, não introduzido por
esta proposta e não específico a cartão de crédito.

**Fato comprovado:** `MotorConciliacao._fitid_do_lancamento`
(`core/rule_engine/motor_conciliacao.py`) verifica
`hasattr(lanc, "numero_documento_origem")` sobre a dataclass `Lancamento`
(`core/domain/entities.py:437-477`), que **não declara esse campo**. O
único campo relacionado é `Documento.numero_documento` (linha 384), nunca
copiado para `Lancamento` em `core/rule_engine/lancamento_service.py` (zero
ocorrências do nome do campo nesse arquivo). `hasattr` retorna sempre
`False`; a Camada 1 (FITID) do motor é inalcançável no fluxo atual. Nenhum
teste em `tests/unit/core/conciliacao/test_motor_conciliacao.py` exercita
esse caminho — a fixture `_lanc()` nunca define o campo, porque o campo não
existe na classe.

Este débito **não é causado pela proposta de cartão** e já afeta hoje
qualquer conciliação (OFX genérico, não só cartão) que dependeria de match
exato por FITID em vez de valor+data.

### Alternativas de tratamento

**Alternativa A — Corrigir antes da implementação de cartão**
Adicionar o campo faltante (ou o mecanismo equivalente de propagação do
FITID de `Documento` para `Lancamento`) e o teste correspondente, como
item independente, antes de iniciar qualquer código da feature de cartão.

**Alternativa B — Corrigir como etapa obrigatória anterior à integração OFX/pagamento do cartão**
Prosseguir com as etapas de domínio, contabilidade e PDF/OCR da feature de
cartão (que não dependem de FITID), e tratar a correção do FITID como
pré-requisito formal apenas da etapa de conciliação do pagamento — a
última do plano de implementação (Seção "Plano de implementação
posterior", itens 6–8).

| Alternativa | Vantagens | Desvantagens | Impacto | Recomendação |
|---|---|---|---|---|
| **A — corrigir antes de tudo** | Elimina o débito da base antes de qualquer nova dependência sobre ele; evita que a feature de cartão seja construída sobre um caminho que parece funcionar (Camada 2 cobre o caso) mas mascara o defeito da Camada 1 | Bloqueia o início da feature de cartão por um problema que não é dela; mistura escopo de correção de bug geral com escopo de feature nova, indo contra a separação de commits/PRs pequenos e de finalidade única | Atraso no início da feature; correção isolada é pequena (um campo + propagação + teste) | Aceitável, mas não obrigatória |
| **B — corrigir só antes da etapa de conciliação do pagamento** | Permite progresso imediato nas etapas de domínio/contabilidade/PDF-OCR, que são a maior parte do esforço e não dependem de FITID; a Camada 2 (valor+data) do motor já é suficiente para o pagamento agregado, então a feature de cartão nem precisa do FITID para funcionar | Se a correção for adiada indefinidamente, o pagamento do cartão fica permanentemente dependente de valor+data, sem o match exato que o FITID daria | Menor atraso; risco de a correção nunca ser priorizada se não houver critério de bloqueio formal na etapa de conciliação | **Recomendada**, com uma condição: a etapa de conciliação do pagamento do cartão (Seção "Plano de implementação posterior", item 8) não pode ser dada como concluída sem que o FITID esteja corrigido e testado — não é opcional, é pré-requisito de saída dessa etapa específica |

**Recomendação:** Alternativa B, com a condição explícita acima. A
correção do FITID é necessária, mas não precisa bloquear o início da
feature de cartão como um todo — apenas a sua etapa final de conciliação
de pagamento, que é justamente onde o FITID seria usado.

> **D14 — FITID: DELIBERADO — APROVADA (Alternativa B) — CORRIGIDO na Fase 5.**
> Mecanismo técnico escolhido na Etapa 5.0 (Gate B4): **B4-B** — `MotorConciliacao.conciliar()` recebe um mapa opcional `fitids_por_lancamento` (lancamento_id → FITID), resolvido pelo chamador (`core/cli.py::conciliacao_executar`) via `Lancamento.documento_id → Documento.numero_documento`. Sem alteração em `Lancamento`, sem migration, motor permanece sem I/O. Commit e testes próprios, independentes da feature de cartão (`tests/unit/core/conciliacao/test_fitid_fase5.py`), conforme exigido.
>
> **Achado da Etapa 5.0, registrado formalmente:** corrigir D14 **não** habilita FITID (Camada 1) para os lançamentos de pagamento de fatura de cartão (D8). Esses lançamentos nascem de `FaturaCartao`, não de um `Documento` OFX — nunca têm `documento_id` preenchido, portanto nunca entram no mapa `fitids_por_lancamento` e nunca ativam a Camada 1. Para o pagamento de cartão, **D15 permanece a decisão vigente e inalterada**: conciliação via Camada 2 (valor + data). Confirmado por teste negativo dedicado.

---

## 3.6 — Idempotência

| Nível | Chave proposta | Por que hash de arquivo não basta |
|---|---|---|
| Documento (PDF da fatura) | Hash do conteúdo do arquivo (já existe, `DetectorDocumento.calcular_hash`) | Suficiente apenas para "mesmo arquivo enviado duas vezes" — não cobre o caso de reprocessamento após correção manual de um item |
| Fatura | `(cartão, período de referência)` | Duas faturas do mesmo cartão no mesmo mês nunca deveriam coexistir; hash de arquivo não captura isso se o PDF for reemitido com pequena diferença |
| Item/Compra | `(fatura_id, posição ou hash da linha)` | Hash de arquivo inteiro não permite identificar duplicidade de um item específico se a fatura for reprocessada parcialmente |
| Lançamento (compra) | `(compra_id)` — 1:1 | Evita gerar dois lançamentos para a mesma compra em reprocessamento |
| Pagamento (OFX) | `(conta_bancaria, FITID)` do lado `TransacaoBancaria` — **já implementado** e correto (`salvar_se_nova`). Do lado `Lancamento`/`MotorConciliacao`, o match exato por FITID depende da correção do débito técnico descrito acima; até lá, o pagamento é identificado por valor+data (Camada 2), suficiente para o modelo de lançamento único proposto | O nível de importação da transação bancária já está correto; o nível de conciliação do lançamento de pagamento contra essa transação é que depende da correção pendente |

**Nota:** o hash de arquivo inteiro, usado hoje em
`ProcessarDocumentoUseCase`, não é suficiente para nenhum nível abaixo do
Documento — é a mesma lacuna já registrada no parecer anterior, agora
detalhada por nível.

> **D13 — Idempotência: DELIBERADO — APROVADA (chaves por nível, conforme tabela acima).**

---

## 3.7 — Parcelamento

Os campos já existentes em `Lancamento` (`e_parcelado`, `parcela_atual`,
`total_parcelas`, `lancamento_pai_id`) são **aprovados como suficientes,
sem novo modelo paralelo**: uma compra parcelada gera **um único
lançamento no valor total**, com `e_parcelado=True`, `total_parcelas=N`.
Os campos servem exclusivamente como **metadado informativo e de controle
do cronograma de liquidação** — não geram lançamentos mensais adicionais
nem distribuem a despesa pelas parcelas. O `lancamento_pai_id` não é
necessário para o lançamento inicial.

> **D12 — Competência de parcelas: APROVADO (Alternativa C).** Reconhecimento
> integral no momento da aquisição. A Alternativa B (reconhecimento por
> parcela, com lançamento mensal distribuído) está **formalmente
> rejeitada**.

---

## 3.8 — Auditoria

Comparado ao catálogo existente (`core/events/catalog.py` — lista fechada,
sem nenhum evento de cartão/fatura), propõe-se o mínimo necessário:

- `FaturaCartaoRecebida`
- `FaturaCartaoClassificada` (reaproveita conceito de `ClassificacaoConcluida`, se aplicável ao granularidade de item — a confirmar)
- `PagamentoCartaoIdentificado`

Não propor eventos além destes sem necessidade concreta demonstrada,
conforme o princípio de economia do próprio catálogo existente.

---

## 3.9 — GnuCash

A conta de Passivo do cartão é exportada como qualquer outra `ContaContabil`
via `core/adapters/csv_exporter.py`, sem alteração no exportador — desde
que `guid_gnucash` seja preenchido na criação da conta (Seção 3.3). Nenhuma
mudança no exportador é necessária nesta proposta; validação de que o
mapeamento realmente resulta em uma conta de Passivo (e não confundida com
conta bancária) fica como item de teste, não de novo código no exportador.

---

## Decisões que este ADR deixa explícitas

1. **Modelo de domínio:** Alternativa A (`FaturaCartao` → `CompraCartao` como agregado novo). **DELIBERADO — APROVADA (D1).**
2. **Tipo de documento:** `FATURA_CARTAO_PDF` como subtipo identificado após `PDF_TEXTO`/`PDF_IMAGEM`, não tipo paralelo. Consequência técnica de D1 — sem item de pauta próprio.
3. **Parser:** novo parser registrado em `ParserFactory`, reaproveitando `pdfplumber`. Consequência técnica de D1 — sem item de pauta próprio.
4. **OCR:** extensão de `OCRPlugin` para campos de fatura; conexão ao pipeline real (hoje inexistente). Consequência técnica de D1 — sem item de pauta próprio.
5. **Conta do cartão:** `ContaContabil` existente, natureza Passivo, criação idempotente por cartão. **DELIBERADO — APROVADA (D6).**
6. **Modelo de fatura:** agregado com período, vencimento, cartão, total declarado. **DELIBERADO — APROVADA (D3).**
7. **Modelo de item:** `CompraCartao` com estabelecimento, valor, data, parcela, tipo (compra/juros/IOF/anuidade/estorno). **DELIBERADO — APROVADA (D4)**, com classificação de IOF (D9) e juros/multa/encargos (D10) agora também aprovada.
8. **Partidas dobradas:** compra = D Despesa/C Cartão; pagamento = D Cartão/C Banco, dois lançamentos distintos. **DELIBERADO — APROVADA (D7, D8).**
9. **Parcelamento:** reaproveitar campos existentes em `Lancamento`, exclusivamente como metadado informativo — sem lançamento por parcela. **DELIBERADO — APROVADA (D12, Alternativa C).**
10. **Idempotência:** chaves por nível (Seção 3.6), com correção do gap de dedup por transação/item no documento. **DELIBERADO — APROVADA (D13).**
11. **Auditoria:** três eventos novos mínimos (Seção 3.8). **DELIBERADO — APROVADA, sujeito a revisão semântica dos nomes (D16).**
12. **Conciliação:** conciliar o **pagamento** (1 lançamento agregado) contra o extrato, não as compras individuais. O conciliador atual já é `TransacaoBancaria ↔ Lancamento` (1:1) — compatível com esse modelo sem alteração. **Não introduzir, nesta proposta, nenhum mecanismo de conciliação N:1** (múltiplas compras contra uma transação bancária); se essa necessidade surgir no futuro, é uma decisão arquitetural separada, fora do escopo deste ADR. **Não depender do caminho FITID atual, que está quebrado** (ver "Débito técnico pré-existente") — usar Camada 2 (valor+data), com a correção do FITID como pré-requisito apenas da etapa final de conciliação (Alternativa B recomendada). **DELIBERADO — APROVADA (D15).**
13. **GnuCash:** sem alteração no exportador; validar mapeamento via teste. **DELIBERADO — APROVADA (D18).**
14. **Migrations:** nova migration para `CartaoCredito`, `FaturaCartao`, `CompraCartao` — sem tocar a migration existente. Consequência técnica de D1/D3/D4 — sem item de pauta próprio; segue a mesma condição de D1.
15. **CLI:** comandos novos (`fatura-importar`, `cartao-listar` ou equivalentes) seguindo o padrão de `conciliacao_importar`/`conciliacao_executar` já existente. **DELIBERADO — APROVADA a convenção (D17)**; nomes definitivos permanecem a fechar em revisão de código.
16. **Estratégia de testes:** conforme lista do parecer técnico anterior (detecção, extração, contabilidade, conta, idempotência, conciliação, auditoria, regressão completa). Não é item de pauta próprio — decorre das decisões acima.

---

## Impacto no Gate 0

A funcionalidade de cartão de crédito constitui escopo novo em relação aos
artefatos atualmente verificados e não deve alterar os bloqueadores ou
critérios da homologação corrente. Sua eventual incorporação ao produto
deverá ocorrer mediante decisão formal própria.

Isso não significa impacto zero: a implementação consome tempo de equipe
que poderia ir para a resolução dos itens `DECISÃO`/`BLOQUEADOR` já
registrados na Matriz de Prontidão, e uma migration nova, mesmo isolada em
branch, precisa ser avaliada quanto a não interferir na migration única
existente quando (e se) os branches forem eventualmente unificados. Esse
impacto de cronograma e sequenciamento é real e deve ser considerado na
decisão de priorização — não apenas o impacto técnico direto no schema
atual.

---

## Requisito externo/CRC (D19)

**D19 — APROVADO como registro de suporte, não como exigência geral.**
Houve parecer contábil específico para D9 (IOF), D10 (juros/multa/encargos)
e D12 (competência de parcelas) — registrado formalmente como suporte a
essas três decisões.

**Não há evidência, nos artefatos de governança disponíveis (ADRs
001–008, Matriz de Prontidão, Pauta do Gate 0), de exigência formal geral
de validação do Contador CRC para todo o ADR.** ADR 007 menciona aprovação
do Contador CRC apenas para a transição de versão `0.x.x → 1.0.0` e para o
processo de homologação `0.999` — não para ADRs individuais de modelagem
contábil durante a fase `0.x.x`. Essa constatação permanece válida e
**não é transformada em requisito geral por esta consolidação** —
conforme instrução explícita da Direção.

O registro de validação contábil aplica-se exclusivamente a D9, D10 e D12.
Nenhuma outra decisão deste ADR (D1–D8, D11, D13–D18) está condicionada a
parecer externo.

---

## Impacto em migrations

Nova migration para `CartaoCredito`, `FaturaCartao`, `CompraCartao` e, se
necessário, tabela de itens. Não há histórico incremental de migrations
para servir de precedente (schema atual é uma única migration,
`f43b99e177a7_schema_inicial`) — a nova migration seria a primeira
migration incremental real do projeto, o que em si é um evento arquitetural
que deve ser tratado com cuidado adicional (testar sequência
upgrade→downgrade→upgrade conforme já exigido pelas regras do projeto).

## Impacto em testes

Ver lista completa no Parecer Técnico da Fase A/B (item 18). Adiciona-se
aqui: teste de regressão específico para confirmar que o bug do FITID
(Seção "Análise Complementar") não é mascarado ou "corrigido
acidentalmente" pela implementação de cartão sem ser tratado como correção
própria, documentada e testada isoladamente.

---

## Matriz final consolidada de decisões

Deliberação concluída — **18 de 18 decisões arquiteturais/contábeis
aprovadas**. D19 registrado como validação de suporte, não como decisão
de escopo arquitetural própria (por isso não contabilizada como 19ª
decisão de conteúdo, mas como registro de proveniência das decisões
contábeis).

| Decisão | Conteúdo | Status |
|---|---|---|
| D1 | Modelo de domínio — Alternativa A (`FaturaCartao` → `CompraCartao`) | **APROVADA** |
| D2 | Entidade `CartaoCredito` | **APROVADA** |
| D3 | Entidade `FaturaCartao` | **APROVADA** |
| D4 | Entidade `CompraCartao` | **APROVADA** |
| D5 | Relação fatura→itens, validação de fechamento com fallback de revisão humana | **APROVADA** |
| D6 | Conta de Passivo do cartão — reaproveitar `ContaContabil` | **APROVADA** |
| D7 | Lançamento de compra — `D Despesa/Ativo · C Passivo Cartão` | **APROVADA** |
| D8 | Lançamento de pagamento — agregado, `D Passivo Cartão · C Banco` | **APROVADA** |
| D9 | IOF — despesa financeira independente (Alternativa 2) | **APROVADA** |
| D10 | Juros/multa/encargos — despesas financeiras independentes, segregadas por natureza (Alternativa B); sem sub-passivo de rotativo | **APROVADA** |
| D11 | Créditos/estornos reaproveitam `estorno.py`; ajustes pós-fechamento fora de escopo | **APROVADA** |
| D12 | Competência de parcelas — reconhecimento integral na aquisição, parcelamento como metadado (Alternativa C); Alternativa B rejeitada | **APROVADA** |
| D13 | Idempotência — chaves por nível | **APROVADA** |
| D14 | FITID — débito técnico pré-existente, corrigido via B4-B (Fase 5); pagamento de cartão permanece na Camada 2, não afetado | **APROVADA — CORRIGIDA** |
| D15 | Conciliação — 1:1 pagamento↔transação, sem mecanismo N:1 | **APROVADA** |
| D16 | Existência de no mínimo três eventos específicos para recebimento/classificação da fatura e identificação do pagamento | **APROVADA** (identificadores/nomenclatura final e payloads ainda não definidos) |
| D17 | Convenção de CLI, nomes definitivos a fechar em revisão de código | **APROVADA** |
| D18 | GnuCash — sem alteração no exportador | **APROVADA** |
| D19 | Validação contábil registrada como suporte a D9/D10/D12 — não é exigência geral do ADR | **REGISTRADO** |

Nenhuma decisão permanece pendente de aprovação arquitetural ou contábil.
Detalhes de implementação não cobertos por nenhuma decisão acima ficam
para a etapa de código, sob autorização futura — ver "Baseline de
Implementação" abaixo para a distinção explícita entre decisão fechada e
detalhe ainda em aberto.

## Plano de implementação posterior (não executado nesta etapa)

1. ~~Aprovação deste ADR~~ — **concluída nesta consolidação.**
2. ~~Resolução das decisões pendentes~~ — **concluída nesta consolidação (D9, D10, D12, D19).**
3. Migration para `CartaoCredito` / `FaturaCartao` / `CompraCartao`.
4. Implementação do parser de fatura PDF + extensão do `OCRPlugin`.
5. Registro em `ParserFactory` + identificação de emissor.
6. Extensão do `LancamentoService` para os dois lançamentos (compra/pagamento).
7. Integração dos metadados de parcelamento (`e_parcelado`, `parcela_atual`, `total_parcelas`) no lançamento da compra, sem geração de lançamentos contábeis mensais adicionais (D12).
8. ~~Correção do bug de FITID~~ — **concluída na Fase 5** (B4-B, D14).
9. Novos eventos de auditoria.
10. CLI.
11. Suíte de testes completa + regressão total do projeto.
12. Conciliação do pagamento (depende do item 8 para uso de match exato por FITID).
13. Validação de exportação GnuCash.
14. Pull Request para revisão — sem merge automático em `main`.

**Nenhum destes itens está autorizado a começar nesta etapa** — autorização de implementação é decisão separada e futura, conforme regra de parada desta consolidação.

---

## Consequências

**Positivas:**
- Reaproveita `pdfplumber`, `OCRPlugin`, `ClassificationPort`,
  `ContaContabil` (incluindo `guid_gnucash`), `TransacaoBancaria`/FITID
  (idempotência do lado bancário), `core/audit/chain.py`,
  `core/rule_engine/motor_conciliacao.py` e padrão de estorno existente —
  nenhum desses precisa ser recriado.
- Corrige, como efeito colateral necessário (não incidental), a
  identificação de um bug real e não relacionado a cartão (FITID quebrado),
  que teria permanecido despercebido sem esta investigação.
- Mantém `Documento` com sua semântica atual (1:1 transação), evitando
  quebrar contratos usados por NF-e, OFX e CSV bancário.

**Negativas:**
- Introduz a primeira migration incremental real do projeto — evento que
  merece atenção própria, independente do cartão.
- O modelo aprovado (D12) reconhece integralmente a despesa ou ativo no
  momento da aquisição, em conformidade com o regime de competência. O
  parcelamento representa exclusivamente a forma de liquidação do passivo e
  permanece registrado como metadado informativo, sem distribuição mensal
  da despesa.
- Consome tempo de equipe em paralelo aos itens `DECISÃO`/`BLOQUEADOR` já
  registrados no Gate 0, mesmo estando isolado em branch.

---

# BASELINE DE IMPLEMENTAÇÃO

Consolidação normativa das decisões aprovadas neste ADR, para uso direto
na etapa de implementação quando autorizada. Cada item distingue
explicitamente **DECISÃO APROVADA** de **DETALHE DE IMPLEMENTAÇÃO AINDA
NÃO DEFINIDO** — o segundo não é inventado aqui, apenas sinalizado como
aberto.

### 1. Modelo de domínio
**DECISÃO APROVADA:** Alternativa A — `Documento → FaturaCartao →
CompraCartao` como agregado novo (D1).
**AINDA NÃO DEFINIDO:** estrutura exata de campos de cada entidade além do
mínimo já citado neste ADR (período, vencimento, cartão, total declarado
para `FaturaCartao`; estabelecimento, valor, data, parcela, tipo para
`CompraCartao`).

### 2. Entidades
**DECISÃO APROVADA:** `CartaoCredito` (D2), `FaturaCartao` (D3),
`CompraCartao` (D4) como entidades de domínio novas.
**AINDA NÃO DEFINIDO:** nomes de campos, tipos exatos, validações de
formato (ex.: máscara do final do cartão).

### 3. Relacionamento Fatura → Itens
**DECISÃO APROVADA:** `FaturaCartao` contém N `CompraCartao` e demais
componentes financeiros identificáveis (encargos, créditos, estornos); a
invariante de fechamento verifica que a composição de itens + encargos −
créditos/estornos corresponde ao total declarado da fatura; divergência
gera item para revisão humana, não erro fatal (D5).
**AINDA NÃO DEFINIDO:** tolerância numérica aceitável para a validação de
fechamento (ex.: diferença de centavos por arredondamento).

### 4. Conta permanente de Passivo por cartão
**DECISÃO APROVADA:** `CartaoCreditoORM.conta_codigo` como referência
textual (String, sem FK), seguindo o padrão já existente em
`SplitORM.conta_codigo`; `guid_gnucash` persistido diretamente em
`CartaoCreditoORM`; criação idempotente na primeira identificação do
cartão; sem código de plano de contas fixo (D6, corrigido por DT-CC-01).
Não criar `contas_contabeis`, `ContaContabilORM`, FK de conta, repository
de `ContaContabil`, nem alterar `SplitORM` ou o modelo contábil global —
fora de escopo deste ADR.
**AINDA NÃO DEFINIDO:** nenhum — chave de identidade do cartão fechada em
B1 (Deliberação Complementar — Gate de Implementação): `(emissor, final
mascarado, titular)`.

### 5. Lançamento de compra
**DECISÃO APROVADA:** `D Despesa/Ativo (conforme classificação do item) /
C Passivo — Cartão de Crédito`, um lançamento por item (D7).
**AINDA NÃO DEFINIDO:** nenhum — decisão completa para implementação
direta.

### 6. Lançamento de pagamento
**DECISÃO APROVADA:** `D Passivo — Cartão de Crédito / C Ativo — Banco`,
**um único lançamento agregado** por fatura paga, nunca N lançamentos por
compra (D8).
**AINDA NÃO DEFINIDO:** nenhum — decisão completa para implementação
direta.

### 7. IOF
**DECISÃO APROVADA:** `D Despesas Financeiras — IOF / C Passivo — Cartão
de Crédito`, item separado da compra original, não incorporado ao valor de
aquisição (D9).
**AINDA NÃO DEFINIDO:** nome/código exato da conta de despesa financeira
no plano de contas.

### 8. Juros/multa/encargos
**DECISÃO APROVADA:** despesas financeiras independentes, segregadas por
natureza — `D Despesas Financeiras — Juros`, `— Multas`, `— Encargos`,
todos `/ C Passivo — Cartão`; sem sub-passivo de rotativo nesta etapa
(D10).
**AINDA NÃO DEFINIDO:** nomes/códigos exatos das contas de despesa
financeira; regra de identificação de qual linha da fatura corresponde a
cada categoria (juros vs. multa vs. encargo) na extração do parser/OCR.

### 9. Parcelamento
**DECISÃO APROVADA:** reconhecimento integral no momento da aquisição;
campos `e_parcelado`/`parcela_atual`/`total_parcelas` usados exclusivamente
como metadado informativo e de controle de cronograma; nenhum lançamento
mensal adicional; Alternativa B (lançamento por parcela) formalmente
rejeitada (D12).
**AINDA NÃO DEFINIDO:** nenhum — decisão completa para implementação
direta.

### 10. Idempotência
**DECISÃO APROVADA:** chaves por nível — hash de arquivo (Documento);
`(cartão, período)` (Fatura); `(fatura_id, posição/hash da linha)` (Item);
`(compra_id)` 1:1 (Lançamento de compra); `(conta_bancaria, FITID)` já
implementado (Transação Bancária) (D13).
**AINDA NÃO DEFINIDO:** implementação técnica do dedup por nível dentro de
`ProcessarDocumentoUseCase` (hoje restrito a hash de arquivo inteiro).

### 11. FITID
**DECISÃO APROVADA E IMPLEMENTADA (Fase 5):** débito técnico pré-existente
corrigido via B4-B — `MotorConciliacao.conciliar()` recebe
`fitids_por_lancamento` resolvido pelo chamador via `documento_id →
Documento.numero_documento`; sem alteração em `Lancamento`; sem
migration (D14).
**AINDA NÃO DEFINIDO:** nenhum — mecanismo fechado e testado
(`tests/unit/core/conciliacao/test_fitid_fase5.py`). Nota: esta correção
não estende Camada 1 ao pagamento de cartão (D8), que permanece na
Camada 2 por não ter `documento_id` — ver "Débito técnico registrado"
para o achado completo.

### 12. Conciliação
**DECISÃO APROVADA:** `1 Transação Bancária ↔ 1 Lançamento de Pagamento ↔
1 Fatura`; nenhum mecanismo de conciliação N:1 introduzido; reaproveitar
`MotorConciliacao` sem alteração estrutural; usar Camada 2 (valor+data) até
a correção do FITID (D15).
**AINDA NÃO DEFINIDO:** nenhum — decisão completa para implementação
direta.

### 13. Auditoria
**DECISÃO APROVADA:** existência de no mínimo três eventos específicos —
um para recebimento da fatura, um para sua classificação, um para
identificação do pagamento (esboço atual: `FaturaCartaoRecebida`,
`FaturaCartaoClassificada`, `PagamentoCartaoIdentificado`) (D16).
**AINDA NÃO DEFINIDO:** identificadores/nomenclatura final dos eventos e
payloads — o número e a finalidade dos eventos estão fechados; os nomes
exatos, não.

### 14. CLI
**DECISÃO APROVADA:** seguir a convenção de nomenclatura já existente
(`processar`, `revisar`, `conciliacao_importar`/`conciliacao_executar`)
(D17).
**AINDA NÃO DEFINIDO:** nomes exatos dos comandos novos.

### 15. GnuCash
**DECISÃO APROVADA:** nenhuma alteração em `core/adapters/csv_exporter.py`;
a conta de Passivo do cartão é exportada como qualquer `ContaContabil`,
desde que `guid_gnucash` esteja preenchido (D18).
**AINDA NÃO DEFINIDO:** teste específico que confirme que o mapeamento
resulta em conta de Passivo, não bancária.

### 16. PDF texto
**DECISÃO APROVADA:** extração direta via `pdfplumber` (já dependência do
projeto), reaproveitada sem substituição.
**AINDA NÃO DEFINIDO:** lógica de identificação do emissor da fatura a
partir do texto extraído; estrutura exata do parser de fatura.

### 17. PDF imagem/OCR
**DECISÃO APROVADA:** extensão de `OCRPlugin`/`SpikeOCR` para campos de
fatura, conectada ao pipeline real (hoje desconectado).
**AINDA NÃO DEFINIDO:** quais campos exatos o OCR precisa extrair além dos
já genéricos (`cnpj_emitente`, `valor_total`); threshold de confiança
específico para este fluxo antes de acionar revisão humana.

### 18. Testes obrigatórios
**DECISÃO APROVADA:** suíte completa cobrindo detecção, extração,
contabilidade (compra/IOF/juros/multa/encargo/estorno/equilíbrio D=C),
conta (criação/reuso idempotente), idempotência (reprocessamento,
restart), conciliação (correto/divergente/ambíguo/sem documento/sem
pagamento), auditoria (rastreabilidade PDF→lançamento), e regressão
completa da suíte existente — sem exceção.
**AINDA NÃO DEFINIDO:** casos de teste específicos (nomes de arquivo,
fixtures) — a definir na etapa de implementação.

### 19. Restrição de não introduzir conciliação N:1
**DECISÃO APROVADA — restrição permanente desta versão do ADR, não sujeita
a reinterpretação silenciosa:** não implementar, nesta feature, nenhum
mecanismo que concilie múltiplas `CompraCartao` diretamente contra uma
`TransacaoBancaria`. Toda conciliação do lado do cartão passa
exclusivamente pelo lançamento de pagamento agregado (item 6/12 acima). Se
essa necessidade surgir no futuro, é decisão arquitetural nova e separada,
fora do escopo deste ADR.

**Invariante de arquitetura (não apenas decisão negativa):** o vínculo
entre as compras da fatura e o lançamento de pagamento é indireto:

```text
CompraCartao → FaturaCartao → LancamentoPagamento → TransacaoBancaria
```

Uma `CompraCartao` **nunca** é candidata direta à conciliação bancária —
apenas o `LancamentoPagamento` agregado é.

**Critério de aceite adicional para a correção do FITID (item 11):** a
correção deve possuir teste dedicado que demonstre o caminho `FITID →
Lancamento → MotorConciliacao`, independente dos testes da feature de
cartão — evita que a suíte de cartão passar seja lida como "FITID está
corrigido".

---

## Ambiguidades remanescentes (não resolvidas por esta consolidação)

- Chave exata de identidade do `CartaoCredito` para idempotência de conta (item 4).
- Tolerância numérica de fechamento de fatura (item 3).
- ~~Mecanismo técnico exato de propagação do FITID~~ — **resolvido na Fase 5** (B4-B).
- Regra de identificação de linha de juros/multa/encargo na extração (item 8).
- Nomenclatura definitiva de eventos (item 13) e comandos CLI (item 14).
- Campos exatos e threshold de confiança do OCR para fatura (item 17).

Nenhuma dessas ambiguidades bloqueia a aprovação do ADR — são detalhes de
implementação a resolver durante a Fase de código, quando autorizada, não
decisões de arquitetura ou de modelo contábil.

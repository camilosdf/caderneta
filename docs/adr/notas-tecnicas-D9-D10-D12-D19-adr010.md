# Notas Técnicas de Fechamento — D9, D10, D12, D19
### ADR 010 / Cartão de Crédito · Branch `feature/cartao-credito`

Nenhum código, migration, teste ou pipeline alterado. Conteúdo decisório do
ADR 010 não foi tocado nesta etapa — estas notas são insumo para a
deliberação final, não uma revisão do ADR.

**Achado de governança prévio, relevante a todas as notas abaixo:** o
número `ADR 009` já está reservado em
`docs/caderneta_matriz_prontidao_v0999.docx` para o registro de "Open
Finance" como escopo pós-`v1.0.0` — ver nota no início desta entrega. As
notas abaixo tratam do conteúdo já produzido sob esse número; a resolução
da colisão é decisão separada da Direção.

---

## D9 — IOF

| | Alternativa 1 — Incorporado ao valor da compra | Alternativa 2 — Despesa financeira independente | Alternativa 3 — Absorvido no saldo sem discriminação |
|---|---|---|---|
| **Lançamento contábil** | `D Despesa/Ativo (valor compra + IOF) / C Cartão` | `D Despesa Financeira — IOF / C Cartão`, separado do lançamento da compra | Nenhum lançamento próprio — diferença apenas no saldo total repassado |
| **Momento do reconhecimento** | No lançamento da compra | No fechamento da fatura, junto aos demais encargos | Não aplicável |
| **Conta de destino** | Mesma conta de despesa da compra | Conta de despesa financeira específica (ex.: "Despesas Financeiras — IOF") — nova conta paramétrica, mesmo padrão de D6 | Nenhuma conta própria |
| **Impacto no valor da compra** | Aumenta o valor do item | Nenhum — compra permanece no valor original de aquisição | Nenhum lançamento visível |
| **Impacto no saldo da fatura** | Já incluído no item, sem diferença no total | Soma normalmente ao passivo total, como item próprio | Soma ao passivo total sem rastro do componente IOF |
| **Impacto em parcelas** | Se a compra for parcelada, o IOF entraria na base parcelada — **diverge da prática usual de mercado**, em que IOF sobre operação com cartão (ex. compra internacional) costuma ser cobrado integralmente na fatura corrente, não parcelado | Lançado integral na fatura em que ocorre, independentemente do parcelamento da compra de origem — compatível com a prática usual | Idem alternativa 1, sem rastreabilidade |
| **Impacto no GnuCash** | Nenhuma conta nova | Requer conta de despesa financeira "IOF" cadastrada — dentro do padrão paramétrico já existente (`ContaContabil.tipo` livre) | Nenhuma conta nova, mas perde informação na exportação |
| **Vantagens** | Simplicidade; não exige nova classificação | Rastreabilidade fiscal clara; alinhado ao "tipo de item" já aprovado em D4 (`CompraCartao` já prevê tipo IOF); permite relatório de IOF pago, útil para eventual dedução/apuração fiscal | Nenhuma vantagem identificada além da simplicidade extrema |
| **Riscos** | Perda de rastreabilidade fiscal; dificulta conferência de quanto foi pago de IOF no período; distorce a base de custo do item comprado | Depende de o parser/OCR identificar corretamente a linha de IOF na fatura — extração nem sempre discrimina esse valor claramente; risco mitigável pelo princípio já adotado no projeto (confiança insuficiente → revisão humana, não pela criação de mecanismo novo) | Perda total de rastreabilidade; incompatível com o princípio de auditabilidade do projeto (Seção 17/CLAUDE.md) |
| **Recomendação técnica** | Não recomendada isoladamente | **Recomendada** | Não recomendada |

**Nota:** a Alternativa 2 é a única compatível, sem ajuste adicional, com o
modelo de item já aprovado em D4 (`CompraCartao` com campo de tipo,
incluindo IOF). As Alternativas 1 e 3 exigiriam revisitar D4, já
deliberado como aprovado.

Decisão não tomada nesta nota — apresentada para deliberação da Direção.

---

## D10 — Juros/multa/encargos

**Distinção conceitual (fato, não proposta):**

| Categoria | Natureza | Quando ocorre |
|---|---|---|
| Juros da operação | Custo financeiro sobre saldo financiado (ex.: parcelamento com juros do emissor) | Quando a compra é parcelada com juros cobrados pelo cartão, distinto de parcelamento "sem juros" do lojista |
| Multa por atraso | Penalidade contratual/legal sobre valor em atraso | Fatura não paga até o vencimento |
| Encargos financeiros | Custo genérico associado ao saldo em aberto (ex.: taxa de manutenção de rotativo) | Fatura não paga integralmente, entra em "rotativo" |
| Tarifa | Custo administrativo (ex.: segunda via, saque) | Independente de atraso ou financiamento |
| Encargos de financiamento/rotativo | Juros compostos sobre saldo não pago integralmente | Quando parte da fatura não é quitada e vira dívida rotativa |

**Alternativas de tratamento:**

**A — Incorporados à compra original.** Rejeitada tecnicamente pelo mesmo
motivo do D9/Alternativa 1, agravado: juros, multa e encargos de rotativo
não pertencem a nenhuma compra específica — são encargos da fatura como um
todo ou do saldo em atraso, sem vínculo causal com um item de compra
individual. Vincular a uma compra seria semanticamente incorreto, não
apenas menos rastreável.

**B — Despesas financeiras independentes.** `D Despesa Financeira — [Juros
| Multa | Encargo] / C Cartão`, lançado no fechamento da fatura em que o
encargo aparece, usando os tipos de item já aprovados em D4. Aumenta o
saldo do passivo do cartão exatamente como uma compra normal — o passivo
cresce, apenas a natureza da despesa contrapartida muda (financeira, não
operacional).

**C — Sub-passivo separado para rotativo.** Criar conta de Passivo distinta
("Cartão — Rotativo") para a parcela financiada com juros, separada do
passivo "Cartão" principal — mais fiel à natureza econômica de uma dívida
rotativa com juros compostos, mas introduz nova conta, nova regra de
transferência entre passivos e maior complexidade de implementação.

**Lançamentos (Alternativa B, recomendada):**

```text
Juros/Multa/Encargo:
  D — Despesa Financeira (Juros | Multa | Encargo Cartão)
  C — Passivo: Cartão de Crédito
```

**Recomendação técnica:** Alternativa B para esta primeira versão —
consistente com D4/D9 já aprovados, sem exigir conta de passivo nova.
Alternativa C registrada como evolução possível, não recomendada nesta
etapa por desproporção entre complexidade e benefício imediato.

Decisão não tomada nesta nota — apresentada para deliberação da Direção.

---

## D12 — Competência de parcelas

### Alternativa A — Competência integral na compra

- **Contabilidade:** despesa e passivo reconhecidos integralmente no mês da compra.
- **Fluxo de caixa:** não reflete o desembolso real futuro por parcela — o caixa só é afetado no pagamento da fatura mensal, mas a despesa já apareceu inteira antes disso.
- **Fatura:** cada fatura mensal soma apenas o valor da parcela correspondente ao passivo bancário, mas o registro contábil da despesa já ocorreu integralmente antes.
- **Passivo:** o passivo "Cartão de Crédito" cresce pelo valor total da compra no mês da aquisição, mesmo que o desembolso real seja parcelado nos meses seguintes — **inconsistência entre o saldo contábil do passivo e o saldo real devido ao banco por parcelas futuras**, ponto que precisa ser resolvido operacionalmente (ex.: o passivo reflete "total devido incluindo parcelas futuras", que é tecnicamente correto sob a ótica de obrigação total assumida).
- **Classificação:** simples — um único lançamento por compra.
- **Relatórios:** demonstrativo do mês da compra mostra a despesa cheia; meses seguintes não mostram nada dessa compra.
- **Competência mensal:** diverge do regime de competência estrito (que reconheceria 1/N da despesa por mês).
- **Cancelamentos:** simples — um único estorno cancela a compra inteira.
- **Estornos:** idem — sem necessidade de rastrear parcelas já "reconhecidas" versus futuras.
- **Parcelamentos longos (12x, 24x):** sem diferença de complexidade em relação a uma compra à vista — mesma estrutura de lançamento único.
- **Impacto no modelo de `Lancamento`:** usa os campos já existentes (`e_parcelado`, `parcela_atual`, `total_parcelas`) apenas como metadado informativo — nenhuma alteração de schema.
- **Compatibilidade com GnuCash:** direta — um lançamento, um split, sem necessidade de lançamentos futuros agendados.

### Alternativa B — Reconhecimento por parcela

- **Contabilidade:** cada parcela gera lançamento próprio no mês de competência correspondente — regime de competência estrito.
- **Fluxo de caixa:** mais aderente à realidade do desembolso mensal.
- **Fatura:** cada fatura mensal corresponde exatamente a um conjunto de lançamentos gerados naquele mês.
- **Passivo:** o passivo cresce de forma incremental, mês a mês, refletindo o saldo real devido — mais fiel à posição financeira real a qualquer momento.
- **Classificação:** mais complexa — é necessário classificar/gerar N lançamentos por compra, distribuídos no tempo.
- **Relatórios:** demonstrativos mensais mostram a despesa distribuída corretamente por competência.
- **Competência mensal:** aderente ao regime de competência estrito.
- **Cancelamentos:** uma compra cancelada após algumas parcelas já lançadas exige estornar as parcelas já lançadas e não gerar as futuras — lógica de cancelamento parcial, mais complexa que a Alternativa A.
- **Estornos:** mesma complexidade adicional do item acima.
- **Parcelamentos longos (12x, 24x):** exige mecanismo de geração de lançamentos futuros agendados — **inexistente hoje em qualquer parte do sistema** (nem para períodos contábeis regulares, conforme evidência já levantada no ADR 010).
- **Impacto no modelo de `Lancamento`:** exigiria lógica nova de agendamento/geração diferida, além dos campos já existentes — não é apenas reaproveitamento, é capacidade nova.
- **Compatibilidade com GnuCash:** exige exportação de lançamentos futuros ainda não ocorridos, ou reexportação incremental mês a mês — mais complexo, sem precedente no exportador atual.

### Alternativa C — Reconhecimento integral na compra + memo informativo por parcela

Combina a Alternativa A (lançamento contábil único, integral, no mês da
compra) com uso dos campos já existentes (`e_parcelado`, `parcela_atual`,
`total_parcelas`) puramente como **metadado de relatório gerencial** (ex.:
"restam 8 de 12 parcelas desta compra"), sem gerar lançamento contábil por
parcela. **Justificativa técnica no modelo existente:** os campos já
existem em `Lancamento` e já são formatados no exportador CSV
(`csv_exporter.py`) — essa alternativa é, na prática, a Alternativa A com
uso explícito e documentado desses campos para fins informativos, não uma
estrutura nova.

- **Contabilidade / Passivo / Fatura:** idênticos à Alternativa A.
- **Relatórios:** ganha a informação de "quantas parcelas restam" sem o custo de lançamentos futuros — diferença frente à Alternativa A é puramente de apresentação, não de lançamento.
- **Competência mensal:** mesma divergência da Alternativa A frente ao regime estrito — o metadado informativo não corrige isso contabilmente, apenas comunica.
- **Impacto no modelo de `Lancamento`:** nenhum além do já existente.
- **Compatibilidade com GnuCash:** idêntica à Alternativa A.

**Recomendação técnica:** Alternativa C. Reaproveita integralmente a
infraestrutura já existente (sem exigir mecanismo de lançamentos futuros
agendados, que não tem precedente no projeto), preserva simplicidade de
cancelamento/estorno, e ainda assim entrega a informação de parcelamento
pendente como metadado — mas **não resolve a divergência frente ao regime
de competência estrito**, que é uma questão contábil, não técnica. Esta
recomendação é técnica; a adequação ao regime de competência exigido pela
política contábil da empresa é decisão do Contador CRC.

Decisão não tomada nesta nota — apresentada para deliberação da Direção.

---

## D19 — CRC/validação externa

Verificação restrita aos artefatos de governança disponíveis (ADRs
001–008, Matriz de Prontidão, Pauta de Deliberação Gate 0). Nenhuma
suposição além do texto encontrado.

**1. Onde existe exigência formal de CRC:**
- **ADR 007** — exige aprovação do Contador CRC (junto ao Especialista em Controles Internos) especificamente para a **transição `0.x.x → 1.0.0`**, e validação do CRC durante o processo `0.999` ("Contador CRC valida lançamentos gerados contra lançamentos manuais").
- **Pauta de Deliberação Gate 0** — Item **D1** (segregação de funções criador≠aprovador): responsabilidade explícita de "Especialista em Controles Internos e Contador CRC". Item **D6** (modelo de IA para sugestão): responsabilidade conjunta "Técnica + CRC".
- **ADR 001** — lista "Contador CRC" como um dos decisores permanentes da equipe (papel na composição da equipe, não uma exigência de gate específico por ADR).
- **ADR 008** — "Senior Accountant CRC" integrou o painel externo que revisou aquele ADR (interface web/segurança) — precedente de um ADR específico ter sido submetido a parecer do CRC, por escolha registrada naquele ADR, não por regra geral.

**2. Onde existe apenas recomendação (não exigência):**
Não há, em nenhum artefato disponível, uma cláusula genérica do tipo "todo ADR que altera o modelo contábil requer aprovação do CRC". O que existe são instâncias pontuais (D1/D6 da Pauta Gate 0; painel do ADR 008) — não uma regra codificada aplicável a qualquer ADR novo.

**3. Existe exigência específica para alteração do modelo contábil?**
Não há regra formal genérica nesse sentido. Existe o precedente do ADR 008 (painel externo incluindo CRC foi usado para uma decisão sensível), mas isso é prática observada em um caso, não requisito documentado como regra geral.

**4. ADR 007 realmente limita a exigência de CRC à transição `0.x.x → 1.0.0`?**
**Confirmado por citação direta.** O texto da Decisão do ADR 007 é literal: *"A transição de `0.x.x` para `1.0.0` é um marco formal... Requer aprovação do Contador CRC responsável e do Especialista em Controles Internos"*. A única outra menção de CRC nesse ADR é sobre o processo `0.999` (validação de lançamentos antes do congelamento), que é etapa que antecede essa mesma transição — não há, no ADR 007, exigência de CRC para ADRs individuais de arquitetura durante a fase `0.x.x`.

**5. D9, D10 e D12 devem ser submetidas a validação contábil externa?**
> **Não existe requisito formal identificado nas fontes atuais.**

**Recomendação técnica (separada da regra de governança acima):** dado que
D9/D10/D12 definem partidas dobradas e classificação fiscal (IOF, juros,
competência), e dado o precedente voluntário do ADR 008, recomenda-se
submeter especificamente D9, D10 e D12 a parecer do Contador CRC antes da
aprovação final — como boa prática de prudência da Direção, não como
obrigação identificada nas fontes disponíveis.

Decisão não tomada nesta nota — apresentada para deliberação da Direção.

---

## Matriz final

| Decisão | Questão | Alternativas | Recomendação técnica | Dependência externa | Decisão necessária |
|---|---|---|---|---|---|
| **D9** | IOF | 1. Incorporado à compra · 2. Despesa financeira independente · 3. Absorvido sem discriminação | Alternativa 2 | Confirmação contábil/fiscal do tratamento do IOF (não obrigatória por regra formal — Seção D19) | Escolha entre as 3 alternativas |
| **D10** | Juros/multa/encargos | A. Incorporados à compra · B. Despesas financeiras independentes · C. Sub-passivo rotativo separado | Alternativa B | Idem D9 | Escolha entre as 3 alternativas |
| **D12** | Competência de parcelas | A. Integral na compra · B. Por parcela · C. Integral + memo informativo | Alternativa C | Confirmação do regime de competência exigido pela política contábil da empresa (decisão do CRC, não técnica) | Escolha entre as 3 alternativas |
| **D19** | CRC/validação externa | Exigir CRC para D9/D10/D12 · Não exigir | Nenhuma recomendação técnica — é decisão de governança, não de arquitetura. Nota: não há requisito formal identificado | Não há dependência formal comprovada; existe precedente pontual (ADR 008) | Definir se D9/D10/D12 serão submetidas a parecer do CRC antes de fechamento |

**Achado adicional a resolver, fora desta matriz:** colisão de numeração —
`ADR 009` já reservado para Open Finance na Matriz de Prontidão. Recomenda-
se decisão sobre renumeração do ADR de cartão antes do fechamento formal.

---

**Regra de parada aplicada.** Nenhum código, migration, teste, pipeline ou
conteúdo decisório do ADR 010 foi alterado. Nenhuma decisão foi tomada em
nome da Direção. Aguardando deliberação final de D9, D10, D12 e D19, e
orientação sobre a colisão de numeração identificada.

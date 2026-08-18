# Caderneta — Pauta de Deliberação ADR 010 / Cartão de Crédito

Branch `feature/cartao-credito` | `main` intocado | Nenhum código, migration ou teste alterado nesta etapa

**Regra de conciliação (vigente em todos os itens desta pauta):**
A proposta não introduz mecanismo de conciliação N:1.

```text
1 Fatura                          1 Transação Bancária
 ├── Item 1                              ↕
 ├── Item 2                    1 Lançamento de Pagamento
 ├── Item 3                              ↕
 └── Item N                          1 Fatura
```

Não há, em nenhuma decisão abaixo, proposta de conciliar N compras individuais contra 1 transação bancária.

**Como usar:** para cada item, a Direção marca **APROVAR / ALTERAR / REJEITAR / ADIAR**. Itens não decididos bloqueiam apenas as etapas de implementação que deles dependem (ver dependências no ADR 010), não o restante da linha `feature/cartao-credito`.

---

## D1 — Modelo de domínio

**1. Decisão a tomar:** qual estrutura representa uma fatura de cartão no domínio.

**2. Proposta no ADR:** Alternativa A — `FaturaCartao` como agregado novo, com `CompraCartao` como itens filhos.

**3. Alternativas:**
- A — agregado dedicado (`Documento → FaturaCartao → CompraCartao`)
- B — `Documento` estendido com lista de itens internos
- C — itens como `Documento`s independentes ligados por referência cruzada

**4. Impacto contábil:** nenhum diretamente — é decisão de modelagem, não de partidas. Mas condiciona como o total da fatura é validado contra a soma dos itens.

**5. Impacto arquitetural:** A introduz entidades e repositórios novos; B reaproveita `Documento` mas quebra a invariante implícita "1 Documento = 1 transação", usada hoje em `ProcessarDocumentoUseCase`, `ParserFactory` e auditoria; C mistura o conceito de fatura com o padrão já usado para parcelamento (`lancamento_pai_id`), o que gera ambiguidade semântica.

**6. Impacto no código existente:** A — nenhum arquivo existente é alterado em sua semântica, só estendido. B — múltiplos pontos que assumem `Documento` 1:1 precisam ser revisados (risco de regressão disperso). C — nenhuma entidade nova, mas lógica de agregação empurrada para fora do domínio.

**7. Risco por alternativa:** A — maior superfície inicial, menor dívida futura. B — risco de regressão em fluxos não isolados que já tratam `Documento` como 1:1. C — validação de fechamento da fatura (itens + encargos − créditos = total) fica difícil de expressar sem entidade agregadora.

**8. Recomendação técnica:** Alternativa A.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D2 — Entidade `CartaoCredito`

**1. Decisão a tomar:** criar `CartaoCredito` como entidade de domínio própria (emissor, final do número, titular, status ativo).

**2. Proposta no ADR:** entidade mínima, relação 1:1 com uma `ContaContabil` de natureza Passivo.

**3. Alternativas:** (a) entidade própria (proposta); (b) tratar "cartão" apenas como um atributo da `ContaContabil` (sem entidade separada); (c) tratar "cartão" apenas como metadado do `Documento`/fatura, sem persistência própria.

**4. Impacto contábil:** nenhum direto — afeta apenas onde a identidade do cartão é armazenada.

**5. Impacto arquitetural:** (a) exige repositório e migration próprios; (b) simplifica, mas dificulta identificar o mesmo cartão em faturas de meses diferentes sem entidade estável; (c) inviabiliza reuso de conta entre faturas — cada fatura recriaria a conta.

**6. Impacto no código existente:** nenhum arquivo existente alterado; é adição pura.

**7. Risco:** (a) baixo, mais código; (b)/(c) risco de duplicidade de conta contábil por cartão ao longo do tempo, quebrando o requisito de idempotência de conta (D6).

**8. Recomendação técnica:** (a) — entidade própria.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D3 — Entidade `FaturaCartao`

**1. Decisão a tomar:** criar `FaturaCartao` como agregado (período, vencimento, cartão, total declarado).

**2. Proposta no ADR:** entidade nova, dependente da decisão D1.

**3. Alternativas:** condicionadas a D1 — se D1 for B ou C, este item não se aplica na forma proposta.

**4. Impacto contábil:** permite validar total da fatura (itens + encargos − créditos) como invariante antes de gerar lançamentos — sem essa entidade, essa validação fica dispersa ou ausente.

**5. Impacto arquitetural:** consequência direta de D1 = A.

**6. Impacto no código existente:** nenhum, adição pura.

**7. Risco:** nenhum adicional além do já registrado em D1.

**8. Recomendação técnica:** aprovar em conjunto com D1 = A.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D4 — Entidade `CompraCartao`

**1. Decisão a tomar:** criar `CompraCartao` como item da fatura (estabelecimento, valor, data, parcela, tipo de item).

**2. Proposta no ADR:** entidade nova, filha de `FaturaCartao`.

**3. Alternativas:** mesma dependência de D1.

**4. Impacto contábil:** é a unidade que gera o lançamento de compra (D5) — sem ela, não há granularidade para classificar cada item separadamente (compra vs. juros vs. IOF vs. anuidade).

**5. Impacto arquitetural:** consequência de D1 = A.

**6. Impacto no código existente:** nenhum, adição pura.

**7. Risco:** nenhum adicional além do já registrado em D1.

**8. Recomendação técnica:** aprovar em conjunto com D1 = A.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D5 — Relação fatura → itens

**1. Decisão a tomar:** como os itens se relacionam com a fatura e como o fechamento é validado.

**2. Proposta no ADR:** `FaturaCartao` contém N `CompraCartao`; invariante de fechamento (soma dos itens = total declarado da fatura) verificada no agregado antes de gerar lançamentos.

**3. Alternativas:** (a) validação no agregado (proposta); (b) sem validação de fechamento — cada item processado independentemente; (c) validação apenas informativa (log de divergência, sem bloqueio).

**4. Impacto contábil:** (a) impede que uma fatura mal extraída gere lançamentos com soma incorreta; (b)/(c) permitem lançamentos que não batem com o total real da fatura, sem alerta.

**5. Impacto arquitetural:** (a) exige que a extração produza todos os itens antes de qualquer lançamento ser gerado — processamento em duas fases (extração completa → validação → lançamento), não streaming item a item.

**6. Impacto no código existente:** nenhum, é comportamento novo.

**7. Risco:** (a) fatura com item não reconhecido pelo parser bloqueia todo o processamento até correção manual — pode ser visto como rigor excessivo ou como controle interno correto, a depender da tolerância operacional desejada.

**8. Recomendação técnica:** (a), com fallback: divergência gera item para revisão humana (não erro fatal), coerente com o princípio geral do projeto (regra determinística com fallback de revisão, não bloqueio duro).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D6 — Conta de Passivo do cartão

**1. Decisão a tomar:** como a conta contábil do cartão é criada e identificada.

**2. Proposta no ADR:** reaproveitar `ContaContabil` existente (campo `tipo` livre, `guid_gnucash` já presente); criação idempotente na primeira identificação do cartão; sem código de plano de contas fixo.

**3. Alternativas:** (a) reaproveitar `ContaContabil` (proposta); (b) criar tabela de conta específica para cartões, fora do plano de contas geral; (c) usar código de plano de contas fixo pré-definido neste ADR.

**4. Impacto contábil:** (a) mantém o cartão dentro do plano de contas único da empresa, auditável junto com o restante; (b) fragmenta a visão contábil; (c) engessa a numeração antes de decisão do contador responsável.

**5. Impacto arquitetural:** (a) nenhuma alteração de schema em `ContaContabil`; (b) nova tabela e nova integração com exportação GnuCash; (c) nenhuma, mas reduz flexibilidade.

**6. Impacto no código existente:** (a) nenhum — `ContaContabil` já suporta o caso sem alteração.

**7. Risco:** (a) baixo. (b) duplica conceito já existente, contra o princípio "estender antes de duplicar". (c) risco de código de conta conflitar com plano de contas real da empresa.

**8. Recomendação técnica:** (a).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D7 — Lançamento de compra

**1. Decisão a tomar:** formato do lançamento gerado por item de compra.

**2. Proposta no ADR:** `D Despesa/Ativo — C Passivo: Cartão de Crédito`, um lançamento por item.

**3. Alternativas:** (a) proposta; (b) um único lançamento agregado por fatura (soma de todos os itens), sem lançamento por item.

**4. Impacto contábil:** (a) preserva rastreabilidade por estabelecimento/item, essencial para classificação e auditoria; (b) perde granularidade — não é possível auditar item a item depois.

**5. Impacto arquitetural:** (a) consistente com `LancamentoService` atual (um lançamento por unidade classificável); (b) exigiria agregação prévia, indo contra o padrão de classificação por documento/item já usado no resto do sistema.

**6. Impacto no código existente:** (a) `LancamentoService._gerar_splits` precisa aceitar múltiplos lançamentos por fatura, mas mantém a mesma forma de gerar cada um; (b) exigiria lógica de agregação nova, sem paralelo no código atual.

**7. Risco:** (a) baixo, alinhado ao padrão existente. (b) perda de rastreabilidade, contra princípio de auditabilidade do projeto.

**8. Recomendação técnica:** (a).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D8 — Lançamento de pagamento

**1. Decisão a tomar:** formato do lançamento gerado pelo pagamento da fatura.

**2. Proposta no ADR:** `D Passivo: Cartão de Crédito — C Ativo: Banco`, **um único lançamento agregado** por fatura paga (não um por compra).

**3. Alternativas:** (a) proposta — um lançamento agregado; (b) N lançamentos de pagamento, um por compra original, distribuindo o valor total.

**4. Impacto contábil:** (a) reflete corretamente que o pagamento é a liquidação do passivo total, não um novo evento por compra; (b) reintroduziria a confusão que o modelo pretende evitar (Seção 3.2 do ADR — "por que o pagamento não é nova despesa").

**5. Impacto arquitetural:** (a) compatível diretamente com o conciliador atual (1 `TransacaoBancaria` ↔ 1 `Lancamento`); (b) exigiria mecanismo de conciliação N:1 — **explicitamente fora de escopo desta proposta** (ver regra de conciliação no cabeçalho desta pauta).

**6. Impacto no código existente:** (a) nenhuma alteração no `MotorConciliacao`; (b) exigiria reescrever `_buscar_candidatos`/`_decidir` para suportar agregação — mudança estrutural não aprovada.

**7. Risco:** (a) baixo. (b) alto — contraria decisão já tomada nesta mesma linha de trabalho de não introduzir N:1.

**8. Recomendação técnica:** (a), sem alternativa viável dentro do escopo já definido.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D9 — IOF

**1. Decisão a tomar:** classificação contábil do IOF cobrado na fatura.

**2. Proposta no ADR:** despesa financeira ou custo da operação, conforme classificação fiscal — **não resolvido no ADR**, sinalizado como pendente de confirmação contábil.

**3. Alternativas:** (a) despesa financeira (`D Despesa Financeira / C Cartão`); (b) custo direto agregado ao valor do item de compra; (c) tratamento fiscal específico não coberto pelas alternativas acima.

**4. Impacto contábil:** decisão puramente contábil/fiscal — fora da competência técnica desta análise. **Não há evidência suficiente nas fontes disponíveis** (nenhum ADR ou documento do projeto trata tributação sobre operações de cartão).

**5. Impacto arquitetural:** nenhum, independente da alternativa — é apenas qual conta de despesa o item aponta.

**6. Impacto no código existente:** nenhum.

**7. Risco:** classificação fiscal incorreta tem consequência tributária real após homologação (`v1.0.0`) — ainda que baixo em `0.x.x` (pré-produção, sem dados reais).

**8. Recomendação técnica:** nenhuma — decisão deve vir do Contador CRC responsável, não da equipe técnica.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D10 — Juros/multa

**1. Decisão a tomar:** classificação contábil de juros e multa por atraso.

**2. Proposta no ADR:** despesa financeira, item separado da compra original.

**3. Alternativas:** (a) despesa financeira (proposta); (b) agregado ao saldo do passivo sem lançamento de despesa próprio.

**4. Impacto contábil:** (a) reconhece o custo financeiro no período em que ocorre, correto sob regime de competência; (b) subestima despesas financeiras do período.

**5. Impacto arquitetural:** nenhum — mesmo padrão de item de fatura (D4/D7).

**6. Impacto no código existente:** nenhum.

**7. Risco:** (b) risco de demonstrativo financeiro incorreto quanto a despesas financeiras.

**8. Recomendação técnica:** (a).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D11 — Créditos/estornos/ajustes

**1. Decisão a tomar:** tratamento de créditos na fatura, estornos de compras e ajustes pós-fechamento.

**2. Proposta no ADR:** créditos/estornos reaproveitam `core/rule_engine/estorno.py` (padrão já existente); **ajustes pós-fechamento sem tratamento definido — não há evidência suficiente nas fontes disponíveis**.

**3. Alternativas para ajustes pós-fechamento:** (a) tratar como novo item na fatura seguinte; (b) reabrir a fatura já fechada para correção; (c) não tratar nesta versão — registrar como fora de escopo explícito.

**4. Impacto contábil:** créditos/estornos — nenhum novo, reaproveita padrão testado. Ajustes pós-fechamento — (b) fere a invariante de fechamento definida em D5; (a) e (c) preservam a invariante.

**5. Impacto arquitetural:** créditos/estornos — nenhum. Ajustes — (b) exigiria mecanismo de reabertura de agregado fechado, não existente em nenhuma parte do sistema hoje (nem para períodos contábeis regulares).

**6. Impacto no código existente:** créditos/estornos — nenhum, reuso direto. Ajustes — depende da alternativa.

**7. Risco:** (b) risco arquitetural desproporcional ao problema — reabertura de agregado fechado é um padrão novo e sensível que não deveria ser introduzido apenas para este caso.

**8. Recomendação técnica:** créditos/estornos — aprovar reuso de `estorno.py`. Ajustes pós-fechamento — (c), registrar como fora de escopo explícito nesta primeira versão.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D12 — Competência de parcelas

**1. Decisão a tomar:** se cada parcela gera lançamento contábil próprio por competência mensal, ou se a compra parcelada gera um único lançamento no valor total.

**2. Proposta no ADR:** lançamento único no valor total da compra, com metadado de parcelamento (`e_parcelado`, `parcela_atual`, `total_parcelas` — campos já existentes em `Lancamento`), sem lançamento por parcela.

**3. Alternativas:** (a) lançamento único (proposta); (b) um lançamento por parcela, na competência do respectivo mês.

**4. Impacto contábil:** (a) reconhece a despesa/passivo integralmente no momento da compra — divergente do regime de competência estrito, que reconheceria cada parcela no mês correspondente; (b) mais aderente à competência estrita, mas gera N lançamentos por compra parcelada, todos contra a mesma conta de Passivo do cartão, exigindo baixa parcial do passivo a cada mês.

**5. Impacto arquitetural:** (a) usa os campos já existentes sem novo modelo; (b) exigiria lógica de geração programada de lançamentos futuros (um por mês), inexistente hoje em qualquer parte do sistema.

**6. Impacto no código existente:** (a) nenhuma alteração de schema. (b) exigiria mecanismo novo de agendamento/geração diferida de lançamentos.

**7. Risco:** (a) risco contábil se a competência estrita for exigida pela política da empresa/contador. (b) risco arquitetural de introduzir um padrão novo (lançamentos futuros agendados) sem precedente no projeto, para resolver um caso específico.

**8. Recomendação técnica:** (a), por reaproveitar infraestrutura existente — **mas esta é uma decisão contábil, não técnica**, e deve ser confirmada pelo Contador CRC responsável antes de aprovação final.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D13 — Idempotência

**1. Decisão a tomar:** chaves de identidade/idempotência por nível (documento/fatura, item, lançamento, pagamento).

**2. Proposta no ADR:** hash de arquivo para o Documento; `(cartão, período)` para a Fatura; `(fatura_id, posição/hash da linha)` para o Item; `(compra_id)` 1:1 para o Lançamento de compra; `(conta_bancaria, FITID)` já implementado para a Transação Bancária de pagamento.

**3. Alternativas:** (a) chaves por nível, como proposto; (b) hash de arquivo como identidade universal para todos os níveis.

**4. Impacto contábil:** (b) risco de duplicidade de lançamentos em reprocessamento parcial (ex.: reenvio da mesma fatura após correção manual de um item), contrariando o requisito de idempotência do domínio.

**5. Impacto arquitetural:** (a) exige implementar dedup em múltiplos pontos do pipeline, não apenas no gate de entrada do `ProcessarDocumentoUseCase` como hoje.

**6. Impacto no código existente:** (a) `ProcessarDocumentoUseCase` precisa de ajuste no mecanismo de dedup, hoje restrito a hash de arquivo inteiro — gap já identificado e válido mesmo sem cartão.

**7. Risco:** (b) alto — é exatamente o gap já demonstrado com evidências no parecer técnico anterior (dedup por arquivo não cobre transação).

**8. Recomendação técnica:** (a).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D14 — FITID (débito técnico pré-existente)

**1. Decisão a tomar:** quando e como corrigir a desconexão do FITID em `MotorConciliacao._fitid_do_lancamento`.

**2. Proposta no ADR:** classificar como **débito técnico pré-existente**, não específico de cartão. Alternativa B — corrigir como pré-requisito **obrigatório de saída** da etapa de conciliação do pagamento do cartão, não como bloqueio ao início da feature.

**3. Alternativas:** A — corrigir antes de iniciar qualquer código de cartão; B — corrigir apenas antes de concluir a etapa de conciliação do pagamento (proposta).

**4. Impacto contábil:** nenhum direto — é um mecanismo de matching, não de lançamento. Indiretamente, sem a correção, o pagamento do cartão só é conciliado por valor+data (Camada 2), não por match exato (Camada 1).

**5. Impacto arquitetural:** correção é local a `MotorConciliacao`/`LancamentoService` (propagar FITID de `Documento` para `Lancamento`) — não afeta o modelo de domínio de cartão.

**6. Impacto no código existente:** correção exige alteração em `core/rule_engine/lancamento_service.py` (propagação) e/ou `core/domain/entities.py` (campo em `Lancamento`), com teste dedicado — **não deve ser incorporada silenciosamente à implementação de outra funcionalidade**, deve ter commit e teste identificáveis próprios.

**7. Risco:** A — atraso no início da feature por um problema não específico dela. B — se não for tratado como pré-requisito formal de saída da etapa de conciliação, risco de ser adiado indefinidamente.

**8. Recomendação técnica:** B, com a condição de que a etapa de conciliação do pagamento não seja considerada concluída sem a correção testada.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D15 — Conciliação

**1. Decisão a tomar:** confirmar o modelo de conciliação do pagamento do cartão.

**2. Proposta no ADR:** `1 Transação Bancária ↔ 1 Lançamento de Pagamento ↔ 1 Fatura`. Nenhum mecanismo N:1 para compras individuais.

**3. Alternativas:** (a) proposta — conciliação 1:1 do pagamento agregado; (b) conciliar cada compra individualmente contra o extrato bancário (impossível na prática — compras não aparecem individualmente no extrato do banco, só o pagamento da fatura aparece).

**4. Impacto contábil:** (a) único modelo compatível com a realidade do extrato bancário, que só mostra o pagamento agregado da fatura, nunca as compras individuais.

**5. Impacto arquitetural:** (a) zero alteração no `MotorConciliacao` — reaproveitamento direto.

**6. Impacto no código existente:** (a) nenhum.

**7. Risco:** (b) tecnicamente inviável — não há dado bancário correspondente a compras individuais de cartão de crédito.

**8. Recomendação técnica:** (a), única alternativa tecnicamente correta — não apresentada como escolha entre equivalentes.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D16 — Eventos de auditoria

**1. Decisão a tomar:** quais eventos novos entram no catálogo (`core/events/catalog.py`).

**2. Proposta no ADR:** mínimo de três — `FaturaCartaoRecebida`, `FaturaCartaoClassificada`, `PagamentoCartaoIdentificado`.

**3. Alternativas:** (a) mínimo proposto; (b) conjunto mais amplo (ex.: evento por item, evento por lançamento gerado); (c) nenhum evento novo — reaproveitar eventos genéricos já existentes (`DocumentoRecebido`, `ClassificacaoConcluida`, `LancamentoCriado`).

**4. Impacto contábil:** nenhum — é rastreabilidade, não lançamento.

**5. Impacto arquitetural:** (b) infla o catálogo além do necessário, contra o princípio de economia já aplicado ao catálogo existente; (c) perde a granularidade de saber que um evento é especificamente de cartão, dificultando auditoria futura desse fluxo específico.

**6. Impacto no código existente:** (a)/(b) adição ao catálogo, sem alterar eventos existentes. (c) nenhuma adição.

**7. Risco:** (b) risco de eventos redundantes nunca consumidos. (c) risco de perda de rastreabilidade específica de cartão em auditoria.

**8. Recomendação técnica:** (a).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D17 — CLI

**1. Decisão a tomar:** comandos de linha de comando para importar/consultar faturas e cartões.

**2. Proposta no ADR:** esboço análogo ao padrão já existente (`conciliacao_importar`/`conciliacao_executar`) — nomes definitivos não fechados.

**3. Alternativas:** (a) seguir o padrão de nomenclatura existente (proposta); (b) nomenclatura nova, desalinhada do padrão atual do `core/cli.py`.

**4. Impacto contábil:** nenhum.

**5. Impacto arquitetural:** (a) mantém consistência com `processar`, `revisar`, `importar`, `conciliacao_*` já existentes; (b) fragmenta a convenção de nomes do CLI.

**6. Impacto no código existente:** ambos são adição pura em `core/cli.py`, sem alterar comandos existentes.

**7. Risco:** (b) inconsistência de UX para quem já usa o CLI.

**8. Recomendação técnica:** (a), com nomes definitivos a fechar em revisão de código, não nesta pauta.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D18 — GnuCash

**1. Decisão a tomar:** confirmar que a exportação da conta de Passivo do cartão não exige alteração no exportador.

**2. Proposta no ADR:** nenhuma mudança em `core/adapters/csv_exporter.py` — a conta do cartão é exportada como qualquer `ContaContabil`, desde que `guid_gnucash` seja preenchido na criação (D6).

**3. Alternativas:** (a) nenhuma alteração no exportador (proposta); (b) lógica específica no exportador para tratar contas de cartão de forma diferenciada.

**4. Impacto contábil:** nenhum, desde que o mapeamento de tipo (Passivo) esteja correto na origem (D6).

**5. Impacto arquitetural:** (a) zero alteração; (b) introduz acoplamento entre o exportador genérico e o domínio de cartão, contra a separação de camadas do projeto.

**6. Impacto no código existente:** (a) nenhum.

**7. Risco:** (b) acoplamento desnecessário.

**8. Recomendação técnica:** (a), com item de teste dedicado para confirmar que o mapeamento realmente resulta em conta de Passivo, não bancária.

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## D19 — Necessidade de validação externa/CRC

**1. Decisão a tomar:** se este ADR e/ou sua implementação exigem parecer formal do painel externo (Contador CRC) antes de aprovação.

**2. Proposta no ADR:** **não há exigência formal comprovada** nos artefatos de governança disponíveis para ADRs deste tipo — ADR 007 exige CRC apenas para a transição `0.x.x → 1.0.0`. Registrado como recomendação técnica a deliberar, não decisão já existente.

**3. Alternativas:** (a) não exigir CRC neste ADR, tratando-o como decisão técnica de arquitetura (proposta); (b) exigir parecer do CRC antes de aprovação, dado o impacto em partidas dobradas e itens fiscalmente sensíveis (D9, D10, D12).

**4. Impacto contábil:** (b) reduz risco de modelagem contábil formalmente incorreta chegar a `v1.0.0`; (a) mantém a decisão puramente técnica, com risco de itens como IOF/competência de parcela (já sinalizados como pendentes em D9/D12) ficarem sem validação formal até mais tarde.

**5. Impacto arquitetural:** nenhum, é decisão de processo de governança, não de código.

**6. Impacto no código existente:** nenhum.

**7. Risco:** (a) risco de decisão contábil incorreta avançar sem validação formal. (b) atraso no fechamento do ADR até disponibilidade do CRC.

**8. Recomendação técnica:** nenhuma recomendação técnica — é decisão de governança, não de arquitetura. Nota: dado que D9, D10 e D12 já estão marcados como pendentes de confirmação contábil, a exigência de CRC pode ser aplicada especificamente a esses três itens, sem bloquear os itens puramente técnicos (D1–D8, D13–D18).

**9. Decisão da Direção:** [ ] APROVAR &nbsp; [ ] ALTERAR &nbsp; [ ] REJEITAR &nbsp; [ ] ADIAR

---

## Encerramento

Nenhuma decisão acima foi tomada em nome da Direção. Todas as recomendações técnicas (item 8 de cada tópico) são propostas, não decisões — inclusive nos itens onde a alternativa proposta é apresentada como "única tecnicamente correta" (D15), a confirmação formal permanece necessária.

**Regra de parada aplicada:** nenhum código, migration, teste ou alteração no motor de conciliação foi feito para produzir esta pauta. `main` intocado. Aguardando deliberação item a item.

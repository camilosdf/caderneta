# Matriz de Prontidão para Implementação — ADR 010 / Cartão de Crédito

**ADR 010:** congelado documentalmente nesta etapa — 18/18 decisões
aprovadas, 5 correções de consistência aplicadas, D19 registrado como
validação de suporte contábil.

**Esta matriz não é implementação.** É o plano de execução verificável,
derivado das decisões já aprovadas, para uso quando a implementação for
autorizada. Nenhum código, migration, entidade, parser, OCR,
`LancamentoService`, FITID, motor de conciliação, CLI ou teste foi criado
ou alterado para produzi-la. Branch `feature/cartao-credito`; `main`
intocado.

---

## Ordem de execução geral (fases)

```text
Fase 0 — Migration (schema)
   ↓
Fase 1 — Entidades de domínio (D1–D6)
   ↓
Fase 2 — Parser PDF/OCR (independente das Fases 3–5, pode ocorrer em paralelo)
   ↓
Fase 3 — LancamentoService (D7, D8, D9, D10, D12)
   ↓
Fase 4 — Idempotência (D13) + Auditoria (D16) + CLI (D17)
   ↓
Fase 5 — Correção do FITID (D14) — pré-requisito de saída, não de início
   ↓
Fase 6 — Conciliação do pagamento (D15) — depende da Fase 5
   ↓
Fase 7 — GnuCash (D18) — validação, sem alteração de exportador
   ↓
Fase 8 — Testes completos + regressão total (transversal a todas as fases, fechamento final)
   ↓
Fase 9 — Pull Request → decisão sobre merge (fora desta matriz)
```

A Fase 2 (parser/OCR) não depende de nenhuma decisão contábil (D9/D10/D12)
— pode avançar em paralelo às Fases 1/3, desde que a extração de campos
seja neutra quanto à classificação final de cada item.

---

## D1 — Modelo de domínio (Alternativa A)

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `Documento → FaturaCartao → CompraCartao` como agregado novo |
| **Evidência existente no código** | `Documento` (`core/domain/entities.py:366`) é 1:1 com transação — não suporta N itens; padrão de entidade de domínio própria já existe em `TransacaoBancaria` (linha 599), usado como precedente |
| **Componente existente reaproveitado** | Nenhum diretamente — é o agregado raiz novo |
| **Componente a alterar** | Nenhum — `Documento` permanece com sua semântica atual |
| **Componente novo** | `FaturaCartao`, `CompraCartao` (dataclasses de domínio) |
| **Migration** | Sim — tabelas novas (ver Fase 0) |
| **Testes** | Criação, validação de invariantes básicas do agregado (sem itens = inválido; item órfão = inválido) |
| **Dependências** | Nenhuma — decisão raiz |
| **Critério de aceite** | Entidades compilam, testes de criação passam, nenhuma alteração em `Documento` existente quebra testes atuais |
| **Risco** | Baixo — adição pura |
| **Ordem de execução** | Fase 1, primeiro item |
| **Regra de parada** | Não prosseguir para D2–D5 sem os testes de invariante básica passando |

---

## D2 — Entidade `CartaoCredito`

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Entidade própria (emissor, final do número, titular, status ativo) |
| **Evidência existente no código** | Nenhuma entidade equivalente hoje |
| **Componente existente reaproveitado** | Nenhum |
| **Componente a alterar** | Nenhum |
| **Componente novo** | `CartaoCredito` (dataclass) |
| **Migration** | Sim — tabela nova (ver Fase 0) |
| **Testes** | Criação; identidade natural do cartão (**AINDA NÃO DEFINIDO no ADR** — chave exata a resolver antes de codificar este item) |
| **Dependências** | Nenhuma |
| **Critério de aceite** | Entidade compila; teste de idempotência de criação (mesmo cartão não gera duas entidades) passa, uma vez definida a chave de identidade |
| **Risco** | Médio — bloqueado por ambiguidade remanescente do ADR (chave de identidade); não iniciar a codificação deste item sem resolver isso primeiro |
| **Ordem de execução** | Fase 1, em paralelo a D3/D4 |
| **Regra de parada** | Não implementar `salvar_se_nova`-equivalente para `CartaoCredito` sem a chave de identidade definida — resolver a ambiguidade é pré-requisito de código, não um detalhe a decidir durante a implementação |

---

## D3 — Entidade `FaturaCartao`

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Agregado com período, vencimento, cartão, total declarado |
| **Evidência existente no código** | Nenhuma |
| **Componente existente reaproveitado** | Relação com `CartaoCredito` (D2) |
| **Componente a alterar** | Nenhum |
| **Componente novo** | `FaturaCartao` (dataclass) |
| **Migration** | Sim — tabela nova (ver Fase 0) |
| **Testes** | Criação; invariante de fechamento (item+encargos−créditos=total, conforme correção aplicada ao D5) |
| **Dependências** | D1, D2 |
| **Critério de aceite** | Testes de invariante de fechamento passam para os casos: exato, com encargos, com créditos, e caso de divergência (deve gerar item para revisão, não erro fatal) |
| **Risco** | Médio — tolerância numérica de arredondamento não definida no ADR; decidir antes de codificar a validação |
| **Ordem de execução** | Fase 1 |
| **Regra de parada** | Não prosseguir para D4/D5 sem a tolerância numérica definida e testada |

---

## D4 — Entidade `CompraCartao`

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Item da fatura — estabelecimento, valor, data, parcela, tipo (compra/juros/IOF/anuidade/estorno) |
| **Evidência existente no código** | Nenhuma; `Lancamento.e_parcelado/parcela_atual/total_parcelas` já existem e serão reaproveitados na Fase 3 (D12) |
| **Componente existente reaproveitado** | Nenhum diretamente nesta entidade |
| **Componente a alterar** | Nenhum |
| **Componente novo** | `CompraCartao` (dataclass), enum de tipo de item |
| **Migration** | Sim — tabela nova (ver Fase 0) |
| **Testes** | Criação; cada tipo de item (compra/juros/IOF/multa/encargo/anuidade/estorno) instancia corretamente |
| **Dependências** | D1, D3 |
| **Critério de aceite** | Todos os tipos de item do enum cobertos por teste de criação |
| **Risco** | Baixo |
| **Ordem de execução** | Fase 1 |
| **Regra de parada** | Não prosseguir para a Fase 3 (lançamentos) sem os 7 tipos de item testados |

---

## D5 — Relação fatura → itens (invariante de fechamento)

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `itens + encargos − créditos/estornos = total declarado`; divergência gera item para revisão humana |
| **Evidência existente no código** | Nenhuma validação equivalente hoje |
| **Componente existente reaproveitado** | Padrão de "revisão humana em baixa confiança" já é princípio geral do projeto (`PolicyEngine`) |
| **Componente a alterar** | Nenhum |
| **Componente novo** | Serviço/método de validação de fechamento em `FaturaCartao` |
| **Migration** | Não — é lógica, não schema |
| **Testes** | Fechamento exato; com encargos; com créditos; divergência dentro/fora da tolerância |
| **Dependências** | D3, D4, tolerância numérica definida |
| **Critério de aceite** | 100% dos casos de teste acima passando |
| **Risco** | Médio — mesma pendência de tolerância numérica de D3 |
| **Ordem de execução** | Fase 1, após D3/D4 |
| **Regra de parada** | Não gerar nenhum `Lancamento` de uma fatura sem essa validação ter sido executada primeiro |

---

## D6 — Conta de Passivo do cartão

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Reaproveitar `ContaContabil` existente, natureza Passivo, criação idempotente, `guid_gnucash` preenchido |
| **Evidência existente no código** | `ContaContabil` (`core/domain/entities.py:282`) — `tipo: str` livre, `guid_gnucash` já presente |
| **Componente existente reaproveitado** | `ContaContabil` integralmente, sem alteração de schema |
| **Componente a alterar** | Nenhum |
| **Componente novo** | Serviço de criação/reuso idempotente de conta por cartão |
| **Migration** | Não — reaproveita schema existente |
| **Testes** | Criação de conta para cartão novo; reuso de conta para cartão já existente (idempotência); nenhuma duplicidade de conta para o mesmo cartão em execuções repetidas |
| **Dependências** | D2 (chave de identidade do cartão) |
| **Critério de aceite** | Teste de idempotência de conta passa de forma determinística |
| **Risco** | Médio — depende da mesma ambiguidade de chave de identidade de D2 |
| **Ordem de execução** | Fase 1, após D2 |
| **Regra de parada** | Não prosseguir para D7 sem a idempotência de conta comprovada por teste |

---

## D7 — Lançamento de compra

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `D Despesa/Ativo / C Passivo — Cartão`, um lançamento por item |
| **Evidência existente no código** | `LancamentoService._gerar_splits` gera 1 par D/C por documento — padrão a estender, não substituir |
| **Componente existente reaproveitado** | `LancamentoService`, `ClassificationPort` para classificar a despesa/ativo de destino |
| **Componente a alterar** | `LancamentoService` — aceitar múltiplos lançamentos por fatura (hoje assume 1 documento = 1 lançamento) |
| **Componente novo** | Nenhum — extensão de componente existente |
| **Migration** | Não |
| **Testes** | Um lançamento por `CompraCartao`; valor e contas corretos; múltiplos itens da mesma fatura geram múltiplos lançamentos independentes |
| **Dependências** | D1–D6 |
| **Critério de aceite** | Fatura com N itens gera N lançamentos de compra, cada um auditável e rastreável ao item de origem |
| **Risco** | Médio — é a primeira vez que `LancamentoService` gera mais de um lançamento por documento; testar regressão dos fluxos existentes (NF-e, OFX, CSV) que assumem 1:1 |
| **Ordem de execução** | Fase 3, junto com D9/D10/D12 |
| **Regra de parada** | Rodar suíte de regressão completa dos parsers existentes antes de considerar D7 concluído — não apenas os testes novos de cartão |

---

## D8 — Lançamento de pagamento

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `D Passivo — Cartão / C Ativo — Banco`, **um único lançamento agregado** por fatura paga |
| **Evidência existente no código** | Nenhum precedente direto — mas compatível com o padrão 1:1 já usado pelo conciliador |
| **Componente existente reaproveitado** | `LancamentoService` (mesma extensão de D7) |
| **Componente a alterar** | `LancamentoService` |
| **Componente novo** | Lógica de identificação de "fatura quitada" (todas as compras já lançadas + valor total = passivo acumulado) |
| **Migration** | Não |
| **Testes** | Um único lançamento gerado por fatura paga, nunca N; valor igual à soma do passivo acumulado da fatura |
| **Dependências** | D6, D7 |
| **Critério de aceite** | Teste explícito que comprove que N compras nunca geram N lançamentos de pagamento — apenas 1 |
| **Risco** | Alto se violado — reintroduziria exatamente o padrão de conciliação N:1 vedado pelo ADR (item 19 da baseline) |
| **Ordem de execução** | Fase 3, após D7 |
| **Regra de parada** | Bloquear o merge deste item se qualquer teste permitir mais de 1 lançamento de pagamento por fatura |

---

## D9 — IOF

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `D Despesas Financeiras — IOF / C Passivo — Cartão`, item separado, não incorporado ao valor da compra |
| **Evidência existente no código** | Nenhuma conta de despesa financeira cadastrada hoje — só contas fiscais em `tax_engine.py` |
| **Componente existente reaproveitado** | `ContaContabil` (mesmo padrão de D6) |
| **Componente a alterar** | `LancamentoService` (mesmo ponto de extensão de D7) |
| **Componente novo** | Conta "Despesas Financeiras — IOF" (nome/código exato — **AINDA NÃO DEFINIDO**) |
| **Migration** | Não, se a conta for criada via mesmo mecanismo paramétrico de D6 |
| **Testes** | Item tipo IOF gera lançamento correto; valor do IOF não se mistura ao valor da compra de origem |
| **Dependências** | D4 (tipo de item), D6 (padrão de conta) |
| **Critério de aceite** | Teste que separa explicitamente valor de compra e valor de IOF na mesma linha de fatura |
| **Risco** | Médio — depende de o parser/OCR (Fase 2) identificar corretamente a linha de IOF; se a extração falhar silenciosamente, o item pode ser mal classificado |
| **Ordem de execução** | Fase 3, junto com D7/D8/D10/D12 |
| **Regra de parada** | Não aceitar item classificado como IOF sem confiança mínima da extração — abaixo do limiar, gerar item para revisão humana, não lançamento automático |

---

## D10 — Juros/multa/encargos

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Despesas financeiras independentes, segregadas por natureza (Juros/Multas/Encargos); sem sub-passivo de rotativo |
| **Evidência existente no código** | Nenhuma |
| **Componente existente reaproveitado** | `ContaContabil` (mesmo padrão de D6/D9) |
| **Componente a alterar** | `LancamentoService` |
| **Componente novo** | Três contas de despesa financeira (Juros/Multas/Encargos — nomes exatos **AINDA NÃO DEFINIDOS**) |
| **Migration** | Não, mesmo mecanismo paramétrico |
| **Testes** | Cada uma das três categorias gera lançamento na conta correta; nenhuma mistura entre categorias |
| **Dependências** | D4, D6 |
| **Critério de aceite** | Teste que comprove segregação — juros, multa e encargo em contas distintas, não uma única conta genérica |
| **Risco** | Médio — mesma dependência de qualidade de extração do parser/OCR que D9; regra de identificação de qual linha é qual categoria **ainda não definida** no ADR |
| **Ordem de execução** | Fase 3, junto com D7/D8/D9/D12 |
| **Regra de parada** | Não classificar automaticamente uma linha ambígua entre juros/multa/encargo sem revisão humana — mesma regra de D9 |

---

## D11 — Créditos/estornos/ajustes *(já aprovado em etapa anterior, incluído aqui por completude de execução)*

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Créditos/estornos reaproveitam `core/rule_engine/estorno.py`; ajustes pós-fechamento fora de escopo |
| **Evidência existente no código** | `core/rule_engine/estorno.py` usa `lancamento_pai_id`, já existente em `Lancamento` |
| **Componente existente reaproveitado** | `EstornoService`/padrão de estorno, sem alteração |
| **Componente a alterar** | Nenhum |
| **Componente novo** | Nenhum |
| **Migration** | Não |
| **Testes** | Estorno de item de compra dentro de uma fatura de cartão usando o mecanismo já testado do sistema |
| **Dependências** | D4, D7 |
| **Critério de aceite** | Teste de estorno de `CompraCartao` reaproveitando `estorno.py` sem modificação do módulo |
| **Risco** | Baixo — reuso direto |
| **Ordem de execução** | Fase 3, junto com D7 |
| **Regra de parada** | Se `estorno.py` precisar de qualquer alteração para suportar cartão, isso é sinal de que D11 estava incompleto — parar e reabrir a decisão, não forçar o encaixe |

---

## D12 — Competência de parcelas

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Reconhecimento integral na aquisição; `e_parcelado`/`parcela_atual`/`total_parcelas` como metadado informativo apenas; Alternativa B rejeitada |
| **Evidência existente no código** | Campos já existem em `Lancamento` (`core/domain/entities.py:455-458`) e já são formatados em `csv_exporter.py:76-77` |
| **Componente existente reaproveitado** | Campos de `Lancamento` sem alteração de schema |
| **Componente a alterar** | `LancamentoService` — preencher os campos a partir de `CompraCartao.parcela` |
| **Componente novo** | Nenhum |
| **Migration** | Não |
| **Testes** | Compra parcelada gera 1 lançamento no valor total, com metadados corretos; **nenhum lançamento mensal adicional é gerado** — teste negativo explícito |
| **Dependências** | D4, D7 |
| **Critério de aceite** | Teste negativo (ausência de lançamentos futuros agendados) é obrigatório, não apenas o teste positivo do metadado |
| **Risco** | Baixo tecnicamente; risco de reinterpretação equivocada como "motor de parcelas" já mitigado pela correção de texto no plano de implementação do ADR |
| **Ordem de execução** | Fase 3, junto com D7 |
| **Regra de parada** | Se a implementação criar qualquer lógica de agendamento/geração futura de lançamentos, isso viola D12 explicitamente — parar imediatamente, não é um detalhe de implementação em aberto |

---

## D13 — Idempotência

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Chaves por nível — arquivo (Documento), `(cartão, período)` (Fatura), `(fatura_id, posição/hash)` (Item), `(compra_id)` (Lançamento), `(conta_bancaria, FITID)` (Transação, já implementado) |
| **Evidência existente no código** | `ProcessarDocumentoUseCase` dedup só por hash de arquivo inteiro; `TransacaoBancaria.salvar_se_nova` já correto |
| **Componente existente reaproveitado** | `TransacaoBancariaRepository.salvar_se_nova` como padrão a replicar nos demais níveis |
| **Componente a alterar** | `ProcessarDocumentoUseCase` — dedup por nível, não só por arquivo |
| **Componente novo** | Repositórios/métodos `salvar_se_nova`-equivalentes para `FaturaCartao` e `CompraCartao` |
| **Migration** | Não além da já prevista na Fase 0 (índices de unicidade podem ser necessários — detalhe de implementação) |
| **Testes** | Reenvio do mesmo PDF não duplica; reprocessamento parcial (item corrigido) não duplica os itens já processados |
| **Dependências** | D1, D3, D4 |
| **Critério de aceite** | Teste de reenvio integral E de reenvio parcial, ambos sem duplicidade |
| **Risco** | Médio — é o gap já identificado com evidências antes mesmo da feature de cartão existir; corrigir aqui não deve mascarar o gap genérico do `ProcessarDocumentoUseCase` para outros tipos de documento |
| **Ordem de execução** | Fase 4 |
| **Regra de parada** | Não declarar D13 concluído sem o teste de reprocessamento parcial — o teste de reenvio integral sozinho não comprova a decisão |

---

## D14 — FITID (débito técnico pré-existente)

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Alternativa B — correção obrigatória como pré-requisito de saída da etapa de conciliação (Fase 6), não de início da feature |
| **Evidência existente no código** | `MotorConciliacao._fitid_do_lancamento` verifica `hasattr(lanc, "numero_documento_origem")`, campo inexistente em `Lancamento`; confirmado por ausência de teste no caminho |
| **Componente existente reaproveitado** | Nenhum — é a correção do próprio componente |
| **Componente a alterar** | `core/domain/entities.py` (`Lancamento`) e/ou `core/rule_engine/lancamento_service.py` (propagação do FITID de `Documento`) |
| **Componente novo** | Nenhum |
| **Migration** | Possível, se o campo for adicionado a `Lancamento` e refletido em schema — a decidir na implementação |
| **Testes** | Teste dedicado, independente da feature de cartão, demonstrando o caminho `FITID → Lancamento → MotorConciliacao` (critério de aceite reforçado no ADR nesta última revisão) |
| **Dependências** | Nenhuma decisão de cartão — é debt independente |
| **Critério de aceite** | Commit próprio, teste próprio, não incorporado silenciosamente à Fase 3 ou 6 |
| **Risco** | Alto se adiado indefinidamente — a Fase 6 (conciliação) não pode ser dada como concluída sem esta correção |
| **Ordem de execução** | Fase 5 — antes da Fase 6, pode ocorrer a qualquer momento a partir da Fase 0 (é independente), mas **bloqueia a conclusão da Fase 6** |
| **Regra de parada** | A Fase 6 não é declarada concluída sem este item corrigido e testado — não é opcional, é pré-requisito de saída |

---

## D15 — Conciliação do pagamento

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | `1 Transação Bancária ↔ 1 Lançamento de Pagamento ↔ 1 Fatura`; sem mecanismo N:1 |
| **Evidência existente no código** | `MotorConciliacao` já é 1:1 (`TransacaoBancaria ↔ Lancamento`) — compatível sem alteração estrutural |
| **Componente existente reaproveitado** | `MotorConciliacao` integralmente, sem alteração de sua lógica de matching (Camadas 2/3) |
| **Componente a alterar** | Nenhum no motor — apenas garantir que o `Lancamento` de pagamento (D8) chegue a ele no formato esperado |
| **Componente novo** | Nenhum |
| **Migration** | Não |
| **Testes** | Pagamento de fatura concilia corretamente contra a transação bancária; nenhuma `CompraCartao` é candidata direta a conciliação (teste negativo explícito) |
| **Dependências** | D8, D14 (para uso de match exato por FITID) |
| **Critério de aceite** | Teste negativo de N:1 obrigatório — nenhuma tentativa de conciliar itens individuais deve ser aceita pela suíte |
| **Risco** | Alto se o teste negativo faltar — é o ponto mais sensível de toda a arquitetura aprovada (Seção 19 da baseline) |
| **Ordem de execução** | Fase 6, após Fase 5 (D14) |
| **Regra de parada** | Nenhum PR desta fase é aceito sem o teste negativo de N:1 presente e passando |

---

## D16 — Eventos de auditoria

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | No mínimo três eventos — recebimento, classificação, identificação de pagamento (nomes definitivos em aberto) |
| **Evidência existente no código** | `core/events/catalog.py` — lista fechada, sem eventos de cartão hoje |
| **Componente existente reaproveitado** | `core/audit/chain.py` (cadeia de hash, agnóstica ao tipo de evento) |
| **Componente a alterar** | `core/events/catalog.py` — adição, sem alterar eventos existentes |
| **Componente novo** | Três dataclasses de evento (nomes a fechar antes da implementação) |
| **Migration** | Não |
| **Testes** | Cada evento é gravado corretamente na cadeia de auditoria; rastreabilidade completa PDF→lançamento comprovável a partir dos eventos |
| **Dependências** | D1–D8 |
| **Critério de aceite** | Teste de rastreabilidade ponta a ponta (documento→fatura→item→lançamento→auditoria) |
| **Risco** | Baixo |
| **Ordem de execução** | Fase 4 |
| **Regra de parada** | Fechar os nomes definitivos dos eventos antes de codificar — não decidir nomenclatura durante a implementação sem registro |

---

## D17 — CLI

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Seguir convenção existente (`processar`, `conciliacao_importar`/`conciliacao_executar`); nomes definitivos em aberto |
| **Evidência existente no código** | `core/cli.py` — nenhum comando de cartão hoje |
| **Componente existente reaproveitado** | Estrutura de comandos Typer/Click já usada no arquivo |
| **Componente a alterar** | Nenhum comando existente |
| **Componente novo** | Comandos novos (nomes a fechar) |
| **Migration** | Não |
| **Testes** | Comando importa fatura corretamente; comando lista cartões/faturas |
| **Dependências** | D1–D8 |
| **Critério de aceite** | Comandos seguem o mesmo padrão de saída (CSV/JSON Lines) já usado pelos comandos existentes (Emenda E-10 do ADR 004) |
| **Risco** | Baixo |
| **Ordem de execução** | Fase 4 |
| **Regra de parada** | Não introduzir convenção de CLI divergente da já existente sem justificativa registrada |

---

## D18 — GnuCash

| Campo | Conteúdo |
|---|---|
| **Decisão aprovada** | Sem alteração no exportador; conta de Passivo do cartão exportada como qualquer `ContaContabil` |
| **Evidência existente no código** | `core/adapters/csv_exporter.py`; `ContaContabil.guid_gnucash` já existe |
| **Componente existente reaproveitado** | Exportador integralmente, sem alteração |
| **Componente a alterar** | Nenhum |
| **Componente novo** | Nenhum |
| **Migration** | Não |
| **Testes** | Exportação de uma conta de cartão resulta em conta de Passivo no arquivo gerado, não confundida com conta bancária |
| **Dependências** | D6 |
| **Critério de aceite** | Teste específico de mapeamento de tipo (Passivo) na exportação |
| **Risco** | Baixo |
| **Ordem de execução** | Fase 7 |
| **Regra de parada** | Se o teste revelar necessidade de alterar o exportador, isso contradiz a decisão D18 aprovada — parar e reabrir a decisão, não alterar o exportador silenciosamente |

---

## Itens transversais (não são decisões D, mas fazem parte da execução)

### Fase 0 — Migration

| Campo | Conteúdo |
|---|---|
| **Escopo** | Tabelas novas para `CartaoCredito`, `FaturaCartao`, `CompraCartao`; possível ajuste em `Lancamento` para D14 |
| **Evidência existente** | Schema atual é uma única migration (`f43b99e177a7_schema_inicial`) — esta seria a primeira migration incremental real do projeto |
| **Testes** | Sequência upgrade → downgrade → upgrade, conforme exigido para qualquer migration no projeto; teste em banco limpo |
| **Dependências** | D1–D4 fechados quanto à estrutura de campos |
| **Critério de aceite** | Migration reversível sem perda de dados em banco de teste |
| **Risco** | Alto simbolicamente — primeira migration incremental do projeto, merece revisão própria, independente do cartão |
| **Ordem de execução** | Antes da Fase 1 |
| **Regra de parada** | Não avançar para Fase 1 sem a migration testada em upgrade/downgrade |

### Fase 2 — Parser PDF/OCR

| Campo | Conteúdo |
|---|---|
| **Escopo** | Parser de fatura PDF (texto) reaproveitando `pdfplumber`; extensão de `OCRPlugin`/`SpikeOCR` para campos de fatura; identificação de emissor; registro em `ParserFactory` |
| **Evidência existente** | `core/parsers/detector.py` já detecta `PDF_TEXTO`/`PDF_IMAGEM`; `ParserFactory` não registra nenhum dos dois hoje; `OCRPlugin` extrai só CNPJ/valor genéricos |
| **Testes** | Detecção correta de fatura vs. outro PDF; extração de todos os campos de `CompraCartao`; threshold de confiança do OCR (**AINDA NÃO DEFINIDO** — decidir antes de codificar) |
| **Dependências** | D1, D4 (estrutura de `CompraCartao` a preencher) |
| **Critério de aceite** | Fatura de teste (texto e imagem) extraída corretamente até o nível de item |
| **Risco** | Médio–Alto — é o componente com maior incerteza de qualidade de extração; itens mal extraídos devem cair em revisão humana, não gerar lançamento automático incorreto |
| **Ordem de execução** | Pode iniciar em paralelo à Fase 1, independente de D9/D10/D12 |
| **Regra de parada** | Não conectar o parser ao pipeline real (`ProcessarDocumentoUseCase`) sem D5 (validação de fechamento) implementada — evita lançamentos gerados a partir de fatura mal fechada |

### Fase 8 — Testes completos + regressão total

| Campo | Conteúdo |
|---|---|
| **Escopo** | Suíte completa (detecção, extração, contabilidade, conta, idempotência, conciliação, auditoria) + regressão de toda a suíte existente do projeto (668 testes na última medição conhecida) |
| **Testes** | Todos os critérios de aceite de D1–D18 acima, mais os testes negativos explicitamente exigidos (D8, D12, D15) |
| **Dependências** | Todas as fases anteriores |
| **Critério de aceite** | 100% dos testes novos passando + zero regressão na suíte existente |
| **Risco** | Alto se a regressão não for executada de forma completa — é o único ponto de checagem final antes do PR |
| **Ordem de execução** | Última fase antes do PR |
| **Regra de parada** | Nenhum PR é aberto com testes de regressão pendentes, mesmo que os testes novos de cartão estejam 100% passando |

---

## Resumo de bloqueios de codificação (ambiguidades do ADR que precisam de decisão antes do código, não durante)

| Item | Ambiguidade | Bloqueia |
|---|---|---|
| D2/D6 | Chave de identidade natural do `CartaoCredito` | Codificação de D2 e D6 |
| D3/D5 | Tolerância numérica de fechamento de fatura | Codificação de D5 |
| D9/D10 | Regra de identificação de linha de IOF/juros/multa/encargo na extração | Codificação da Fase 2 para esses tipos específicos |
| D14 | Mecanismo técnico exato de propagação do FITID (novo campo vs. lookup via `documento_id`) | Codificação de D14 |
| D16/D17 | Nomes definitivos de eventos e comandos | Codificação de D16/D17 (a estrutura pode ser codificada, os nomes não) |
| Fase 2 | Campos exatos e threshold de confiança do OCR | Codificação da Fase 2 |

Estes seis pontos devem ser resolvidos — por decisão técnica simples ou por
retorno rápido à Direção — antes de iniciar a codificação dos itens
correspondentes. Não são bloqueadores do ADR como um todo, apenas de
partes específicas da execução.

---

**Regra de parada desta etapa.** Esta matriz é o plano de execução — não
inicia nenhuma fase. Nenhum código, migration, entidade, parser, OCR,
`LancamentoService`, FITID, motor de conciliação, CLI ou teste foi criado.
`main` intocado. A autorização para iniciar a Fase 0 (migration) é decisão
separada e explícita da Direção.

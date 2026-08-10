# Deliberação Complementar — Gate de Implementação ADR 010

**Status:** Fechamento de B1–B3 (decisão técnica de engenharia, escopo não
contábil) · B4–B6 associados formalmente às fases correspondentes, não
resolvidos nesta deliberação.
**Escopo:** exclusivamente os 6 bloqueios de codificação listados na
Matriz de Prontidão para Implementação — ADR 010. Nenhuma decisão
arquitetural ou contábil já fechada (D1–D18) é reaberta aqui.

Nenhum código, migration, entidade ou teste foi criado para produzir esta
deliberação.

---

## B1 — Chave de identidade natural do `CartaoCredito` (bloqueava D2/D6)

**FECHADO.** Chave: `(emissor, final_do_número_mascarado, titular)`.

**Fundamentação:** o final do número isoladamente não é único entre
cartões distintos do mesmo emissor; o emissor isoladamente não distingue
cartões do mesmo banco. A combinação dos três campos é suficiente para
identidade estável entre faturas de meses diferentes do mesmo cartão, sem
depender do número completo do cartão — que **nunca deve ser armazenado**,
consistente com a regra de segurança do projeto (Seção 24: nunca expor
dados sensíveis desnecessários).

**Critério de aceite:** teste de idempotência de `CartaoCredito` usa essa
chave composta; duas faturas do mesmo cartão em meses diferentes resolvem
para a mesma entidade; cartões de emissores diferentes com o mesmo final
de número resolvem para entidades distintas.

**Impacto:** desbloqueia a codificação de D2 e D6.

---

## B2 — Tolerância numérica de fechamento de fatura (bloqueava D3/D5)

**FECHADO.** Tolerância de **R$ 0,01 por item** (erro de arredondamento
individual) e **R$ 0,05 agregados por fatura** (soma de arredondamentos).
Acima disso, a fatura é classificada como divergente e vai para revisão
humana — nunca lançada automaticamente.

**Fundamentação:** o projeto já estabelece um valor de tolerância análogo
em `core/rule_engine/motor_conciliacao.py`
(`ToleranciasConciliacao.valor = R$0,10`, usado na comparação
transação-bancária × lançamento). O valor aqui é propositalmente menor
porque a soma de itens de uma fatura tem menos fontes de arredondamento
independentes do que a comparação banco×contabilidade — usar o mesmo valor
(R$0,10) mascararia divergências reais de extração, não apenas
arredondamento.

**Critério de aceite:** teste de fechamento exato passa; teste com
diferença de R$0,03 agregados passa (dentro da tolerância); teste com
diferença de R$0,10 agregados falha e gera item de revisão.

**Impacto:** desbloqueia a codificação de D5 (e a estrutura de D3 já estava
codificável, só a validação dependia disso).

---

## B3 — Regra de identificação de linha de IOF/juros/multa/encargo na extração (bloqueava Fase 2 para esses tipos)

**FECHADO — estratégia, não lista exaustiva.** Classificação por
correspondência de palavra-chave (case-insensitive) na descrição do item
extraído (ex.: "IOF", "JUROS", "MULTA", "ENCARGO", "ANUIDADE" e variações
usuais dos emissores), análogo ao padrão já usado em
`core/parsers/csv/nubank.py` para reconhecimento textual. **Sem
correspondência clara, o item é classificado como compra comum com
confiança reduzida**, sujeito a revisão humana conforme o princípio já
adotado no projeto (regra determinística com fallback de revisão, não
bloqueio duro nem inferência silenciosa).

**Fundamentação:** evita inventar uma lista fechada de termos por emissor
sem evidência de quais faturas reais serão processadas; a estratégia é
extensível (novos termos adicionados conforme faturas reais forem
processadas) sem exigir nova decisão arquitetural a cada emissor novo.

**Critério de aceite:** teste com item de descrição inequívoca (ex.: "IOF
OPERACAO EXTERIOR") classifica corretamente; teste com item ambíguo cai em
confiança reduzida e gera revisão, não classificação automática errada.

**Impacto:** desbloqueia a codificação da Fase 2 especificamente para os
tipos IOF/juros/multa/encargo — os demais campos da Fase 2 (estabelecimento,
valor, data, parcela) não dependiam deste bloqueio.

---

## B4 — Mecanismo técnico de propagação do FITID (associado à Fase 5)

**NÃO FECHADO nesta deliberação — associação formal apenas.**

**Fase:** Fase 5 (correção do FITID, D14).

**O que precisa ser decidido nessa fase, não antes:** se a correção
adiciona um campo novo em `Lancamento` (ex.: `numero_documento_origem`,
replicando o nome já esperado por `MotorConciliacao`) ou se resolve via
lookup em tempo de conciliação através de `Lancamento.documento_id →
Documento.numero_documento`, sem alterar o schema de `Lancamento`.

**Por que não fechar agora:** a escolha tem implicação de migration (se
for campo novo) que só faz sentido avaliar junto com o restante do
trabalho da Fase 5, não isoladamente nesta deliberação de gate. Fechar
agora seria decidir um detalhe de implementação sem o contexto completo da
tarefa que o usa.

---

## B5 — Nomes definitivos de eventos e comandos CLI (associado à Fase 4)

**NÃO FECHADO nesta deliberação — associação formal apenas.**

**Fase:** Fase 4 (idempotência + auditoria D16 + CLI D17).

**O que precisa ser decidido nessa fase, não antes:** nomenclatura final
dos três eventos de auditoria (esboço atual: `FaturaCartaoRecebida`,
`FaturaCartaoClassificada`, `PagamentoCartaoIdentificado`) e dos comandos
CLI novos, seguindo a convenção já usada em `core/cli.py`.

**Por que não fechar agora:** nomenclatura de eventos/CLI normalmente se
beneficia de revisão em conjunto com o código real da Fase 4 (payload dos
eventos, assinatura dos comandos), não isoladamente aqui.

---

## B6 — Campos exatos e threshold de confiança do OCR (associado à Fase 2)

**NÃO FECHADO nesta deliberação — associação formal apenas.**

**Fase:** Fase 2 (parser PDF/OCR).

**O que precisa ser decidido nessa fase, não antes:** quais campos além
dos já genéricos (`cnpj_emitente`, `valor_total`) o `OCRPlugin` precisa
extrair para popular `CompraCartao`, e o threshold de confiança mínimo
abaixo do qual um item extraído por OCR (não por texto direto) é enviado
para revisão humana em vez de lançamento automático.

**Por que não fechar agora:** o threshold correto depende de testar contra
faturas reais (texto vs. imagem) durante a própria Fase 2 — fixar um
número agora, sem essa evidência, seria inventar um detalhe de
implementação sem base, o que a instrução do projeto veda explicitamente.

---

## Resumo

| Bloqueio | Status | Fase associada |
|---|---|---|
| B1 — Chave de identidade do cartão | **FECHADO** | Desbloqueia D2/D6 (Fase 1) |
| B2 — Tolerância de fechamento | **FECHADO** | Desbloqueia D5 (Fase 1) |
| B3 — Regra de identificação de linha IOF/juros/multa/encargo | **FECHADO** | Desbloqueia parte da Fase 2 |
| B4 — Mecanismo de propagação do FITID | Associado, não fechado | Fase 5 |
| B5 — Nomes de eventos/CLI | Associado, não fechado | Fase 4 |
| B6 — Campos e threshold do OCR | Associado, não fechado | Fase 2 |

---

**Regra de parada aplicada.** Nenhum código, migration, entidade, parser,
OCR, `LancamentoService`, FITID, motor de conciliação, CLI ou teste foi
criado ou alterado. `main` intocado. B1–B3 fechados nesta deliberação são
decisões de engenharia dentro do escopo já aprovado pelo ADR 010 — não
alteram nenhuma decisão D1–D18 nem reabrem D9/D10/D12/D19. Aguardando
autorização explícita para iniciar a Fase 0 (migration).

# Pauta de Deliberação Residual — Gate 0 (PREENCHIDO)

**Natureza:** pauta deliberativa, deliberação concluída nesta data.
Complementa `docs/caderneta_pauta_deliberacao_gate0_v2.docx` (D1-D7, B1,
B2, OF) e `docs/adr/deliberacao-d2-d3-gate0-pos-cartao.md` — não os
substitui. Cobre os itens que a revalidação de Gate 0 (pós D2/D3/D5,
commit `8716fc7`) encontrou pendentes ou com evidência insuficiente.

**Data da deliberação:** 2026-08-18
**Decisor:** Camilo (Proprietário do Produto)
**Branch:** `feature/cartao-credito`, HEAD `8716fc7`

---

## Como usar este documento

Para cada item, três classificações possíveis — não mutuamente
redutíveis a uma única regra geral, porque a natureza de cada pendência
é diferente:

- **BLOQUEADOR DE PROMOÇÃO:** impede o fast-forward `feature/cartao-
  credito → main` até resolução.
- **PENDÊNCIA PÓS-MERGE:** registrada formalmente, não impede o merge,
  mas fica com prazo/responsável definido para resolução após.
- **DEPENDÊNCIA EXTERNA — SÓ REGISTRO:** o item depende de uma pessoa,
  papel ou evento fora do controle da equipe técnica (Contador CRC,
  dado real de cliente, Especialista em Controles); a única ação
  possível agora é registrar formalmente a dependência, não resolvê-la.

---

## Grupo A — equipe pode produzir evidência

### D4 — Procedimento de backup/recuperação documentado

**Contexto (docx D4, original):** procedimento de cópia de segurança do
banco de dados e recuperação em caso de falha, responsabilidade
operacional do ambiente de execução, não do código do sistema.
**Proposta original da equipe:** documentar procedimento mínimo — cópia
diária, retenção de 30 dias, teste de recuperação documentado.
**Estado nesta verificação:** nenhum artefato novo encontrado além do
registro da própria pendência nos documentos de governança já
existentes.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA:** ☒ ☐ ☐
**Responsável:** Infra / Proprietário do Produto
**Decisão:** BLOQUEADOR DE PROMOÇÃO
**Observações:** Documentação de backup/recuperação é requisito mínimo
de governança operacional para qualquer sistema em produção,
especialmente sistema financeiro. A equipe pode produzir este artefato
internamente — não depende de terceiros. Deve ser entregue antes do
merge.

---

### D6 — Modelo de IA para sugestão de classificação (benchmark)

**Contexto (docx D6, original):** sistema usa modelo multilíngue leve
(MiniLM); plano original especificava modelo especializado em pt-BR;
nenhuma comparação formal feita com dados reais de lançamentos.
**Proposta original da equipe:** usar o modelo atual em v1.0.0, fazer
comparação formal depois de ter dados reais de uso — o modelo é
trocável sem alterar o resto do sistema.
**Estado nesta verificação:** nenhuma comparação formal encontrada;
`ai/embeddings/sentence_transformer_provider.py` continua usando o
modelo multilíngue leve.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA:** ☐ ☒ ☐
**Responsável:** Equipe técnica + Contador CRC (avaliação de qualidade)
**Decisão:** PENDÊNCIA PÓS-MERGE
**Observações:** O modelo atual é funcional e substituível sem impacto
arquitetural. O benchmark formal com dados reais é uma melhoria
contínua, não um impeditivo para entrega. Prazo: 30 dias após merge. O
Contador CRC participa da avaliação de qualidade, não da execução.

---

### D7 — Testes automáticos de propriedades matemáticas (Hypothesis)

**Contexto (docx D7, original):** garantias como idempotência de
importação e unicidade de conciliação, verificáveis por teste de
propriedade em vez de cenário fixo; ferramenta instalada, não usada.
**Proposta original da equipe:** não implementar antes de v0.999 —
cenários críticos já cobertos pelos testes existentes; implementar
depois do congelamento.
**Estado nesta verificação, confirmado agora:** `hypothesis>=6.100.0`
está em `pyproject.toml` como dependência declarada; `grep -rl "import
hypothesis" tests/` não retorna nenhum arquivo — nenhum teste de
propriedade escrito.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA:** ☐ ☒ ☐
**Responsável:** Equipe técnica
**Decisão:** PENDÊNCIA PÓS-MERGE
**Observações:** A decisão original já previa implementação pós-v0.999.
Os testes críticos existentes cobrem os cenários principais. O
Hypothesis está instalado; a implementação é um aprimoramento da suíte
de testes, não um bloqueador. Prazo: 45 dias após merge.

---

### B3 — Validação da classificação de tipo de item contra fatura real (cartão)

**Contexto:** ADR 010 (`docs/adr/010-fatura-cartao-credito.md`, linha
~204) registra explicitamente: "B3 (classificação de tipo de item) já
está registrado como não validado contra fatura real, com a confiança
sub-threshold como única salvaguarda contra lançamento automático
incorreto." Depende de dado real de fatura de cartão, não disponível no
repositório nem em ambiente de teste.
**Estado nesta verificação:** sem mudança — depende de disponibilidade
de fatura real autorizada pelo titular dos dados, que a equipe técnica
não controla.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA:** ☐ ☐ ☒
**Responsável:** Equipe técnica (execução) + Proprietário do Produto
(autorização de uso de dado real)
**Decisão:** DEPENDÊNCIA EXTERNA — SÓ REGISTRO
**Observações:** A equipe não controla a disponibilidade de fatura real
autorizada. O registro formal da dependência é a única ação possível
agora. A validação será executada quando o dado se tornar disponível.
Não bloqueia a promoção.

---

## Grupo B — depende de evidência/decisão externa

### D12 — Competência de parcelas: decisão registrada, evidência externa insuficiente

**Contexto:** ADR 010, "Matriz final consolidada de decisões" (presente
desde o commit inicial do ADR, `b909ed8`, anterior a toda a
implementação de cartão): `D12 — APROVADO (Alternativa C)` —
reconhecimento integral na aquisição, parcelamento como metadado,
Alternativa B (reconhecimento por parcela) rejeitada. O mesmo ADR
declara: "Houve parecer contábil específico para D9, D10 e D12,
registrado formalmente como suporte a essas três decisões."

**O que não há, nos artefatos do repositório:** nenhum documento
externo ao ADR (parecer assinado, identificação do Contador CRC
responsável, data do parecer) comprovando esse parecer contábil. A
sessão anterior que produziu `docs/adr/deliberacao-pos-fase6.md`
(commit `c3a8036`, posterior ao ADR010) já registrou explicitamente essa
mesma lacuna — "sem confirmação de que o parecer ocorreu" — mesmo já
tendo acesso ao texto atual do ADR010. Esta verificação não encontrou
nenhum artefato novo que resolva essa lacuna.

**Distinção que este item exige:** a decisão de escopo (Alternativa C)
está registrada e é uma decisão técnica/arquitetural fechada,
independente de o parecer contábil ter ou não documentação externa. O
que falta não é decidir de novo — é decidir se a **ausência de
evidência externa do parecer** é aceitável para promoção, ou se exige
comprovação documental antes.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA — SÓ
REGISTRO:** ☐ ☒ ☐
**Responsável:** Contador CRC (fornecer evidência, se existir) +
Proprietário do Produto (decidir se a ausência é aceitável)
**Decisão:** PENDÊNCIA PÓS-MERGE
**Observações:** A decisão de escopo (Alternativa C) está formalmente
registrada no ADR 010 e já foi implementada. A falta de evidência
externa do parecer contábil não invalida a decisão técnica, mas é uma
lacuna de rastreabilidade. O Proprietário do Produto deve buscar o
parecer assinado ou, na impossibilidade, documentar formalmente que a
decisão foi tomada com base na melhor informação disponível e com
validação interna. Prazo: 15 dias após merge para registrar o
posicionamento final.

---

### D19 — Exigência de parecer CRC: registro existente, evidência externa insuficiente

**Contexto:** ADR 010 (seção "Requisito externo/CRC (D19)"): "D19 —
APROVADO como registro de suporte, não como exigência geral" — o mesmo
ADR reconhece explicitamente que "não há evidência, nos artefatos de
governança disponíveis..., de exigência formal geral de validação do
Contador CRC para todo o ADR", e que essa constatação "não é
transformada em requisito geral por esta consolidação — conforme
instrução explícita da Direção."

**Nuance:** D19 não é, em si, uma decisão de conteúdo contábil (por
isso o próprio ADR010 não o conta como uma das 18 decisões de escopo) —
é um registro sobre a **proveniência** das decisões D9/D10/D12. A mesma
lacuna de evidência externa de D12 se aplica aqui, pela mesma razão.

**Classificação — BLOQUEADOR / PÓS-MERGE / DEPENDÊNCIA EXTERNA — SÓ
REGISTRO:** ☐ ☒ ☐
**Responsável:** Proprietário do Produto
**Decisão:** PENDÊNCIA PÓS-MERGE
**Observações:** Vinculado à mesma lacuna de D12. Não é uma decisão de
conteúdo, mas de proveniência. Como D12 foi classificado como
PENDÊNCIA PÓS-MERGE, D19 segue a mesma classificação por consistência.
O Proprietário do Produto deve documentar a origem das decisões
contábeis ou confirmar a ausência de parecer formal com a devida
justificativa.

---

## Grupo C — débitos arquiteturais fora do Gate 0 (referência, não deliberados aqui)

Já registrados em `docs/adr/dt-cc-01-r1-debitos-remanescentes.md`,
tratados como fora do escopo desta pauta:

- **R1** — `CartaoCreditoORM.conta_codigo` sem FK.
- **R2** — comando `dry-run` roda sem enforcement de FK.
- **R3** — `criar_tabelas()` (`create_all()`) em vez de Alembic no
  bootstrap real do CLI.

---

## Resumo (após deliberação)

| Item | Classificação | Responsável | Decisão |
|---|---|---|---|
| D4 — Backup/recuperação | **BLOQUEADOR** | Infra / PO | Documentar procedimento mínimo antes do merge |
| D6 — Modelo de embedding | **PÓS-MERGE** | Técnica + CRC | Benchmark em até 30 dias após merge |
| D7 — Testes de propriedade | **PÓS-MERGE** | Técnica | Implementar em até 45 dias após merge |
| B3 — Validação contra fatura real | **DEP. EXTERNA** | Técnica + PO | Aguardar disponibilidade de dados; registrar dependência |
| D12 — Competência de parcelas (evidência) | **PÓS-MERGE** | CRC + PO | Buscar/registrar evidência em até 15 dias após merge |
| D19 — Exigência de parecer CRC (evidência) | **PÓS-MERGE** | PO | Documentar proveniência em até 15 dias após merge |

## Efeito sobre o Gate

| Item | Status |
|---|---|
| **BLOQUEADORES DE PROMOÇÃO** | **1** (D4) |
| **PENDÊNCIAS PÓS-MERGE** | 4 (D6, D7, D12, D19) |
| **DEPENDÊNCIAS EXTERNAS** | 1 (B3) |

**Decisão final:** Gate 0 permanece **ABERTO** até a resolução de D4
(documentação de backup/recuperação). Uma vez resolvido o bloqueador, o
fast-forward `feature/cartao-credito → main` fica **AUTORIZADO**, com
as pendências pós-merge devidamente registradas e monitoradas conforme
prazos estabelecidos.

**Próximos passos:**
1. Infraestrutura documenta procedimento de backup/recuperação (D4) —
   prazo: 7 dias.
2. Após entrega de D4, realizar o merge para `main`.
3. Monitorar entregas das pendências pós-merge conforme prazos.

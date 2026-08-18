# ADR 004 — Emendas E-09, E-10, E-11 e E-12 aprovadas pelo Comitê

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe multidisciplinar + Comitê de Avaliação Externa

---

## Contexto

Após análise externa da proposta de 10 etapas, o comitê aprovou o plano com
três emendas obrigatórias antes do início da execução.

---

## Emenda E-09 — Tax Core dentro da Etapa 4

**Problema identificado:** O Motor Contábil (Etapa 4) estava incompleto sem
apuração tributária. ICMS, PIS e COFINS são determinísticos — não pertencem à
IA nem a etapas futuras.

**Decisão:** `core/rule_engine/tax_engine.py` faz parte da Etapa 4.
Implementa apuração de tributos a partir dos campos fiscais da NF-e (CFOP,
CST, alíquotas) usando apenas regras e aritmética. Zero dependência de IA.

**Escopo mínimo:**
- Cálculo de ICMS por CST (tributado integral, redução de base, isenção,
  substituição tributária)
- Cálculo de PIS/COFINS por regime (Lucro Real cumulativo/não-cumulativo,
  Lucro Presumido)
- Apuração de créditos vs. débitos tributários
- Geração de splits contábeis específicos para tributos (contas de ICMS a
  recuperar, PIS/COFINS a recuperar)

---

## Emenda E-10 — CLI First: saída CSV desde a Etapa 4

**Problema identificado:** O contador só veria valor real na Etapa 6
(interface web). Com 10 sprints lineares, isso pode inviabilizar o projeto.

**Decisão:** A Etapa 4 produz saída em CSV ou JSON Lines consumível pelo
contador *antes* da interface web existir. A CLI (Typer) é o primeiro frontend
do sistema — não um detalhe de UX, mas um requisito de negócio.

**Fluxo da Etapa 4:**
```
documento → pipeline → lançamentos gerados → CSV auditado → contador revisa
```

O contador importa o CSV manualmente no GnuCash. A aprovação é registrada via
CLI (`caderneta importar`). A interface web da Etapa 6 é uma melhoria de
experiência, não um prerequisito para o primeiro valor de negócio.

---

## Emenda E-11 — Spike de OCR paralela a partir da Etapa 1

**Problema identificado:** Se o Arquiteto de IA esperar a Etapa 7 para
começar a trabalhar com OCR, o time perde domínio da ferramenta e a Etapa 7
se torna um gargalo.

**Decisão:** Uma spike (prova de conceito técnica) de PaddleOCR é autorizada
em container separado, paralela ao desenvolvimento do Core, a partir da
Etapa 1. A spike:
- Não integra ao pipeline principal
- Não bloqueia nenhuma etapa do Core
- Produz métricas de performance (tempo, acurácia em documentos brasileiros)
- Gera fixtures de teste (pares texto_extraído ↔ campos_esperados) usados na
  Etapa 3 como "Ground Truth Dataset"

O resultado da spike é um relatório técnico e um conjunto de fixtures — não
código de produção.

---

## Emenda E-12 — Conclusão fora de ordem: Etapa 9 (GnuCash) antes das Etapas 6–8

**Data da emenda:** 2026-08 (posterior às demais — registrada após o fato,
não antes)

**Problema identificado:** Seguindo a mesma lógica de valor de negócio da
Emenda E-10, o trabalho real avançou diretamente da Etapa 5 (Persistência +
Auditoria) para o aprofundamento da Etapa 4 (Motor Contábil: `LancamentoService`,
Período Contábil, Centro de Custo) e da Etapa 9 (Integração GnuCash completa:
persistência de `Lancamento`/`Documento`, status `EXPORTADO`, conciliação por
GUID) — sem completar as Etapas 6 (Interface Web), 7 (IA) e 8 (Conciliação
avançada/Open Finance).

Isso colocou o projeto em uma situação não prevista pelo ADR 007: o número de
versão (`FASE.ETAPA.REVISÃO`) assume implicitamente que etapas são concluídas
em ordem. Usar `0.9.x` sem qualificação sugeriria a um auditor externo que as
Etapas 6, 7 e 8 também estão prontas — o que é falso.

**Decisão:** O Comitê autoriza conclusão de etapas fora de ordem quando
justificada por valor de negócio direto ao contador/CRC — mesmo racional já
usado na E-10. A partir desta emenda:

1. O dígito `ETAPA` do versionamento (ADR 007) passa a refletir a **etapa de
   maior valor de negócio efetivamente entregue**, não necessariamente a
   etapa mais alta com conclusão contígua.
2. Toda vez que essa situação ocorrer, o `CHANGELOG` (ou nota equivalente no
   README) deve declarar explicitamente **quais etapas intermediárias
   permanecem pendentes**, para que a lacuna nunca fique implícita.
3. Esta emenda **não se aplica** à transição `0.x.x → 1.0.0`: homologação de
   produção continua exigindo todas as etapas revisadas e aprovação formal do
   Contador CRC, independentemente da ordem em que foram concluídas.

**Situação registrada nesta emenda (2026-08):**
`VERSAO_ATUAL = "0.9.0"` — Etapa 9 (Integração GnuCash) concluída.
**Pendentes:** Etapa 6 (Interface Web), Etapa 7 (IA), Etapa 8 (Conciliação
avançada/Open Finance).

---



| Sprint | Core (obrigatório) | Paralelo (AI/Infra) |
|--------|-------------------|---------------------|
| 0–1 | Infraestrutura + Domínio | Setup Ollama + modelos de embedding |
| 2–3 | Pipeline mock + Parsers XML/OFX/CSV | Spike PaddleOCR em PDFs reais |
| 4–5 | Motor Contábil + Tax Core + CLI | Finance Knowledge Base (estrutura) |
| 6 | Auditoria (Hash Chain) | Integrar spike OCR ao pipeline |
| 7 | Interface Web (fila de aprovação) | Avaliar Ground Truth Dataset |
| 8 | IA (Embeddings + LLM) | Refinar thresholds de confiança |
| 9–10 | Conciliação + Adaptadores | Fine-tuning e feedback loop |

**Marco de primeiro valor de negócio:** Sprint 6 — CSV com hash de
integridade gerado automaticamente para o contador.

---

## Emenda E-13 — Conclusão das Etapas 6, 7 e 8 (agosto de 2026)

**Problema identificado:** A Emenda E-12 registrou explicitamente que as Etapas 6
(Interface Web), 7 (IA como Plugin) e 8 (Conciliação Bancária) estavam pendentes
quando o projeto chegou em v0.9.0. Esta emenda registra a conclusão das três etapas.

**Etapa 6 — Interface Web (W1–W4):**
- W1: esqueleto FastAPI + `UsuarioORM`/`UsuarioRepository` + fix crítico em
  `verificar_isolamento.py` (nunca havia escaneado arquivos de fato)
- W2: login/logout com cookie de sessão + `current_authentication_id` no banco
  (vulnerabilidade de sessão encontrada em teste e corrigida antes do merge)
- W3: `POST /aprovar` e `/rejeitar` com RBAC via `PolicyEngine`; dois débitos
  técnicos do ADR 008 resolvidos (`PolicyEngine` conectado ao `Usuario`,
  `PeriodoFechadoError` efetivamente levantada)
- W4: templates HTMX (fila de aprovação visual, htmx 2.0.10 vendorizado)
- Terceiro verificador automatizado: `verificar_endpoints_auth.py`

**Etapa 7 — IA como Plugin (7.1–7.5):**
- 7.1: `EmbeddingProvider` Protocol + `EmbeddingsPlugin` + `ClassifierOrchestrator`
  (composição regras→embeddings no Orchestrator, nunca nos plugins)
- 7.2: `SentenceTransformerProvider` (paraphrase-multilingual-MiniLM-L12-v2, 384 dim,
  lazy, `_modelo_instancia` para injeção em testes — eliminou 72s da suite)
- 7.3: `HistoricoRepository` + `EmbeddingsIndexer` (histórico aprovado como base
  de candidatos; embeddings computados em batch)
- 7.4: `OCRPlugin` (adapter `SpikeOCR → ExtractionPort`) + correções Ruff em `ai/`
- 7.5: `LLMPort` Protocol + `LLMPlugin` + `FakeLLMProvider` + Orchestrator com
  terceira camada LLM (regras→embeddings→LLM→fallback)
- `confidence=1.0` reservado para regras; LLM clipado em 0.98; sem histórico →
  `precisa_revisao=True` sem fabricar sugestão

**Etapa 8 — Conciliação Bancária (8.1–8.4):**
- 8.1: `TransacaoBancaria`, `ContaBancaria`, `ConciliacaoItem`, `RelatorioConciliacao`,
  `BankStatementPort`, 7 novos `TipoEvento` de conciliação
- 8.2: `MotorConciliacao` — matching determinístico em camadas (FITID → valor+data →
  descrição → unicidade); todos os critérios de aceite do parecer cobertos
- 8.3: `OFXBankStatementAdapter` — importação idempotente com chave
  `(instituição, conta, FITID)`
- 8.4: `TransacaoBancariaRepository` + CLI `conciliacao importar/executar/listar`
- `BankStatementPort` preparado para Open Finance (adaptador real pós-v1.0.0)

**Achados relevantes durante as Etapas 6–8 (registrados como aprendizado):**
- `verificar_isolamento.py` nunca havia escaneado nenhum arquivo (bug de path)
- Logout não invalidava sessão real (Starlette SessionMiddleware é client-side)
- `PeriodoFechadoError` definida desde a Etapa 5, nunca levantada; `ProcessarDocumentoUseCase`
  não a capturava
- FastAPI 0.141.x retorna 405 quando GET e POST da mesma rota ficam em routers separados

**Decisão:** Registrar a conclusão das Etapas 6, 7 e 8. O estado atual do sistema é
v0.014.003 com 668 testes passando. A próxima etapa formal é a Etapa 9 — Pré-Homologação
(Gate 0), cujos artefatos foram produzidos em agosto de 2026:
- Matriz de Prontidão para v0.999 (31 itens, 21 conformes, 7 decisões, 2 bloqueadores)
- Pauta de Deliberação Gate 0 (7 itens de decisão + registro de Open Finance pós-v1.0.0)

`VERSAO_ATUAL` permanece `"0.9.0"` até deliberação formal do Item D2 da Pauta de
Deliberação Gate 0.

**Data:** 2026-08
**Aprovado por:** Proprietário do Produto (Camilo)

---

## Emenda E-14 — Deliberação formal do Item D2: `VERSAO_ATUAL` para `0.9.1`

**Data da emenda:** 2026-08-18

**Problema identificado:** O Item D2 da Pauta de Deliberação Gate 0
(`docs/caderneta_pauta_deliberacao_gate0_v2.docx`) registrou formalmente,
com proposta e consequências redigidas, a necessidade de atualizar
`VERSAO_ATUAL` para refletir entregas reais — sem decisão marcada. A
Emenda E-13 registrou a conclusão das Etapas 6–8 mas manteve
`VERSAO_ATUAL = "0.9.0"` explicitamente até essa deliberação formal do
D2. Desde então, a branch `feature/cartao-credito` (não mesclada em
`main`) entregou, adicionalmente: ADR 010 completo (Fases 0–6, cartão de
crédito) e DT-CC-01/plano B.2 (ADR 011), regularizado em
`docs/adr/regularizacao-governanca-adr011-dtcc01-b2.md`. Nenhuma dessas
entregas está refletida em `VERSAO_ATUAL`.

**Decisão (Item D2 — APROVADA):**

1. **Dígito `ETAPA`:** permanece `9`. Pela regra já fixada em E-12, esse
   dígito reflete "a etapa de maior valor de negócio efetivamente
   entregue", não a mais alta com conclusão contígua. Nenhuma das
   entregas deste ciclo (Etapas 6–8, cartão de crédito, DT-CC-01/B.2)
   introduz uma etapa numericamente superior a 9 no esquema de 10 etapas
   do ADR 007 — cartão de crédito, em particular, não é uma das 10
   etapas; toca Parsers, Motor Contábil, Conciliação e Integrações, sem
   superar o valor já registrado pela Etapa 9 (GnuCash).
2. **Dígito `REVISÃO`:** incrementa de `0` para `1`. Registra-se uma
   única revisão acumulada desde a declaração original de `0.9.0`,
   cobrindo em conjunto: o estado já alcançado pelas Etapas 6–8
   (Interface Web, IA como Plugin, Conciliação Bancária — E-13), as
   entregas de cartão de crédito (ADR 010, Fases 0–6) e DT-CC-01/B.2
   (ADR 011). Optou-se deliberadamente por **não fabricar** uma
   sequência histórica `0.9.1 → 0.9.2` que nunca existiu — E-13 nunca
   incrementou revisão nenhuma, permanecendo em `0.9.0` até agora.
3. **`VERSAO_ATUAL` resultante:** `"0.9.1"`.

**Pendência de aplicação em código:** esta emenda registra a decisão de
governança. `core/versao.py:20` (`VERSAO_ATUAL = "0.9.0"`) e
`pyproject.toml` (versão sincronizada, ver comentário em `versao.py`)
**não foram alterados** por esta emenda — a atualização do código é ação
separada, deliberadamente não incluída neste commit exclusivamente
documental, pendente de autorização explícita.

**Escopo não decidido por esta emenda:** o Item D3 (qualidade do código —
Ruff) é tratado em documento próprio
(`docs/adr/deliberacao-d2-d3-gate0-pos-cartao.md`), não nesta emenda.

**Data:** 2026-08-18
**Aprovado por:** Proprietário do Produto (Camilo)

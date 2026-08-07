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

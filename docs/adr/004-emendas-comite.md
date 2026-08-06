# ADR 004 — Emendas E-09, E-10 e E-11 aprovadas pelo Comitê

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

## Cronograma revisado (Sprints overlapped)

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

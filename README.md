# Caderneta v0.2 — Monorepo por Camadas de Maturidade

Plataforma modular de automação contábil.  
Organizada por **camadas de maturidade**, não por funcionalidades.

---

## Estrutura

```
caderneta-v2/
│
├── core/                    # Caderneta Core — lógica contábil (sem IA)
│   ├── domain/              # Etapa 1: Entidades, Value Objects, invariantes
│   ├── ports/               # Etapa 2: Contratos (Protocols) para plugins externos
│   ├── parsers/             # Etapa 3: Parsers determinísticos (XML, OFX, CSV)
│   ├── pipeline/            # Etapa 2: Orquestrador do fluxo
│   ├── rule_engine/         # Etapa 4: Motor contábil e regras
│   ├── audit/               # Etapa 5: Hash chain imutável
│   └── adapters/            # Etapa 9: Adaptadores de exportação (GnuCash, etc.)
│
├── ai/                      # Caderneta AI — plugins (Etapa 7+)
│   ├── embeddings/          # Sentence Transformers para normalização semântica
│   ├── llm/                 # Ollama + Qwen para desambiguação
│   ├── ocr/                 # PaddleOCR para documentos não estruturados
│   └── rag/                 # RAG sobre Finance Knowledge Base
│
├── infra/
│   ├── db/migrations/       # Schema PostgreSQL
│   └── docker/              # docker-compose.yml
│
├── docs/
│   └── adr/                 # Architecture Decision Records
│       ├── 001-separacao-core-ai.md
│       ├── 002-auditoria-hash-chain.md
│       └── 003-ia-como-plugin.md
│
└── tests/
    ├── unit/core/           # Testes do domínio e regras (meta: > 90% cobertura)
    ├── unit/ai/             # Testes dos plugins de IA
    ├── integration/         # Testes de integração end-to-end
    └── fixtures/            # Documentos anonimizados para testes
```

---

## Princípios

**1. Core nunca importa AI.**  
O `core/` funciona completamente sem modelos de linguagem, GPU ou conexão externa.  
Verificado em CI via `mypy` com `disallow_any_explicit = true` em `core.*`.

**2. AI implementa contratos do Core.**  
Os plugins em `ai/` implementam os `Protocol`s definidos em `core/ports/`.  
Trocar Ollama por vLLM = substituir uma classe, sem tocar em nenhuma regra contábil.

**3. Toda decisão importante tem um ADR.**  
Ver `docs/adr/` para entender por que cada tecnologia foi escolhida.

---

## Setup

```bash
# 1. Ambiente virtual
python -m venv .venv && source .venv/bin/activate

# 2. Instalar Core (sem IA)
pip install -e ".[core,dev]"

# 3. Banco de dados
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Rodar testes do Core (rápido, sem GPU)
pytest tests/unit/core/ -v --cov=core --cov-report=term-missing
```

---

## Etapas de desenvolvimento

| Etapa | Módulo | Status |
|-------|--------|--------|
| 0 — Fundação | Monorepo, ADRs, CI/CD | ✅ |
| 1 — Domínio | `core/domain/` | ✅ |
| 2 — Pipeline (mocks) | `core/pipeline/`, `core/ports/` | ✅ parcial |
| 3 — Parsers | `core/parsers/` | 🔜 |
| 4 — Motor Contábil | `core/rule_engine/` | ✅ parcial |
| 5 — Auditoria | `core/audit/` | ✅ |
| 6 — Interface Web | FastAPI + HTMX | 🔜 |
| 7 — IA | `ai/` | 🔜 |
| 8 — Conciliação | `core/` + OFX/Open Finance | 🔜 |
| 9 — Integrações | `core/adapters/` | 🔜 |

---

## Relação com a v0.1

O código da Fase 1 (v0.1) serve como **protótipo de referência**:

| v0.1 | v0.2 | Papel |
|------|------|-------|
| `models/documento.py` | `core/domain/entities.py` | Elevado ao domínio |
| `motores/classificador.py` | `core/rule_engine/classification_impl.py` | Reimplementado como Plugin |
| `auditoria/log.py` | `core/audit/chain.py` | Elevado com hash chain |
| `motores/parsers/` | `core/parsers/` | Migrado na Etapa 3 |
| `migrations/` | `infra/db/migrations/` | Copiado sem alteração |
| `dados/regras/` | `tests/fixtures/` | Virou fixture de teste |

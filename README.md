# Caderneta — Monorepo por Camadas de Maturidade

Plataforma modular de automação contábil com foco fiscal brasileiro (NF-e, OFX,
SPED, ICMS/PIS/COFINS, Simples Nacional/Lucro Presumido/Lucro Real).
Organizada por **camadas de maturidade**, não por funcionalidades.

**Status atual:** pré-produção (`0.x.x`) — ver [Etapas de desenvolvimento](#etapas-de-desenvolvimento).
Testes: **397 passando** · Cobertura: **~92%** · Isolamento Core/AI: verificado em CI.

---

## Estrutura

```
caderneta/
│
├── core/                         # Caderneta Core — lógica contábil (sem IA)
│   ├── domain/                   # Entidades, Value Objects, invariantes
│   ├── ports/                    # Contratos (Protocols) para plugins externos
│   ├── parsers/                  # Parsers determinísticos
│   │   ├── nfe/                  #   XML NF-e (CFOP, NCM, CST, tributos)
│   │   ├── csv/                  #   Nubank, Inter, Itaú, Bradesco, Santander
│   │   ├── ofx.py                #   Extratos OFX/QFX
│   │   ├── detector.py           #   Detecção de tipo por conteúdo
│   │   └── adapters.py           #   ParserProtocol — interface comum
│   ├── pipeline/
│   │   └── parser_factory.py     # Resolve TipoDocumento → Parser
│   ├── application/
│   │   └── use_cases/            # ProcessarDocumentoUseCase (orquestração)
│   ├── rule_engine/               # Motor Contábil
│   │   ├── classification_impl.py #   Classificação por regras determinísticas
│   │   ├── lancamento_service.py  #   Constrói/valida/persiste Lancamento
│   │   ├── tax_engine.py          #   Apuração ICMS/PIS/COFINS
│   │   └── estorno.py             #   Motor de estorno
│   ├── audit/
│   │   └── chain.py              # Hash chain imutável (dataclasses)
│   ├── infra/                    # Persistência (SQLAlchemy 2)
│   │   ├── db/                   #   Base ORM, SessionFactory, modelos
│   │   ├── repositories/         #   Documento, Lancamento, Audit, Período, Centro de Custo
│   │   └── unit_of_work.py       #   Transação única multi-repositório
│   ├── policies/                 # Regras de aprovação (PolicyEngine)
│   ├── adapters/
│   │   └── csv_exporter.py       # Exportação CSV compatível com GnuCash
│   └── cli.py                    # Interface de linha de comando (Typer)
│
├── ai/                            # Caderneta AI — plugins (ainda não implementado)
│   ├── embeddings/                # Normalização semântica de fornecedores
│   ├── llm/                       # Desambiguação de casos incertos
│   ├── ocr/                       # OCR para documentos não estruturados
│   └── rag/                       # RAG sobre base de conhecimento fiscal
│
├── shared/
│   └── identifiers.py            # empresa_id_from_string() — conversão determinística
│
├── infra/
│   ├── migrations/                # Alembic (env.py, script.py.mako, versions/)
│   ├── docker/                    # docker-compose.yml
│   └── scripts/
│       ├── verificar_isolamento.py  # CI: garante que core/ nunca importa ai/
│       └── release.py
│
├── docs/
│   └── adr/                       # Architecture Decision Records (7 ADRs)
│
└── tests/
    └── unit/core/                 # 397 testes — domínio, parsers, motor contábil, infra
```

---

## Princípios

**1. Core nunca importa AI.**
O `core/` funciona completamente sem modelos de linguagem, GPU ou conexão
externa. Verificado em CI via `infra/scripts/verificar_isolamento.py`
(análise estática de imports).

**2. AI implementa contratos do Core.**
Quando implementados, os plugins em `ai/` seguirão os `Protocol`s definidos
em `core/ports/`. Trocar um provedor de LLM por outro será substituir uma
classe, sem tocar em nenhuma regra contábil.

**3. LLMs são camada de sugestão, nunca de decisão.**
Toda classificação contábil final passa por regras determinísticas
(`core/rule_engine/`). IA, quando presente, apenas sugere — nunca decide
sozinha um lançamento.

**4. Toda decisão importante tem um ADR.**
Ver `docs/adr/` para entender por que cada tecnologia foi escolhida.

**5. Auditoria é append-only e verificável.**
Todo evento relevante do pipeline gera um registro em hash chain
(`core/audit/chain.py`, persistido via `AuditRepository`). Qualquer
adulteração é detectável via `caderneta verificar-integridade`.

---

## Setup

```bash
# 1. Ambiente virtual
python -m venv .venv && source .venv/bin/activate

# 2. Instalar Core (sem IA)
pip install -e ".[core,dev]"

# 3. Banco de dados (opcional — SQLite funciona sem Docker)
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Rodar testes
pytest tests/unit/core/ -v --cov=core --cov-report=term-missing

# 5. Verificar isolamento Core/AI
python infra/scripts/verificar_isolamento.py
```

Por padrão, a CLI usa SQLite (`dados/datalake/caderneta.db`). Para PostgreSQL,
defina `DATABASE_URL`:

```bash
export DATABASE_URL="postgresql+psycopg://user:senha@localhost:5432/caderneta"
```

---

## Uso via CLI

```bash
# Processar documentos e gerar CSV para o GnuCash
caderneta processar ./documentos/ --usuario "joao" --empresa "acme" --saida ./saida/

# Simular sem persistir nada (dry-run)
caderneta dry-run ./documentos/

# Gerenciar períodos contábeis
caderneta periodo abrir 2026 6 --empresa acme
caderneta periodo fechar 2026 6 --responsavel "gerente" --empresa acme
caderneta periodo listar --empresa acme

# Gerenciar centros de custo
caderneta centro-custo criar CC-VENDAS "Vendas" --empresa acme
caderneta centro-custo listar --empresa acme

# Consultar e conciliar lançamentos com o GnuCash
caderneta lancamentos listar --empresa acme --status exportado
caderneta lancamentos vincular-guid <id> <guid-do-gnucash> --empresa acme

# Auditoria
caderneta verificar-integridade
caderneta status
```

---

## Etapas de desenvolvimento

| Etapa | Módulo | Status |
|-------|--------|--------|
| 0 — Fundação | Monorepo, ADRs, CI (isolamento) | ✅ |
| 1 — Domínio | `core/domain/` | ✅ |
| 2 — Pipeline | `core/pipeline/`, `core/ports/`, `core/application/` | ✅ |
| 3 — Parsers | `core/parsers/` (NF-e, OFX, CSV) | ✅ |
| 4 — Motor Contábil | `core/rule_engine/` (classificação, tax engine, `LancamentoService`) | ✅ |
| 5 — Persistência | `core/infra/` (SQLAlchemy 2, repositórios, Unit of Work) | ✅ |
| 5 — Auditoria | `core/audit/` + `AuditRepository` (hash chain em banco) | ✅ |
| — Período Contábil | `PeriodoContabilRepository` + CLI `periodo` | ✅ |
| — Centro de Custo | `CentroCustoRepository` + CLI `centro-custo` | ✅ |
| 9 — Integração GnuCash | Exportação CSV + conciliação por GUID | ✅ |
| 6 — Interface Web | FastAPI + HTMX | 🔜 |
| 7 — IA | `ai/` (embeddings, LLM, OCR) | 🔜 |
| 8 — Conciliação avançada | Open Finance, motor de diferenças | 🔜 |
| Homologação | Aprovação formal do CRC | 🔜 |

> **Nota (Emenda E-12, ADR 004):** a Etapa 9 foi concluída fora de ordem —
> as Etapas 6 (Interface Web), 7 (IA) e 8 (Conciliação avançada) ainda
> estão pendentes apesar do dígito `ETAPA=9` no versionamento. Essa
> conclusão fora de sequência segue o mesmo racional de valor de negócio
> já usado na Emenda E-10 (CLI First).

---

## Testando

```bash
# Suite completa
pytest tests/unit/core/ -v

# Com cobertura
pytest tests/unit/core/ --cov=core --cov-report=term-missing

# Apenas um módulo
pytest tests/unit/core/test_lancamento_service.py -v
```

Meta de cobertura: 75% mínimo (`pyproject.toml`). Atual: ~92%.

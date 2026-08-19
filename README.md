# Caderneta — Plataforma de Automação Contábil Brasileira

Plataforma modular para automação de lançamentos contábeis com foco no mercado
fiscal brasileiro (NF-e/CFOP/CST, OFX, SPED, ICMS/PIS/COFINS,
Simples Nacional / Lucro Presumido / Lucro Real).

**Status:** pré-produção (`0.9.1`) — Gate 0 de Homologação **fechado**
(`docs/adr/gate0-fechamento-pre-tag.md`); tag `v0.999.0` ainda não criada.  
**Testes:** suíte com mais de 1000 casos (`tests/unit/`) — 1 falha ambiental
conhecida e documentada (bloqueio de rede a huggingface.co em
`tests/unit/ai/test_sentence_transformer_provider.py`), sem outras falhas
observadas. **Isolamento Core/AI/API:** verificado por script dedicado
(`infra/scripts/verificar_isolamento.py`), executado manualmente — o
repositório não possui pipeline de CI configurado (sem `.github/workflows/`).

---

## O que o sistema faz

1. **Lê** extratos OFX, notas fiscais XML, CSVs bancários (Inter, Itaú, Nubank, Bradesco, Santander) e faturas de cartão de crédito em PDF (ADR 010)
2. **Classifica** lançamentos automaticamente via regras determinísticas → embeddings semânticos → LLM como desambiguador (IA auxiliar, nunca decisor)
3. **Gera** CSV no formato GnuCash para importação manual
4. **Concilia** lançamentos aprovados contra o extrato bancário OFX, incluindo o pagamento agregado de faturas de cartão contra a conta bancária
5. **Mantém** trilha de auditoria imutável (hash chain) de todas as operações
6. **Expõe** fila de aprovação via Interface Web (FastAPI + HTMX) para aprovação/rejeição pelo contador

---

## Estrutura do monorepo

```
caderneta/
│
├── core/                          # Caderneta Core — lógica contábil (sem IA)
│   ├── domain/                    # Entidades, Value Objects, invariantes de domínio
│   ├── ports/                     # Contratos (Protocols): ClassificationPort,
│   │                              #   EmbeddingProvider, LLMPort, BankStatementPort
│   ├── parsers/                   # Parsers determinísticos
│   │   ├── nfe/                   #   XML NF-e (CFOP, NCM, CST, tributos)
│   │   ├── csv/                   #   Nubank, Inter, Itaú, Bradesco, Santander
│   │   ├── ofx.py                 #   Extratos OFX/QFX
│   │   ├── pdf/                   #   Faturas de cartão (ADR 010, ex.: Nubank)
│   │   ├── detector.py            #   Detecção de tipo por conteúdo
│   │   └── adapters.py            #   ParserProtocol — interface comum
│   ├── pipeline/
│   │   └── parser_factory.py      # Resolve TipoDocumento → Parser
│   ├── application/
│   │   └── use_cases/             # ProcessarDocumentoUseCase (orquestração);
│   │                              #   processar/gerar-lançamentos/conciliar-
│   │                              #   pagamento/persistir-conciliação de
│   │                              #   fatura de cartão (ADR 010)
│   ├── rule_engine/               # Motor Contábil
│   │   ├── classification_impl.py #   Classificação por regras determinísticas
│   │   ├── lancamento_service.py  #   Constrói/valida/persiste Lancamento
│   │   ├── motor_conciliacao.py   #   Motor de conciliação bancária (Etapa 8)
│   │   ├── tax_engine.py          #   Apuração ICMS/PIS/COFINS
│   │   └── estorno.py             #   Motor de estorno
│   ├── audit/
│   │   └── chain.py               # Hash chain imutável
│   ├── adapters/
│   │   ├── csv_exporter.py        # Exportação CSV compatível com GnuCash
│   │   └── ofx_bank_statement.py  # OFXBankStatementAdapter → BankStatementPort
│   ├── infra/                     # Persistência (SQLAlchemy 2)
│   │   ├── db/                    #   Base ORM, SessionFactory, modelos
│   │   ├── repositories/          #   Documento, Lancamento, Audit, Período,
│   │   │                          #   Centro de Custo, Usuario, TransacaoBancaria,
│   │   │                          #   CartaoCredito, ContaContabil (DT-CC-01/B.2)
│   │   └── unit_of_work.py        #   Transação única multi-repositório
│   ├── policies/                  # Regras de aprovação (PolicyEngine + RBAC)
│   └── cli.py                     # Interface de linha de comando (Typer)
│
├── ai/                            # Caderneta AI — plugins (implementados)
│   ├── embeddings/                # Classificação semântica via sentence-transformers
│   │   ├── embeddings_plugin.py   #   ClassificationPort via similaridade
│   │   ├── sentence_transformer_provider.py  # MiniLM-L12-v2 (lazy, sem GPU obrigatória)
│   │   ├── historico_repository.py           # Lançamentos aprovados como candidatos
│   │   ├── indexer.py             #   EmbeddingsIndexer — batch de embeddings
│   │   ├── orchestrator.py        #   ClassifierOrchestrator (regras→embeddings→LLM)
│   │   └── fake_provider.py       #   FakeEmbeddingProvider (somente testes)
│   ├── llm/                       # Desambiguação via LLM
│   │   ├── llm_plugin.py          #   LLMPlugin — ClassificationPort via LLM
│   │   └── fake_provider.py       #   FakeLLMProvider (somente testes)
│   └── ocr/                       # Extração de documentos não estruturados
│       ├── ocr_plugin.py          #   OCRPlugin → ExtractionPort
│       └── spike.py               #   SpikeOCR (PaddleOCR, importação lazy)
│
├── api/                           # Interface Web (FastAPI + HTMX)
│   ├── main.py                    # App factory, SessionMiddleware, StaticFiles
│   ├── dependencies.py            # get_current_user, get_session_factory
│   ├── auth/
│   │   ├── security.py            # hash_senha / verificar_senha (Argon2id)
│   │   └── session.py             # iniciar_sessao, encerrar_sessao
│   └── routers/
│       ├── auth.py                # GET+POST /login, POST /logout
│       ├── lancamentos.py         # GET /pendentes, POST /aprovar, POST /rejeitar
│       └── ui.py                  # GET /fila, GET /ui/fila/linhas (HTMX)
│
├── shared/
│   └── identifiers.py             # empresa_id_from_string() — conversão de CNPJ
│
├── infra/
│   ├── migrations/                # Alembic (env.py, versions/)
│   ├── docker/                    # docker-compose.yml
│   └── scripts/
│       ├── verificar_isolamento.py       # core/ nunca importa ai/ nem api/
│       ├── verificar_testes_hermeticos.py # testes unitários sem rede/banco real
│       └── verificar_endpoints_auth.py   # toda rota exige autenticação (execução manual — sem CI)
│
├── docs/
│   └── adr/                       # ADRs numerados (001–008, 010, 011) +
│                                  #   deliberações/registros de governança
│                                  #   complementares (24 arquivos no total)
│
└── tests/
    └── unit/                      # Suíte com mais de 1000 casos — core, ai,
                                    #   api, conciliação, cartão de crédito
```

---

## Princípios arquiteturais

**1. Core nunca importa AI nem API.**  
`core/` funciona completamente sem modelos de linguagem, GPU ou servidor web.
Verificado via `infra/scripts/verificar_isolamento.py` (análise AST de
imports), execução manual — sem pipeline de CI configurado no repositório.

**2. AI implementa contratos do Core.**  
Os plugins em `ai/` implementam os `Protocol`s definidos em `core/ports/`.
Trocar o provedor de LLM ou o modelo de embedding não altera nenhuma regra contábil.

**3. LLM é camada de sugestão, nunca de decisão.**  
Sequência de classificação: regras determinísticas → embeddings semânticos → LLM.
`confidence=1.0` é reservado exclusivamente para regras determinísticas.
Sem histórico → `precisa_revisao=True`, sem fabricar sugestão.

**4. Candidatos antes da decisão.**  
O `MotorConciliacao` produz candidatos de match antes de decidir — isso permite
distinguir `AMBIGUO` (mais de um candidato) de `SEM_MATCH` (nenhum candidato).
Matching é sempre 1-para-1: uma `TransacaoBancaria` ↔ um `Lancamento`.

**5. Toda decisão importante tem um ADR.**  
Ver `docs/adr/` para o racional de cada escolha arquitetural.

**6. Auditoria é append-only e verificável.**  
Todo evento relevante gera um registro em hash chain.
Qualquer adulteração é detectável via `caderneta verificar-integridade`.

---

## Setup

```bash
# 1. Ambiente virtual
python -m venv .venv && source .venv/bin/activate

# 2. Instalar dependências
pip install -e ".[core,dev]"          # CLI + testes
pip install -e ".[ai]"                # plugins de IA (opcional)
pip install -e ".[web]"               # Interface Web (opcional)
pip install ofxparse                  # conciliação bancária OFX

# 3. Banco de dados (SQLite funciona sem configuração)
# Para PostgreSQL:
export DATABASE_URL="postgresql+psycopg://user:senha@localhost:5432/caderneta"

# 4. Rodar testes
pytest tests/unit/ -v

# 5. Verificadores de arquitetura
python infra/scripts/verificar_isolamento.py
python infra/scripts/verificar_testes_hermeticos.py
python infra/scripts/verificar_endpoints_auth.py
```

---

## Interface Web

```bash
export CADERNETA_SECRET_KEY=$(openssl rand -hex 32)
export CADERNETA_ENV=dev
uvicorn api.main:app --host 0.0.0.0 --port 8000
# Acesse: http://localhost:8000
```

Papéis de usuário: `operador` (somente visualização) · `contador` (aprovação normal) ·
`supervisor` (alto valor + fechar período) · `admin` (configuração).

---

## CLI — comandos principais

```bash
# Pipeline principal
python -m core.cli processar documentos/julho/ --empresa 12345678000190 --usuario joao
python -m core.cli dry-run documentos/julho/ --empresa 12345678000190
python -m core.cli revisar --empresa 12345678000190
python -m core.cli importar --empresa 12345678000190

# Períodos contábeis
python -m core.cli periodo listar --empresa 12345678000190
python -m core.cli periodo abrir  --empresa 12345678000190 --ano 2026 --mes 7
python -m core.cli periodo fechar --empresa 12345678000190 --ano 2026 --mes 7

# Lançamentos
python -m core.cli lancamentos listar --empresa 12345678000190 --status pendente

# Conciliação bancária (Etapa 8)
python -m core.cli conciliacao importar extrato.ofx --empresa 12345678000190
python -m core.cli conciliacao executar --empresa 12345678000190 --periodo 2026-07
python -m core.cli conciliacao listar   --empresa 12345678000190 --periodo 2026-07

# Auditoria
python -m core.cli verificar-integridade --empresa 12345678000190
python -m core.cli status --empresa 12345678000190

# Cartão de crédito (ADR 010)
python -m core.cli cartao importar fatura.pdf --empresa 12345678000190 \
    --emissor Nubank --final 1234 --titular "João Silva" --conta 2.1.05.001
python -m core.cli cartao listar --empresa 12345678000190
python -m core.cli cartao gerar-lancamentos <fatura_id> --empresa 12345678000190 \
    --conta-cartao 2.1.05.001 --conta-banco 1.1.01.001 --conta-compra 4.1.01.001
python -m core.cli cartao conciliar-pagamento <fatura_id> --empresa 12345678000190 \
    --periodo 2026-07
```

---

## Etapas de desenvolvimento

| Etapa | Módulo | Status |
|---|---|---|
| 0 — Fundação | Monorepo, ADRs, CI | ✅ |
| 1 — Domínio | `core/domain/` | ✅ |
| 2 — Pipeline | `core/pipeline/`, `core/ports/`, `core/application/` | ✅ |
| 3 — Parsers | `core/parsers/` (NF-e, OFX, CSV × 5 bancos) | ✅ |
| 4 — Motor Contábil | `core/rule_engine/` (classificação, tax engine, `LancamentoService`) | ✅ |
| 5 — Persistência + Auditoria | `core/infra/`, `core/audit/`, hash chain em banco | ✅ |
| 9 — Integração GnuCash | Exportação CSV + conciliação por GUID | ✅ |
| **6 — Interface Web** | FastAPI + HTMX (W1–W4), RBAC, SessionMiddleware | ✅ `v0.010.000–v0.012.001` |
| **7 — IA como Plugin** | Embeddings, OCR, LLM, ClassifierOrchestrator (3 camadas) | ✅ `v0.013.000–v0.013.004` |
| **8 — Conciliação Bancária** | MotorConciliacao, OFXBankStatementAdapter, CLI conciliacao | ✅ `v0.014.000–v0.014.003` |
| **Cartão de Crédito** | Fatura PDF, `CartaoCredito`/`ContaContabil` (DT-CC-01/B.2), geração e conciliação de lançamentos (ADR 010, ADR 011) | ✅ |
| **Homologação** | Gate 0 **fechado** — ver `docs/adr/gate0-fechamento-pre-tag.md` | ✅ |

> **Nota (Emenda E-14, ADR 004):** Gate 0 de Pré-Homologação fechado em
> 2026-08-18 (`docs/adr/gate0-fechamento-pre-tag.md`) — bloqueadores de
> promoção resolvidos ou formalmente retirados da condição de bloqueio.
> Pendências pós-merge com prazo (benchmark de embedding, testes de
> propriedade, evidência externa de parecer contábil D12/D19) e uma
> dependência externa (validação de cartão contra fatura real, B3)
> permanecem monitoradas — ver `docs/adr/pauta-deliberacao-residual-gate0.md`.
> Congelamento em `v0.999.0` é deliberação separada, ainda não realizada.

---

## Verificadores de arquitetura

Scripts em `infra/scripts/`, executados manualmente (o repositório não
possui pipeline de CI configurado — sem `.github/workflows/`):

| Script | O que garante |
|---|---|
| `verificar_isolamento.py` | `core/` nunca importa `ai/` nem `api/`; `api/` nunca importa `ai/` |
| `verificar_testes_hermeticos.py` | `tests/unit/` sem acesso a rede ou banco real |
| `verificar_endpoints_auth.py` | Toda rota de `api/routers/` exige `Depends(get_current_user)`, exceto `/login`, `/logout`, `/` |

---

## Documentação

| Documento | Localização |
|---|---|
| ADRs numerados (001–008, 010, 011) | `docs/adr/` |
| Deliberações e registros de governança complementares (D2–D19, DT-CC-01, regressões corrigidas) | `docs/adr/` (não numerados, nome descritivo) |
| Fechamento formal do Gate 0 | `docs/adr/gate0-fechamento-pre-tag.md` |
| Procedimento de backup/recuperação (D4) | `docs/procedimento-backup-recuperacao.md` |
| Manual do Protótipo | `docs/caderneta_manual_prototipo_v2.docx` |
| Matriz de Prontidão v0.999 | `docs/caderneta_matriz_prontidao_v0999.docx` |
| Pauta de Deliberação Gate 0 (original) | `docs/caderneta_pauta_deliberacao_gate0_v2.docx` |

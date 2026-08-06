# ADR 006 — Convenções Arquiteturais e Regras de Importação

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe + Comitê Ampliado

---

## Contexto

Projetos crescem e perdem coerência quando convenções ficam implícitas.
Este ADR torna explícitas as regras que o CI verifica automaticamente.

## Regras de importação (verificadas pelo CI)

```
PERMITIDO                          PROIBIDO
─────────────────────────────────────────────────────
core/application → core/domain     core/* → ai/*
core/application → core/ports      ai/* → core/domain (diretamente)
core/application → core/events     core/domain → core/parsers
core/domain → (nada externo)       core/domain → core/rule_engine
core/rule_engine → core/domain     qualquer circular
core/policies → core/domain
core/policies → core/rule_engine
core/parsers → core/domain
core/audit → core/domain
core/audit → core/events
core/adapters → core/ports
ai/* → core/ports (somente)
ai/* → core/events (somente leitura)
```

## Convenções de nomenclatura

**Módulos:** snake_case. Ex: `processar_documento.py`  
**Classes de domínio:** PascalCase. Ex: `Lancamento`, `DocumentoFinanceiro`  
**Eventos:** PascalCase + sufixo descritivo. Ex: `LancamentoCriado`, `DocumentoRecebido`  
**Ports (Protocols):** PascalCase + sufixo `Port`. Ex: `ClassificationPort`, `AuditPort`  
**Use cases:** snake_case, verbo no infinitivo. Ex: `processar_documento.py`, `aprovar_lancamento.py`  
**Implementações de Port:** PascalCase + sufixo do módulo. Ex: `RegrasDeterministicasPlugin`, `RedisEventBus`

## Convenções de teste

- `tests/unit/core/` — sem I/O, sem banco, sem rede. Rodam em < 2s.
- `tests/unit/ai/` — podem usar modelos em memória. Sem GPU obrigatória.
- `tests/integration/` — requerem banco e Redis (Docker Compose).
- `tests/property/` — Hypothesis. Foco em parsers e regras fiscais.
- `tests/fixtures/` — documentos anonimizados. Nunca dados reais.

## Convenções de eventos

Todo evento herda de `BaseEvento`:
```python
@dataclass(frozen=True)
class BaseEvento:
    id: str                    # UUID v4
    timestamp: str             # ISO 8601 UTC
    versao_schema: int         # incrementar ao mudar campos
    correlacao_id: str         # propaga pelo pipeline inteiro
```

Eventos são imutáveis (`frozen=True`). Nunca alterar um evento publicado.

## Convenções de ADR

- ADRs nunca são deletados — apenas marcados como `Supersedido por ADR NNN`
- Todo ADR tem: Contexto, Decisão, Alternativas, Consequências
- Mudança de decisão = novo ADR referenciando o anterior

## Verificação automatizada

```bash
# Executado em todo PR
python infra/scripts/verificar_isolamento.py    # core não importa ai
python infra/scripts/verificar_convencoes.py    # nomenclatura e estrutura
pytest tests/unit/ --timeout=2                  # testes unitários rápidos
pytest --cov=core/domain --cov-fail-under=90   # cobertura do domínio
```

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
core/application → core/infra      core/domain → core/rule_engine
core/domain → (nada externo)       core/domain → core/infra
core/rule_engine → core/domain     qualquer circular
core/policies → core/domain
core/policies → core/rule_engine
core/parsers → core/domain
core/audit → core/domain
core/audit → core/events
core/adapters → core/ports
core/infra → core/domain
core/infra → core/audit            (AuditRepository usa EventoAuditoria/TipoEvento)
core/cli → core/infra
core/cli → core/application
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

- `tests/unit/core/` — foco em lógica de domínio e regras, sem rede externa
  nem GPU. Rodam em segundos.
  > **Divergência conhecida (pendente de decisão do Comitê):** os testes de
  > `core/infra/repositories/` e `core/infra/unit_of_work.py` usam SQLite em
  > memória real (não mockado) dentro de `tests/unit/core/`. Na prática isso
  > funciona bem — SQLite em memória é rápido e sem dependências externas —
  > mas contraria a intenção original desta convenção ("sem banco"). Duas
  > opções para o Comitê decidir: (a) mover esses testes para uma nova pasta
  > `tests/unit/infra/` com convenção própria, ou (b) atualizar esta
  > convenção para permitir banco em memória em `tests/unit/`, reservando
  > `tests/integration/` para PostgreSQL real via Docker Compose.
- `tests/unit/ai/` — podem usar modelos em memória. Sem GPU obrigatória.
- `tests/integration/` — requerem banco e Redis (Docker Compose). Diretório
  criado, ainda sem testes até a Etapa 6 (Interface Web).
- `tests/fixtures/` — documentos anonimizados. Nunca dados reais.

> **Nota:** a convenção original também citava `tests/property/` com
> Hypothesis. Esse diretório não foi criado; `hypothesis` está instalado
> como dependência de dev mas ainda não há testes property-based no
> repositório. Remover a referência ou criar o diretório é uma decisão
> pendente do Comitê.

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
python infra/scripts/verificar_isolamento.py    # core não importa ai — implementado
pytest tests/unit/core/ --cov=core --cov-report=term-missing  # 397 testes, meta 75%+
```

> **Nota:** `verificar_convencoes.py` (nomenclatura/estrutura) e
> `pytest --timeout=2` para checagem de velocidade eram citados na versão
> original deste ADR mas nunca foram implementados. A única verificação
> automatizada ativa hoje é o isolamento Core/AI. Nomenclatura e estrutura
> são revisadas manualmente em code review.

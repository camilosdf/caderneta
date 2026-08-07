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
core/application → core/ports      core/* → api/*      (ADR 008)
core/application → core/events     ai/* → core/domain (diretamente)
core/application → core/infra      ai/* → api/*         (ADR 008)
core/domain → (nada externo)       api/* → ai/*         (ADR 008)
core/rule_engine → core/domain     core/domain → core/parsers
core/policies → core/domain        core/domain → core/rule_engine
core/policies → core/rule_engine   core/domain → core/infra
core/parsers → core/domain         qualquer circular
core/audit → core/domain
core/audit → core/events
core/adapters → core/ports
core/infra → core/domain
core/infra → core/audit            (AuditRepository usa EventoAuditoria/TipoEvento)
core/cli → core/infra
core/cli → core/application
ai/* → core/ports (somente)
ai/* → core/events (somente leitura)
api/* → core/application           (ADR 008 — Interface Web)
api/* → core/domain                (ADR 008)
api/* → core/ports                 (ADR 008)
api/* → core/infra                 (ADR 008)
api/* → core/policies              (ADR 008)
api/* → core/audit                 (ADR 008/W2 — TipoEvento é vocabulário
                                     de domínio, não detalhe interno; mesmo
                                     precedente de core/infra → core/audit)
```

Verificado automaticamente por `infra/scripts/verificar_isolamento.py`
(análise estática via AST) — cobre as três direções: `core/* → ai/*`,
`core/* → api/*`, `api/* → ai/*`, `ai/* → api/*`.

> **Nota sobre `core/audit`:** apesar do nome sugerir infraestrutura,
> `core/audit/chain.py` é considerado um **módulo de domínio compartilhado**
> — define o catálogo de tipos de evento (`TipoEvento`) e a estrutura do
> evento imutável (`EventoAuditoria`), vocabulário que tanto `core/infra`
> (persistência) quanto `api/` (geração de eventos de login/logout)
> precisam conhecer. Não é "infraestrutura de auditoria" no sentido de
> implementação de persistência — isso é `core/infra/repositories/
> audit_repository.py`, que sim é infraestrutura. Essa distinção evita
> interpretações divergentes no futuro sobre o que mais poderia
> justificar um import direto de `core/audit`.

## Convenções de nomenclatura

**Módulos:** snake_case. Ex: `processar_documento.py`  
**Classes de domínio:** PascalCase. Ex: `Lancamento`, `DocumentoFinanceiro`  
**Eventos:** PascalCase + sufixo descritivo. Ex: `LancamentoCriado`, `DocumentoRecebido`  
**Ports (Protocols):** PascalCase + sufixo `Port`. Ex: `ClassificationPort`, `AuditPort`  
**Use cases:** snake_case, verbo no infinitivo. Ex: `processar_documento.py`, `aprovar_lancamento.py`  
**Implementações de Port:** PascalCase + sufixo do módulo. Ex: `RegrasDeterministicasPlugin`, `RedisEventBus`

## Convenções de teste

- `tests/unit/core/` — sem infraestrutura externa (Postgres real, Docker,
  Redis, rede, GPU). Rodam em segundos.
  > **Resolvido (2026-08):** a regra original dizia "sem banco", mas a
  > intenção sempre foi evitar dependência de **infraestrutura externa**
  > (serviços que precisam estar de pé, credenciais, rede). SQLite em
  > memória não se encaixa nesse problema: é hermético (zero dependência
  > externa, não usa sockets) e não deixa a suíte lenta — o teste mais
  > lento de toda a suíte de 397 testes leva 0.06s. A regra foi reescrita
  > para refletir o critério real, e SQLite em memória é uma exceção
  > explicitamente permitida, condicionada a ser totalmente hermético
  > (sem arquivo em disco, sem rede). Ver seção
  > "Verificação automatizada" abaixo para o mecanismo que garante isso
  > em CI — estático (import proibido) e em runtime (sockets bloqueados).
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
python infra/scripts/verificar_isolamento.py           # core/ai/api — três direções
python infra/scripts/verificar_testes_hermeticos.py    # tests/unit/ sem infra externa
pytest tests/unit/ -p no:cacheprovider                 # sockets bloqueados via pytest-socket
pytest tests/unit/core/ --cov=core --cov-report=term-missing  # 426 testes, meta 75%+
```

**Isolamento Core/AI/API** — análise estática de imports (AST). Desde a
extensão para a Interface Web (ADR 008, W1), cobre três direções:
`core/* → ai/*` proibido, `core/* → api/*` proibido, `api/* → ai/*`
proibido, `ai/* → api/*` proibido.

> **Achado corrigido durante o W1 (2026-08):** o cálculo de raiz do
> repositório em `verificar_isolamento.py` usava
> `Path(__file__).parent.parent`, que resolve para `infra/`, não a raiz do
> projeto — então `core_dir = raiz / "core"` sempre apontou para um
> caminho inexistente (`infra/core`). O script rodava "✅ verificado" sem
> nunca escanear um único arquivo, desde sua criação. Corrigido para
> `Path(__file__).resolve().parent.parent.parent`, testado com violações
> reais induzidas deliberadamente para confirmar detecção. Ao rodar a
> checagem corrigida contra o código real, nenhuma violação foi
> encontrada — a disciplina manual de não importar `ai/` em `core/` se
> manteve correta mesmo sem a rede de segurança automatizada funcionando.
> `verificar_testes_hermeticos.py` recebeu o mesmo tratamento defensivo
> (`.resolve()`) por consistência, embora sua profundidade de `.parent`
> já estivesse correta por coincidência.

**Hermeticidade de `tests/unit/`** — dois mecanismos independentes,
implementados em 2026-08 junto com a reescrita da regra "sem banco" →
"sem infraestrutura externa":

1. **Estático** (`infra/scripts/verificar_testes_hermeticos.py`): varre
   `tests/unit/*.py` e falha se encontrar import de bibliotecas de rede/infra
   externa (`psycopg`, `psycopg2`, `docker`, `redis`, `requests`, `httpx`,
   `boto3`) ou strings de conexão não-SQLite (`postgresql://`,
   `postgresql+psycopg`).
2. **Runtime** (`pytest-socket`, via `tests/unit/conftest.py`): desabilita
   toda chamada de socket de rede real durante a execução de `tests/unit/`.
   Como SQLite é local (não usa sockets), a suíte inteira passa sem
   alterações — prova automática de que já éramos herméticos antes desta
   formalização. `tests/integration/` não tem essa restrição, pois depende
   de fato de Docker Compose (Postgres, Redis).
   > **Ajuste durante o W1:** `disable_socket()` sozinho também bloqueava
   > `socket.socketpair()`, usado internamente pelo `TestClient` do
   > FastAPI/Starlette para a ponte de thread do event loop assíncrono —
   > IPC local, não infraestrutura externa. Ajustado para
   > `disable_socket(allow_unix_socket=True)`, que mantém sockets de rede
   > real (`AF_INET`/`AF_INET6`) bloqueados e libera apenas sockets Unix
   > locais (`AF_UNIX`), confirmado por teste dedicado.

> **Nota:** `verificar_convencoes.py` (nomenclatura/estrutura genérica) e
> `pytest --timeout=2` eram citados na versão original deste ADR mas nunca
> foram implementados. Nomenclatura e estrutura continuam revisadas
> manualmente em code review.

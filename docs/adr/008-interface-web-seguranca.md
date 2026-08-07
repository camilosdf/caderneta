# ADR 008 — Interface Web e Segurança do MVP

**Status:** Proposto — aguardando revisão da equipe multidisciplinar antes do W1
**Data:** 2026-08
**Decisores:** Equipe multidisciplinar (revisão pendente: Internal Controls
Specialist, Senior Accountant CRC, DevOps)

---

## Contexto

A Etapa 6 (Interface Web) nunca teve um ADR próprio — apenas uma linha
genérica ("FastAPI + HTMX, fila de aprovação") repetida em três lugares
(README, ADR 004, ADR 007), sem nenhuma decisão de segurança, autenticação
ou posicionamento arquitetural registrada.

Isso quebra o padrão que o projeto seguiu até aqui: toda decisão importante
tem um ADR *antes* da implementação (ADR 001 para `core`/`ai`, ADR 002 para
hash chain, ADR 003 para IA como plugin). Escrever a Interface Web sem essa
etapa criaria uma superfície nova — autenticação, sessões, mutação de dados
contábeis via HTTP — sem as mesmas garantias de isolamento e auditabilidade
que o resto do sistema tem.

Este ADR precede qualquer código. A implementação (W1–W4) só começa após
revisão desta proposta.

---

## Decisão

### 1. Localização do módulo — `api/`

`api/` vive na raiz do monorepo, como um **terceiro consumidor de `core/`**,
com a mesma disciplina de dependência que `ai/` já segue: só pode importar
`core/ports`, `core/application`, `core/domain` e `core/infra` — nunca o
inverso.

```
api/
├── main.py                  # FastAPI app factory
├── dependencies.py          # DI: sessão de banco, usuário atual, RBAC
├── auth/
│   ├── security.py          # hash de senha (Argon2id), verificação
│   └── session.py           # sessão via cookie assinado
├── routers/
│   ├── auth.py              # login / logout
│   └── lancamentos.py       # fila de aprovação
├── templates/                # Jinja2 + fragmentos HTMX
│   ├── base.html
│   ├── login.html
│   └── lancamentos/
│       ├── fila.html
│       └── _linha.html       # fragmento HTMX (swap parcial)
└── static/                   # htmx.min.js vendorizado, CSS mínimo
```

**Extensão da matriz de importação do ADR 006:**

```
PERMITIDO                          PROIBIDO
─────────────────────────────────────────────────────
api/ → core/application            core/* → api/*
api/ → core/domain                 ai/* → api/*
api/ → core/ports                  api/* → ai/*  (mesma disciplina do core/)
api/ → core/infra
api/ → core/policies
```

`api/` nunca importa `ai/` diretamente — se algum dia a fila de aprovação
precisar de uma sugestão de IA, isso passa por `core/ports`, igual a
qualquer outro consumidor.

### 2. FastAPI como camada de apresentação

Novo grupo opcional no `pyproject.toml`: `web` (não faz parte de `core` nem
`dev`, já que nem todo deployment precisa da interface web — mesma lógica
que já separa `core` de `ai`).

Dependências previstas: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`
(forms de login), `itsdangerous` (assinatura de cookie de sessão),
`argon2-cffi` (hash de senha).

Processo separado da CLI: `uvicorn api.main:app`. A CLI (Typer) continua
existindo e funcionando de forma independente — a interface web é aditiva,
não substitui o fluxo `caderneta processar` + CSV manual.

### 3. HTMX — sem SPA

Server-rendered HTML (Jinja2) com fragmentos trocados via HTMX. Justificativa:

- Alinhado à Emenda E-10 (CLI First) — minimizar complexidade de frontend,
  já que o CSV/CLI cobre o fluxo primário; a interface web serve para tornar
  a fila de aprovação mais rápida de usar, não é o único caminho.
- Sem build step de JS, sem `npm`, sem framework de SPA.
- `htmx.min.js` vendorizado em `api/static/` — nunca via CDN em produção
  (risco de disponibilidade e de supply-chain).

### 4. Autenticação por usuário/senha

**Achado relevante:** `core/domain/entities.py` já tem uma entidade
`Usuario` com `papel`, `pode_aprovar()`, `pode_aprovar_alto_valor()`,
`pode_fechar_periodo()`. O domínio já possui um **modelo inicial de papéis
e capacidades**, porém sua aplicação ainda não está integrada ao fluxo de
autorização do `PolicyEngine` — `avaliar_aprovacao()` recebe apenas strings
soltas (`aprovador_id: str`), sem nenhuma verificação de papel. A Interface
Web é o que consolida essa integração, conectando o modelo inicial já
existente ao mecanismo que decide aprovações.

**Este ADR não cria novos papéis de domínio.** Documenta exatamente os
quatro papéis que já existem hoje em `Usuario.papel`:

| Papel | Permissões iniciais (conforme domínio atual) |
|---|---|
| `operador` | Consulta e envio de documentos |
| `contador` | Aprovação de lançamentos dentro da sua competência (`pode_aprovar()`) |
| `supervisor` | Aprovação de alto valor e fechamento de período (`pode_aprovar_alto_valor()`, `pode_fechar_periodo()`) |
| `admin` | Administração do sistema |

> O projeto poderá introduzir perfis adicionais (por exemplo, um perfil
> exclusivamente de auditoria, com acesso somente leitura) em ADR futuro,
> caso haja necessidade. Este ADR delibera apenas sobre os quatro papéis
> já modelados no domínio — nenhum papel novo é criado aqui.

**Decisão:**
- Novo `UsuarioORM` (`core/infra/db/models.py`) com `senha_hash` — nunca
  senha em texto puro em nenhum lugar, incluindo audit log.
- Hash via **Argon2id** (`argon2-cffi`) — recomendação atual da OWASP.
  bcrypt é aceitável como fallback documentado se houver restrição
  operacional (ex.: ambiente FIPS).
- Login via formulário HTML padrão (`POST /login`), validado contra o hash.

### 5. RBAC

Reaproveita `Usuario.papel` e os métodos já existentes no domínio — não
cria um sistema de permissões novo. Quatro papéis (já implícitos no
domínio): `operador`, `contador`, `supervisor`, `admin`.

`api/dependencies.py` expõe `require_role(*papeis)` como FastAPI dependency.
Toda rota que muta dados declara explicitamente os papéis mínimos exigidos.

### 6. Sessões autenticadas

Cookie de sessão assinado (`itsdangerous` via `Starlette SessionMiddleware`),
contendo `usuario_id`, `emitido_em`, `expira_em` — **não JWT**. Justificativa:
simplicidade operacional para o estágio atual do projeto (uso interno,
single-tenant por instância); não há necessidade de token portável entre
serviços ainda.

- Expiração por inatividade: 30 minutos (configurável).
- Logout explícito invalida o cookie do lado do cliente.
- Sem tabela de sessões no banco no MVP — reavaliar se surgir necessidade de
  revogação forçada de sessões ativas (ex.: usuário desligado).

### 7. Integração obrigatória com o Audit Log

Toda mutação relevante grava evento via `AuditRepository`, dentro da mesma
`UnitOfWork` da operação — sem exceção. Novos tipos de evento necessários
em `TipoEvento` (`core/audit/chain.py`):

- `USUARIO_LOGIN`
- `USUARIO_LOGOUT`

(`LANCAMENTO_APROVADO` e `LANCAMENTO_REJEITADO` já existem no catálogo,
prontos para uso — nunca foram conectados a nenhum fluxo real até agora.)

### 8. Proibição de mutação sem autenticação

**Ampliação da proposta original, aprovada:** em vez de proteger só
endpoints de mutação, **toda rota exige autenticação**. A fila de
aprovação expõe dados financeiros reais — não há leitura "pública"
razoável neste sistema. Permitir leitura anônima criaria uma
inconsistência arquitetural frente aos perfis distintos já modelados.

**Regra:** Toda rota da Interface Web exige autenticação.

**Exceções explícitas** (única lista válida — qualquer rota fora dela
exige `Depends(...)` de autenticação):
- `/login`
- `/logout`
- `/health`
- `/ready`
- `/live`
- Documentação OpenAPI (`/docs`, `/redoc`, `/openapi.json`) — **somente**
  quando explicitamente habilitada em ambiente de desenvolvimento; nunca
  exposta em produção por padrão.

### 9. Princípio: a camada Web nunca implementa regras de autorização de negócio

A Interface Web autentica o usuário e identifica seu papel. A decisão de
**autorização** (quem pode aprovar o quê, sob quais condições) permanece
inteiramente no domínio — `Usuario`, `PolicyEngine` e os casos de uso em
`core/application/`. A camada Web não replica nem reimplementa essa lógica
em decorators ou dentro de endpoints; apenas encaminha a identidade
autenticada para o domínio decidir.

Este princípio vale independentemente de quantos papéis existirem — se um
papel novo for adicionado em ADR futuro, nenhuma rota da API deveria
precisar mudar, porque a autorização nunca esteve na camada Web.

---

## Alternativas consideradas

| Decisão tomada | Alternativa rejeitada | Por quê |
|---|---|---|
| Cookie de sessão assinado | JWT | Complexidade desnecessária para uso single-tenant interno; cookie de sessão é mais simples de revogar |
| HTMX | SPA (React/Vue) | Contraria a Emenda E-10; adiciona build step, `npm`, e uma segunda linguagem de frontend sem necessidade comprovada |
| Reaproveitar os 4 papéis já modelados em `Usuario.papel` | Criar um sistema de RBAC novo, ou ACL granular por permissão | O domínio já modela 4 papéis suficientes para o fluxo de aprovação; criar um mecanismo paralelo duplicaria modelagem existente. Granularidade fina pode ser adicionada depois sem quebrar o desenho atual |
| Usuário/senha próprio | OAuth/SSO externo | Prematuro para uma instância single-tenant; revisitar se o projeto evoluir para SaaS multi-empresa |
| Argon2id | bcrypt | Recomendação atual da OWASP; bcrypt documentado como fallback aceitável |

---

## Consequências

- Consolida no fluxo de aprovação real um modelo inicial de papéis que já
  existia no domínio, mas nunca esteve conectado ao `PolicyEngine` — sem
  retrabalho de modelagem nem criação de mecanismo paralelo.
- Cria a primeira superfície HTTP do sistema — amplia a matriz de
  importação do ADR 006 e exige atenção nova em revisão de segurança
  (CSRF em formulários POST, cabeçalhos de segurança, rate limiting de
  login — detalhar na implementação do W1/W3, não neste ADR).
- `api/` passa a ser candidato a verificação automatizada própria (ver
  abaixo), seguindo o padrão já estabelecido pelos scripts de isolamento
  e hermeticidade.

---

## Verificação automatizada (planejada para W1/W3)

Seguindo o padrão de `infra/scripts/verificar_isolamento.py` e
`verificar_testes_hermeticos.py`:

```bash
python infra/scripts/verificar_isolamento.py       # já cobre api/ → ai/ proibido
python infra/scripts/verificar_endpoints_auth.py    # novo — toda rota exige Depends(...)
```

`verificar_endpoints_auth.py` varre `api/routers/*.py` via AST e falha se
encontrar qualquer função decorada com `@router.get/post/put/delete/patch`
sem um parâmetro `Depends(...)` de autenticação — impede que alguém
esqueça de proteger uma rota nova sem que isso dependa só de code review.

**Critérios objetivos de conformidade** (verificáveis por teste automatizado
no W3, antes de qualquer rota de mutação ir ao ar):

- ✓ Nenhum endpoint protegido responde `200` sem autenticação.
- ✓ Usuário autenticado mas sem permissão (papel insuficiente) recebe `403`.
- ✓ Credenciais inválidas ou usuário inexistente resultam em `401`.
- ✓ Todo endpoint que altera estado gera um evento de auditoria
  correspondente (via `AuditRepository`, na mesma `UnitOfWork` da operação).

---

## Próximos passos

Esta proposta precisa de revisão antes do W1, especificamente do Internal
Controls Specialist (RBAC e trilha de auditoria), do Senior Accountant CRC
(se o fluxo de aprovação aqui descrito reflete o processo real de trabalho)
e do Arquiteto de Software (posicionamento de `api/` e extensão da matriz
de importação do ADR 006). Após aprovação, a sequência de implementação é:

- **W1** — esqueleto FastAPI + `api/` + extensão do ADR 006 + `UsuarioORM`/`UsuarioRepository`
- **W2** — endpoint só-leitura: listar lançamentos pendentes
- **W3** — endpoint de aprovação/rejeição + login/logout + `verificar_endpoints_auth.py`
- **W4** — templates HTMX (fila de aprovação visual)

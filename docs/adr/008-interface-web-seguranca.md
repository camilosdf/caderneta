# ADR 008 — Interface Web e Segurança do MVP

**Status:** Aceito
**Data:** 2026-08 (proposto e revisado em 2026-08; ratificado em 2026-08)
**Decisores:** Equipe multidisciplinar — Internal Controls Specialist,
Senior Accountant CRC, Arquiteto de Software. Duas rodadas de parecer
técnico incorporadas ao texto; ratificação final concedida pelo Product
Owner (Camilo).

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

Este ADR precedeu qualquer código — a implementação (W1–W4) só começa
após esta decisão estar registrada e aceita, o que ocorre com este
documento.

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
│   └── session.py           # autenticação — mecanismo definido no W1 (Seção 6)
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
(forms de login), `argon2-cffi` (hash de senha), mais **uma** dependência
de autenticação a decidir no W1 conforme Seção 6 — `itsdangerous` se
cookie assinado, ou uma biblioteca JWT (ex.: `pyjwt`) se token stateless.

Processo separado da CLI: `uvicorn api.main:app`. A CLI (Typer) continua
existindo e funcionando de forma independente — a interface web é aditiva,
não substitui o fluxo `caderneta processar` + CSV manual.

Quando a documentação OpenAPI estiver habilitada (ambiente de
desenvolvimento apenas — ver Seção 8), cada rota deve declarar os papéis
exigidos de forma visível no Swagger (ex.: `require_role='contador'`
refletido na descrição do endpoint), para facilitar testes manuais durante
o desenvolvimento.

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

### 6. Autenticação — requisito arquitetural, tecnologia não fixada

**Revisado após parecer da equipe multidisciplinar (2026-08):** a primeira
versão deste ADR fixava cookie de sessão assinado como mecanismo único.
Isso amarra uma decisão de arquitetura a um detalhe de implementação sem
necessidade — o que importa é a propriedade garantida, não a tecnologia
específica.

**Requisito arquitetural:** o mecanismo de autenticação deve fornecer:
- identidade verificável (não forjável pelo cliente);
- expiração;
- integridade criptográfica.

A implementação inicial (W1) pode usar **JWT** ou **cookie de sessão
assinado**, desde que satisfaça os três requisitos acima. Se optar por
cookie, usar flags `HttpOnly; Secure; SameSite=Strict`. Essa escolha é uma
decisão de implementação do W1, não deste ADR.

- Expiração por inatividade: 30 minutos (configurável).
- **Logout:**
  - Se a implementação usar sessão com estado no servidor: logout invalida
    imediatamente.
  - Se a implementação usar token stateless (ex.: JWT): invalidação
    imediata no logout exige mecanismo adicional (blacklist ou lista de
    revogação). Isso é **débito técnico conhecido e aceito para o MVP**,
    não bloqueante — documentar explicitamente na implementação se essa
    rota for escolhida.

**Decisão implementada no W2:** cookie de sessão assinado via Starlette
`SessionMiddleware`, `same_site=strict`, `https_only` fora de dev
(`HttpOnly`/`Secure`/`SameSite=Strict` confirmados empiricamente via
inspeção do header `Set-Cookie` em ambos os cenários, testes automatizados
em `tests/unit/api/test_auth.py::TestAtributosSegurancaCookie`).

> **Achado de segurança corrigido durante o W2 (2026-08):** a implementação
> inicial presumiu que "sessão com estado no servidor" descrevia
> corretamente o cookie assinado do Starlette — o que é **falso**.
> `SessionMiddleware` é inteiramente client-side: toda a sessão vive dentro
> do cookie assinado, sem nenhuma tabela no banco. Um teste dedicado
> comprovou que um cookie capturado antes do logout continuava
> autenticando depois do logout — exatamente o mesmo problema que este
> ADR já havia identificado como débito técnico *apenas* para o cenário
> JWT stateless, mas que na prática também afetava a implementação de
> cookie escolhida.
>
> **Correção:** o cookie assinado passou a carregar somente um
> `authentication_id` (portador de identidade, não a autorização em si).
> `UsuarioORM.current_authentication_id` guarda, no servidor, qual
> `authentication_id` está ativo para cada usuário. Toda requisição
> autenticada compara os dois valores (`UsuarioRepository.
> sessao_ativa_confere()`) — não basta a assinatura do cookie ser válida.
> Login sobrescreve o valor no servidor; logout zera. Um cookie replay
> após logout agora falha com 401, comprovado por teste dedicado
> (`test_sessao_apos_logout_nao_aceita_cookie_antigo`).
>
> **Consequência assumida deliberadamente para o MVP:** no máximo uma
> sessão autenticada por usuário. Um novo login sobrescreve
> `current_authentication_id`, revogando automaticamente qualquer sessão
> anterior do mesmo usuário — mesmo sem logout explícito (comprovado por
> `test_novo_login_revoga_sessao_anterior`). Login em outro dispositivo
> desloga o anterior; isso é aceitável e até desejável para o MVP
> (simplicidade, sem tabela de sessões), mas é uma restrição real de UX
> que a equipe deve estar ciente. Se múltiplas sessões simultâneas forem
> necessárias no futuro, substituir `current_authentication_id` por uma
> tabela `sessoes` (`id`, `usuario_id`, `authentication_id`, `created_at`,
> `expires_at`, `revogada`) — a interface pública da API não muda.

### 7. Integração obrigatória com o Audit Log

Toda mutação relevante grava evento via `AuditRepository`, dentro da mesma
`UnitOfWork` da operação — sem exceção. Além dos campos já existentes em
`EventoAuditoria`, o payload de eventos originados na Interface Web deve
incluir:

- `papel` — o papel do usuário no momento da ação (não apenas `usuario`),
  para permitir auditar futuramente se, por exemplo, uma aprovação de alto
  valor foi feita por alguém com o papel adequado no momento do fato.
- `authentication_id` — identificador da autenticação usada (ex.:
  `session_id` se sessão com estado, `jti` se JWT, ou equivalente). Nome
  genérico deliberado — não amarra o ADR à tecnologia escolhida na Seção 6.

Novos tipos de evento necessários em `TipoEvento` (`core/audit/chain.py`):

- `USUARIO_LOGIN`
- `USUARIO_LOGOUT`

(`LANCAMENTO_APROVADO` e `LANCAMENTO_REJEITADO` já existem no catálogo,
prontos para uso — nunca foram conectados a nenhum fluxo real até agora.)

**Justificativa da ação (aprovação/rejeição):**
- Aprovação rotineira (dentro da alçada normal do papel): justificativa
  **opcional**.
- Rejeição: justificativa **obrigatória**.
- Aprovação excepcional (alto valor, override de política): justificativa
  **obrigatória**.

Essa distinção evita atrito operacional em aprovações rotineiras sem
perder rastreabilidade nos casos que mais importam para auditoria.

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

**Corolário — proteção contra falsificação de identidade:** o servidor
jamais confia em `usuario_id`, `papel`, ou qualquer atributo de autorização
enviado pelo cliente (seja em body, query string, ou header manipulável).
Toda identidade usada pelo domínio vem exclusivamente do mecanismo de
autenticação (Seção 6), nunca de dados enviados pelo cliente na própria
requisição de mutação.

**Middleware único de autenticação:** um único middleware extrai a
identidade autenticada e a disponibiliza para as rotas (ex.:
`request.state.usuario`). Nenhuma rota interpreta token/cookie
individualmente — evita duplicação e inconsistência na extração de
identidade.

```
HTTP Request → Middleware de autenticação → request.state.usuario
             → Endpoint → Caso de uso → PolicyEngine (decide)
```

**Casos de uso sempre recebem identidade completa:** todo caso de uso
invocado pela API recebe `usuario_id` **e** `papel` juntos — nunca apenas
o ID. Isso permite ao `PolicyEngine` aplicar regras de alçada (ex.: valor
máximo que um `contador` pode aprovar sem escalar para `supervisor`) sem
precisar buscar o papel de volta no banco a cada chamada.

**Segregação de funções:** a verificação de conflitos de segregação (ex.:
impedir que um `contador` aprove um lançamento que ele mesmo criou) é
responsabilidade do domínio (`PolicyEngine`), não da API. A API garante
apenas que a identidade completa e correta chegue ao domínio para essa
checagem ser possível — se o domínio ainda não implementa essa checagem
hoje, isso é um débito técnico do domínio, não desta camada.

**Mapeamento de exceções de domínio para HTTP:** exceções de
autorização/validação do domínio são traduzidas para códigos HTTP na
camada Web, sem vazar detalhes internos:

| Exceção de domínio | HTTP |
|---|---|
| Não autenticado (sem identidade válida) | `401` |
| Não autorizado (autenticado, mas sem permissão) | `403` |
| `PeriodoFechadoError` (já existe em `core/rule_engine/lancamento_service.py`) | `409` |
| Lançamento não encontrado | `404` |

> **Nota:** `PeriodoFechadoError` está definida no código mas atualmente
> `LancamentoService._validar_periodo()` levanta `ValueError` genérico, não
> essa exceção específica (divergência encontrada, não corrigida por este
> ADR). Corrigir isso é pré-requisito técnico do W3, para que o
> mapeamento HTTP acima funcione como descrito.

---

## Invariantes arquiteturais

Estas invariantes mantêm a arquitetura consistente à medida que novos
endpoints forem adicionados — qualquer PR que as violar deveria ser
rejeitado em review, independentemente de quão pequena pareça a mudança:

- Nenhum endpoint chama repositórios diretamente para decidir autorização.
- Nenhum endpoint interpreta papel de usuário além de repassá-lo ao caso
  de uso — a interpretação (permitido ou não) é sempre do domínio.
- Nenhum endpoint altera estado sem gerar evento de auditoria correspondente.
- Toda autorização ocorre no domínio (`PolicyEngine`, `Usuario`, casos de uso).
- Toda identidade utilizada pelo domínio provém do middleware de
  autenticação — nunca de dados enviados pelo cliente na própria requisição.

---

## Alternativas consideradas

| Decisão tomada | Alternativa rejeitada | Por quê |
|---|---|---|
| Requisito arquitetural agnóstico (JWT **ou** cookie assinado, ambos aceitáveis) | Fixar uma tecnologia específica no ADR | Revisado após parecer da equipe: pinar a tecnologia é decisão de implementação (W1), não de arquitetura — o que importa é a propriedade garantida (identidade verificável, expiração, integridade), não o mecanismo |
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

## Verificação automatizada (obrigatória — pré-requisito do W3)

**`verificar_endpoints_auth.py` é pré-requisito obrigatório para o W3 ser
considerado completo** — nenhuma rota de mutação vai ao ar sem essa
verificação rodando em CI, conforme parecer da equipe multidisciplinar.

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
- ✓ Um usuário autenticado não consegue forjar a identidade de outro
  usuário (ex.: enviar um `usuario_id` diferente no payload e ter esse
  valor aceito) — o teste envia um `usuario_id` divergente do
  autenticado e confirma que o servidor ignora esse campo, usando apenas
  a identidade do middleware de autenticação.

---

## Próximos passos

**Ratificado (2026-08):** este ADR incorporou duas rodadas de parecer da
equipe multidisciplinar (Internal Controls Specialist, Contador CRC,
Arquiteto de Software) e foi ratificado. **Status: Aceito.** O W1 pode
começar.

**Tarefas técnicas complementares identificadas na revisão** (fora do
escopo deste ADR, mas pré-requisito para W3 funcionar como descrito):

1. Conectar `PolicyEngine.avaliar_aprovacao()` às capacidades já
   modeladas em `Usuario` (`pode_aprovar()`, `pode_aprovar_alto_valor()`,
   `pode_fechar_periodo()`) — hoje `PolicyEngine` não usa papel algum.
   Pode virar um ADR complementar ou apenas uma tarefa técnica dentro do
   W1/W3, a critério da equipe.
2. Corrigir `LancamentoService._validar_periodo()` para levantar
   `PeriodoFechadoError` (já definida, nunca usada) em vez de `ValueError`
   genérico — necessário para o mapeamento HTTP 409 da tabela acima
   funcionar como descrito.

Sequência de implementação:

- **W1** — esqueleto FastAPI + `api/` + extensão do ADR 006 + `UsuarioORM`/`UsuarioRepository`
- **W2** — endpoint só-leitura: listar lançamentos pendentes
- **W3** — endpoint de aprovação/rejeição + login/logout + `verificar_endpoints_auth.py`
- **W4** — templates HTMX (fila de aprovação visual)

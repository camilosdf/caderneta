# Caderneta — Procedimento de Backup e Recuperação (D4, Gate 0)

**Natureza:** runbook operacional, não decisão arquitetural. Resolve o
Item D4 da Pauta de Deliberação Gate 0 (classificado como BLOQUEADOR DE
PROMOÇÃO em `docs/adr/pauta-deliberacao-residual-gate0.md`).
**Data:** 2026-08-18
**Aprovado por:** Proprietário do Produto (Camilo)

---

## Escopo

Apenas o banco PostgreSQL (dados críticos: `lancamentos`, `splits`,
trilha de auditoria, e demais tabelas do schema). Redis está
provisionado (`infra/docker/docker-compose.yml`) mas hoje **não
armazena estado persistente usado pelo sistema** — a única
implementação de `EventBusPort` existente é `EventBusEmMemoria`
(`core/events/catalog.py:247-248`, "implementação em memória para
testes — sem Redis necessário"). Não requer backup enquanto esse for o
caso — ver nota de rodapé.

Ambiente de referência: `infra/docker/docker-compose.yml` — container
`caderneta_db` (imagem `pgvector/pgvector:pg16`), banco `caderneta`,
usuário `caderneta`, volume nomeado `caderneta_pgdata`.

## Backup diário — `pg_dump`

```bash
mkdir -p ./backups
docker exec caderneta_db pg_dump -U caderneta -F c -f /tmp/caderneta_$(date +%F).dump caderneta
docker cp caderneta_db:/tmp/caderneta_$(date +%F).dump ./backups/
docker exec caderneta_db rm /tmp/caderneta_$(date +%F).dump
```

Executar diariamente (cron ou agendador equivalente do ambiente de
execução).

## Retenção

30 dias. Remoção automática dos dumps mais antigos — pode ser um script
simples, por exemplo:

```bash
find ./backups -name "caderneta_*.dump" -mtime +30 -delete
```

## Teste de restore

```bash
docker exec caderneta_db createdb -U caderneta caderneta_restore_test
docker cp ./backups/caderneta_<data>.dump caderneta_db:/tmp/restore.dump
docker exec caderneta_db pg_restore -U caderneta -d caderneta_restore_test --clean --if-exists /tmp/restore.dump
```

Executar sempre contra o banco de teste separado
(`caderneta_restore_test`), **nunca** contra o banco em uso. Validar
após o restore:

- Contagem de linhas em tabelas críticas (`lancamentos`, `splits`)
  compatível com o esperado no momento do dump.
- Integridade da cadeia de hash da trilha de auditoria (verificação
  determinística, sem inferência — usar o mecanismo de verificação já
  existente no sistema, quando disponível para o schema restaurado).

Ao final, descartar o banco de teste:

```bash
docker exec caderneta_db dropdb -U caderneta caderneta_restore_test
```

## Frequência de teste de restore

**Mensal.** Não extraída de nenhum artefato de governança pré-existente
— prática comum, aprovada como parâmetro para v0.999, a ser revisada
após o primeiro mês de operação.

## Destino dos backups

**Local (`./backups/`).** Armazenamento off-site é **pendência de
evolução**, tratada separadamente — não é requisito para o merge
`feature/cartao-credito → main` nem para o Gate 0.

---

## Nota de rodapé — revisão futura de escopo

Se, no futuro, o `EventBusEmMemoria` for substituído por uma
implementação com estado persistente em Redis (ex.: um `EventBusRedis`
com filas persistentes), o escopo deste procedimento **deverá ser
revisado** para incluir backup do Redis. Esta nota não tem impacto no
Gate 0 atual — é registro preventivo para quando essa mudança
arquitetural ocorrer.

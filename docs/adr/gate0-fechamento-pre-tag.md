# Gate 0 — Fechamento Pré-Tag

**Natureza:** registro formal de decisão de governança. Encerra a
deliberação de Gate 0 iniciada em `docs/caderneta_pauta_deliberacao_gate0_v2.docx`
e continuada em `docs/adr/deliberacao-pos-fase6.md`,
`docs/adr/atualizacao-gate0-pos-reconciliacao.md`,
`docs/adr/deliberacao-d2-d3-gate0-pos-cartao.md` e
`docs/adr/pauta-deliberacao-residual-gate0.md` — não os substitui.
Não autoriza, por si só, a criação de tag ou release.

**Data:** 2026-08-18
**Decisor:** Camilo (Proprietário do Produto)
**Commit auditado:** `main` @ `f8fa2aa2054fb8f4021575903b379df8e1ff4de4`

---

## 1. Estado verificável de `main`

| Verificação | Resultado | Evidência |
|---|---|---|
| `git status` (working tree) | Limpo | Verificado nesta sessão |
| `HEAD` local | `f8fa2aa2054fb8f4021575903b379df8e1ff4de4` | `git rev-parse HEAD` |
| `origin/main` | `f8fa2aa2054fb8f4021575903b379df8e1ff4de4` | `git rev-parse origin/main` — idêntico ao local |
| `VERSAO_ATUAL` (`core/versao.py`) | `"0.9.1"` | `git show origin/main:core/versao.py` |
| `version` (`pyproject.toml`) | `"0.9.1"` | `git show origin/main:pyproject.toml` |
| `.env.example` | Presente, 4 variáveis reais (D5) | `git show origin/main:.env.example` |

## 2. Bloqueadores originais (numeração pré-Fase 6, D1–D7/B1/B2/OF)

| Item | Status | Evidência |
|---|---|---|
| B1 — Chave de identidade `CartaoCredito` | **FECHADO** | `docs/adr/deliberacao-complementar-gate-adr010.md:15,148` |
| B2 — Migration `transacoes_bancarias` | **RESOLVIDO** — commit `03a2fd8`, validado em Postgres real | `docs/adr/deliberacao-pos-fase6.md:32` |
| B3 — Validação de tipo de item contra fatura real (cartão) | **DEPENDÊNCIA EXTERNA — SÓ REGISTRO**, não bloqueante por definição da própria pauta | `docs/adr/pauta-deliberacao-residual-gate0.md:113-120,215` |

## 3. Itens D2–D7 pós-cartão/DT-CC-01

| Item | Status | Evidência |
|---|---|---|
| D2 — Versão do sistema | **RESOLVIDO em código** — `VERSAO_ATUAL`/`pyproject.toml` = `0.9.1` | Seção 1 acima; commit `f19f37c` (PR #3) |
| D3 — Qualidade de código (Ruff) | **Dívida técnica aceita formalmente** — 359 avisos (286 pré-existentes em `main`, 73 atribuíveis à branch), sem `--fix` executado | `docs/adr/deliberacao-d2-d3-gate0-pos-cartao.md` |
| D4 — Backup/recuperação | **RESOLVIDO** — `docs/procedimento-backup-recuperacao.md`, commit `18c9cd0` | `pauta-deliberacao-residual-gate0.md` |
| D5 — `.env.example` | **RESOLVIDO em artefato** | Seção 1 acima; commit `f19f37c` (PR #3) |
| D6 — Benchmark de embedding | **PENDÊNCIA PÓS-MERGE** (prazo 30 dias) | `pauta-deliberacao-residual-gate0.md` |
| D7 — Testes de propriedade (Hypothesis) | **PENDÊNCIA PÓS-MERGE** (prazo 45 dias) | `pauta-deliberacao-residual-gate0.md` |
| D12 — Competência de parcelas (evidência externa) | **PENDÊNCIA PÓS-MERGE** (prazo 15 dias) | `pauta-deliberacao-residual-gate0.md` |
| D19 — Exigência de parecer CRC (evidência externa) | **PENDÊNCIA PÓS-MERGE** (prazo 15 dias) | `pauta-deliberacao-residual-gate0.md` |

## 4. Regressão identificada e corrigida nesta unidade

O commit `8716fc7` (D2 em código + D5) foi perdido de `main` e de
`feature/cartao-credito` por efeito colateral de `git am --abort`
executado numa sessão anterior desta mesma conversa (reverteu a sessão
inteira de aplicação de patches, não apenas o patch em falha — erro de
orientação já assumido nesta conversa). Identificado nesta auditoria,
corrigido via commit `f19f37c`, mesclado em `main` por PR #3
(`f8fa2aa`). Diff idêntico ao commit original, confirmado por
comparação direta (`git diff 8716fc7 HEAD` vazio nos três arquivos
afetados).

## 5. Suíte de testes — execução local, com ressalva

Execução: `pytest`, ambiente local desta sessão, contra `main` @
`f8fa2aa`.

- **1 falha identificada:**
  `tests/unit/ai/test_sentence_transformer_provider.py::TestSentenceTransformerProviderContrato::test_satisfaz_protocolo`
  — `pytest_socket.SocketBlockedError` ao tentar `socket.getaddrinfo`
  para baixar modelo do Hugging Face. Causa ambiental (ambiente de
  execução sem acesso de rede a `huggingface.co`), não regressão de
  código.
- **Ressalva formal:** a versão do pytest neste ambiente não emitiu a
  linha-resumo final ("`N passed`"). Não se afirma, portanto, uma
  contagem exata de testes aprovados — apenas que, além da falha acima
  identificada e explicada, nenhuma outra falha foi observada na
  execução completa da suíte.
- Não se declara "suíte 100% aprovada"; declara-se: uma falha
  conhecida, de causa ambiental não relacionada a código, sem outras
  falhas observadas.

## 6. Integração Contínua (CI)

**Não configurado.** Não há diretório `.github/` nem qualquer pipeline
de CI no repositório nesta revisão. Este item é registrado como
"não configurado / não aplicável à evidência desta auditoria" — não
como aprovação de CI, que não existe para ser aprovada.

## 7. `feature/cartao-credito`

Encerrada/inativa, por decisão do Proprietário do Produto. Não
sincronizada com `main` — preservada como registro histórico do
trabalho, não atualizada artificialmente. Todo o conteúdo necessário já
foi integrado a `main` via PR #1, PR #2 e PR #3.

---

## Decisão formal

**GATE 0 — FECHADO.**

Todos os bloqueadores efetivos à promoção identificados nas
deliberações vigentes (D1–D7/B1/B2/OF originais e a pauta residual
D4/D6/D7/B3/D12/D19) foram resolvidos ou formalmente retirados da
condição de bloqueio — não que D1–D7 em conjunto fossem, em si,
bloqueadores de promoção; vários permanecem como pendência pós-merge
ou dependência externa, conforme as Seções 2 e 3 acima. A regressão de
`8716fc7` foi identificada e corrigida nesta mesma unidade, com
rastreabilidade completa (achado → correção → PR → revalidação).

**Pendências pós-merge monitoradas** (prazos contados a partir desta
data): D6 (30 dias), D7 (45 dias), D12 (15 dias), D19 (15 dias).
**Dependência externa registrada, sem prazo:** B3.
**Dívida técnica aceita, fora de escopo de Gate 0:** D3 (Ruff, 359
avisos) e R1/R2/R3 (`docs/adr/dt-cc-01-r1-debitos-remanescentes.md`).

## O que este documento NÃO decide

Não autoriza criação de tag `v0.999.0`, release, ou qualquer alteração
de código. Não altera nenhuma decisão registrada em documentos
anteriores. A criação de `v0.999.0` permanece como deliberação
separada, condicionada a autorização explícita própria.

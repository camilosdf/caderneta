# Deliberação Gate 0 — Itens D2 e D3, pós-cartão/DT-CC-01

**Natureza:** registro formal de deliberação. Complementa
`docs/adr/deliberacao-pos-fase6.md` e
`docs/adr/atualizacao-gate0-pos-reconciliacao.md` — não os substitui.
Mapeamento de numeração: item **3** do inventário de 19 itens
(`deliberacao-pos-fase6.md`) = **D2** da Pauta de Deliberação Gate 0
(`docs/caderneta_pauta_deliberacao_gate0_v2.docx`); item **4** = **D3**.
**Data:** 2026-08-18
**Branch:** `feature/cartao-credito`, HEAD `e4cb3e3`
**Decisor:** Proprietário do Produto (Camilo)

---

## D2 — Número de versão do sistema desatualizado

**Decisão: APROVADA**, formalizada em `docs/adr/004-emendas-comite.md`,
Emenda E-14.

- `VERSAO_ATUAL`: `"0.9.0"` → `"0.9.1"` (ETAPA `9`, inalterada; REVISÃO
  `0` → `1`).
- Cobre em revisão única: conclusão das Etapas 6–8 (já registrada por
  E-13, nunca incrementada), cartão de crédito completo (ADR 010, Fases
  0–6) e DT-CC-01/plano B.2 (ADR 011).
- **Não aplicada em código nesta ação.** `core/versao.py:20` continua
  `VERSAO_ATUAL = "0.9.0"` — ver Seção 3 abaixo.

## D3 — Qualidade do código-fonte antes do congelamento (Ruff)

**Decisão: MODIFICADA / APROVADA** — não a proposta original da equipe
(zerar todos os avisos), mas alternativa deliberada.

**Registro:** os erros de Ruff existentes **não serão zerados** como
pré-condição de merge ou congelamento neste ciclo. Aceita-se
formalmente como dívida técnica registrada, com a parcela pré-existente
distinguida da parcela introduzida pela branch de cartão:

| Escopo | Contagem | Evidência |
|---|---|---|
| `main` (`7deee47`, antes de qualquer trabalho de cartão) | **286** | `ruff check .` em `main` |
| `feature/cartao-credito` (HEAD `e4cb3e3`) | **359** | `ruff check .` na branch |
| Atribuível à sequência de cartão/DT-CC-01 | **73** | diferença 359−286; confirmado por método independente (Ruff isolado nos 69 arquivos `.py` tocados/criados pela branch: 155 erros nesses arquivos na branch vs. 82 já presentes nos mesmos arquivos em `main`, mesma diferença de 73) |

Distribuição por regra (359 total): 96 `UP045`, 62 `I001`, 46 `F401`, 33
`UP007`, 22 `UP035`, 15 `B008`, 14 `SIM117`, 13 `E741`, 12 `E402`, 12
`UP017`, 9 `F841`, 8 `F541`, 5 `SIM102`, 5 `UP042`, 4 `SIM105`, 2 `B904`,
1 `UP006`. 291/359 têm correção automática (`--fix`); nenhuma foi
executada.

**Explicitamente não decidido por este registro:** os 73 erros
atribuíveis à branch **não** viram requisito de merge — decisão
deliberada para não introduzir escopo de limpeza de código estranho ao
trabalho técnico de DT-CC-01/B.2. Nenhuma execução de `ruff --fix`
(global ou parcial) foi realizada nesta ação nem está autorizada por
este documento.

## O que este documento NÃO resolve

Nenhuma alteração de código foi feita — nem `core/versao.py`, nem
`pyproject.toml`, nem qualquer correção de Ruff. Ambas as ações ficam
como pendências separadas, cada uma exigindo autorização explícita
própria antes de execução.

Os demais itens do inventário (D1, D4–D7, B1/B2 — já tratados em
documentos anteriores — e os achados R1/R2/R3 de
`docs/adr/dt-cc-01-r1-debitos-remanescentes.md`) permanecem exatamente
como registrados alhures. Este documento não os reabre nem os fecha.

## Efeito sobre o merge `feature/cartao-credito → main`

D2 e D3 deixam de ser bloqueadores de deliberação para o merge. O merge
em si continua retido — ver decisão do Proprietário do Produto (Opção 2,
"aguardar") registrada na conversa que originou este documento —
condicionado à aplicação em código de D2 (`VERSAO_ATUAL`), resolução de
D5 (`.env.example`) e revalidação final do inventário de Gate 0.

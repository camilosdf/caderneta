# Atualização — Gate 0, item 1 (VERSAO_HOMOLOGADA), D1 (segregação de funções) e B3 (cascata de aprovação)

**Natureza:** achado técnico + proposta de atualização de status. Nenhuma
decisão de mérito tomada aqui além do que já foi informado por Camilo
nesta sessão (D1). Complementa `deliberacaoposfase6.md` e
`revisaodeliberativadtccd18.md` — não os substitui.

---

## 1. Achado sobre `dd73093`

`deliberacaoposfase6.md` (Seção 6) autorizou como próxima unidade de
trabalho **exclusivamente**: "adicionar `VERSAO_HOMOLOGADA` a
`TipoEvento` (`core/audit/chain.py`), sem qualquer outra alteração".

O commit `dd73093` ("fix(gate0): adiciona TipoEvento.VERSAO_HOMOLOGADA")
não corresponde a essa unidade:

- Inclui `core/cli.py` (+141 linhas): dois comandos novos
  (`cartao gerar-lancamentos`, `cartao conciliar-pagamento`) — sem
  relação com `VERSAO_HOMOLOGADA`.
- Inclui `infra/migrations/versions/61a24bc5d5f6_usuarios_schema.py` —
  é o item **16** do inventário ("Migration para `usuarios`"), não o
  item 1.
- O próprio item 1 ficou **incompleto**: o enum foi adicionado, mas
  `infra/scripts/release.py` nunca chamava `uow.audit.registrar()` para
  esse evento — confirmado por grep nesta sessão, `release.py:165`
  ainda continha só um `print` de lembrete. O bloqueador que o commit
  reivindica fechar continuava, na prática, aberto.

Não é uma objeção ao mérito de nenhuma dessas três mudanças
isoladamente — é um achado de rastreabilidade: a mensagem do commit
descreve uma unidade, o diff entrega três, e a única que a mensagem
reivindica não estava de fato completa.

## 2. Estado real após esta sessão

| # (inventário) | Item | Status antes | Status agora | Evidência |
|---|---|---|---|---|
| 1 | `VERSAO_HOMOLOGADA` | ✗ Bloqueador (enum existia, nada gravava) | ✓ **RESOLVIDO** | `registrar_homologacao()` em `infra/scripts/release.py`; `versao_para_audit()` corrigido (lia singleton desatualizado); 4 testes (`tests/unit/infra/test_release.py`) |
| 2 | Segregação de funções (D1) | ⚠ Decisão crítica, pendente — `criador_id=""` confirmado no código | ✓ **Decisão MODIFICADA — Opção B implementada** (informada por Camilo em nome de Controles Internos + Contador CRC, sessão de 17/08/2026) | `criado_por` persistido; `PolicyEngine` falha fechada (`origem_desconhecida`); migration `8e2c4f1a9b3d` |
| *(não numerado no inventário)* | Cascata de dois aprovadores | Endpoint nunca delegava a `Lancamento.aprovar()` — `DOIS_APROVADORES` nunca exigia de fato um segundo aprovador | ✓ **RESOLVIDO** — achado durante a correção de D1, registrado aqui como item novo, não mesclado a nenhum outro | `PolicyEngine.aprovador_nivel1_id` + `segregacao_niveis_aprovacao`; 5 testes |
| 16 | Migration para `usuarios` | Pendente à data de `deliberacaoposfase6.md` | Já resolvido por `dd73093` (`61a24bc5d5f6`), **antes** desta sessão | — |

Correção a um número que eu mesmo produzi na Entrega 1: o `caderneta_pauta_deliberacao_gate0_v2_1.docx` que você enviou registra "B2 — RESOLVIDO — 9/9 critérios" com a implicação de que esta sessão resolveu o bloqueador de `transacoes_bancarias`. Não foi o caso — `03a2fd8` já havia resolvido isso antes de qualquer trabalho meu. O que esta sessão de fato adicionou ao que already era B2 foi só a coluna `criado_por` (parte de D1, tecnicamente) e a infraestrutura de teste/guardrail (B2.7–B2.9), que não faziam parte do bloqueador original.

## 3. O que esta sessão NÃO decide nem resolve

Itens 3–15, 17–19 do inventário (Ruff — agora 304 erros, não 183; versão
declarada — agora mais desatualizada, toda a Fase 6 sem refletir;
`.env.example`; backup; modelo de embedding; testes de propriedade;
D12; B3-cartão (validação contra fatura real); D19; DT-CC-01/02/03;
D18) permanecem **exatamente** como registrados em
`deliberacaoposfase6.md` e `revisaodeliberativadtccd18.md`. Nenhuma
decisão ou implementação adicional foi feita sobre eles.

## 4. Pendência mecânica — ordem das migrations

`50b082b6c92c_confidence_compras_cartao.py` (DT-CC-02, ainda não
commitada) tem `down_revision='61a24bc5d5f6'` — o mesmo pai da minha
`8e2c4f1a9b3d`. Aplicar as duas sem ajuste cria duas heads
(`alembic upgrade head` falha com "Multiple head revisions"). Não é
uma decisão minha qual vem primeiro — é sequenciamento de trabalho, não
uma questão técnica a arbitrar:

- Se `8e2c4f1a9b3d` entrar primeiro: mude `50b082b6c92c`'s
  `down_revision` para `'8e2c4f1a9b3d'` antes de commitá-la.
- Se `50b082b6c92c` entrar primeiro: eu ajusto `8e2c4f1a9b3d` para
  `down_revision='50b082b6c92c'` e regenero o patch — é só pedir.

## 5. Sobre `docs/adr/caderneta_pauta_deliberacao_gate0_v2_1.docx`

Confirmado por comparação direta: é o mesmo arquivo que esta sessão
entregou como `docs/caderneta_pauta_deliberacao_gate0_v2.docx` — não é
uma pauta paralela, não há conflito de fonte. Está desatualizado frente
ao inventário de 19 itens (cobre só D1–D7/B1/B2/OF, numeração
pré-Fase 6, e a linha B2 tem a imprecisão corrigida na Seção 2 acima).

Recomendo não usá-lo como registro vigente do Gate 0 daqui para frente
— este documento (formato `.md`, mesmo padrão de
`deliberacaoposfase6.md`/`revisaodeliberativadtccd18.md`, que já são o
processo de governança ativo desta branch) é o que proponho manter
como próxima atualização de status. Se preferir manter o `.docx` como
formato oficial, aviso e eu atualizo os itens 1/2/B3 nele em vez disso.

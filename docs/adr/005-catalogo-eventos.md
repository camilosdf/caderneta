# ADR 005 — Catálogo de Eventos do Sistema

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe + Comitê Ampliado (Arquiteto de Sistemas Distribuídos)

---

## Contexto

O comitê identificou a ausência de um mecanismo formal de comunicação entre
módulos. Sem eventos tipados, módulos se acoplam diretamente — o pipeline
chama o classificador, que chama o normalizador, que conhece o audit log.
Isso cria dependências circulares e impede que a IA seja verdadeiramente
opcional.

## Decisão

Todo o sistema se comunica via eventos tipados definidos em `core/events/`.
Nenhum módulo importa outro módulo diretamente para reagir a algo que
aconteceu — apenas publica e escuta eventos.

O barramento de eventos é injetado via `EventBusAdapter` (Port definido em
`core/ports/`). Implementação padrão: Redis Streams. Implementação de teste:
barramento em memória.

**A IA escuta eventos. Nunca os produz diretamente no fluxo principal.**

## Catálogo de eventos

### Ciclo de vida do documento
| Evento | Publicado por | Consumido por |
|--------|--------------|---------------|
| `DocumentoRecebido` | use case ProcessarDocumento | pipeline, audit |
| `DocumentoValidado` | parser | pipeline |
| `DocumentoParseado` | parser | normalizador, audit |
| `DocumentoDuplicado` | deduplicador | pipeline (interrompe) |
| `DocumentoErro` | qualquer motor | audit, alertas |

### Ciclo de vida do lançamento
| Evento | Publicado por | Consumido por |
|--------|--------------|---------------|
| `FornecedorNormalizado` | normalizador | classificador |
| `ClassificacaoConcluida` | classificador | motor contábil |
| `LancamentoCriado` | motor contábil | fila aprovação, audit |
| `LancamentoAprovado` | use case AprovarLancamento | exportador, audit |
| `LancamentoRejeitado` | use case AprovarLancamento | audit |
| `LancamentoEstornado` | use case EstornarLancamento | audit |
| `DocumentoExportado` | adaptador contábil | audit |

### Governança
| Evento | Publicado por | Consumido por |
|--------|--------------|---------------|
| `RegraAlterada` | rule engine | audit (hash chain) |
| `PoliticaAlterada` | policy engine | audit (hash chain) |
| `PeriodoFechado` | use case FecharPeriodo | audit, policy engine |
| `FeedbackRegistrado` | use case RegistrarFeedback | Finance KB (ai/) |

### Regra de consumo da IA
Os plugins em `ai/` APENAS escutam eventos — nunca publicam eventos de
domínio. Podem publicar eventos de métricas (`EmbeddingCalculado`,
`OCRConcluido`) consumidos apenas por observabilidade.

## Consequências

- Módulos completamente desacoplados: trocar o classificador não afeta o audit
- Retry e dead-letter queue naturais via Redis Streams
- Observabilidade: cada evento é uma métrica
- IA é verdadeiramente opcional — remover `ai/` não quebra nenhum evento de domínio

---

## Atualização — Etapas 6 e 8 (agosto de 2026)

Os eventos abaixo foram adicionados ao `TipoEvento` em `core/audit/chain.py`
durante as Etapas 6 (Interface Web) e 8 (Conciliação Bancária).

### Eventos da Interface Web (Etapa 6)

| Evento | Quando é emitido | Payload obrigatório |
|---|---|---|
| `USUARIO_LOGIN` | Login bem-sucedido via `/login` | `email`, `papel`, `authentication_id` |
| `USUARIO_LOGOUT` | Logout via `/logout` | `email`, `papel`, `authentication_id` |

O campo `authentication_id` identifica qual sessão foi iniciada ou encerrada
(equivale ao `session_id` gravado no cookie). Isso permite rastrear, em caso de
auditoria, exatamente qual sessão foi usada em cada ação — mesmo que o mesmo
usuário tenha feito múltiplos logins.

### Eventos do Motor de Conciliação Bancária (Etapa 8)

| Evento | Quando é emitido |
|---|---|
| `EXTRATO_IMPORTADO` | Importação de arquivo OFX concluída |
| `CONCILIACAO_INICIADA` | Motor de conciliação iniciado para um período |
| `MATCH_IDENTIFICADO` | Lançamento conciliado com transação bancária |
| `DIVERGENCIA_IDENTIFICADA` | Match encontrado mas com diferença de valor ou data |
| `CONCILIACAO_AMBIGUA` | Mais de um candidato equivalente — revisão humana necessária |
| `CONCILIACAO_APROVADA` | Conciliação revisada e aprovada pelo contador |
| `CONCILIACAO_REJEITADA` | Conciliação revisada e rejeitada |

### Evento de homologação (Etapa 9 — pendente de implementação)

| Evento | Quando será emitido |
|---|---|
| `VERSAO_HOMOLOGADA` | Transição formal de v0.999 para v1.0.0, após aprovação CRC |

Este evento é classificado como **BLOQUEADOR** na Matriz de Prontidão para v0.999:
deve ser implementado em `TipoEvento` antes do congelamento de código.

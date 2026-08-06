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

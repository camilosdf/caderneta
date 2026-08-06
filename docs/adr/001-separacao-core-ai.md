# ADR 001 — Separação entre Caderneta Core e Caderneta AI

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe (Eng. Software Sênior, Arquiteto IA, Contador CRC, Esp. Controles Internos)

---

## Contexto

O Caderneta é uma plataforma de automação contábil que combina:
- Lógica determinística de regras contábeis (invariável, auditável)
- Componentes de IA para extração e classificação (evolutivos, substituíveis)

A proposta inicial (PoC) misturava esses dois mundos em um único pacote, criando acoplamento entre regras contábeis e modelos de linguagem.

## Decisão

O projeto é dividido em dois módulos lógicos dentro do mesmo monorepo:

**`core/`** — Caderneta Core  
Contém toda a lógica de negócio: domínio, regras, pipeline, auditoria, parsers determinísticos e adaptadores de exportação. Não importa nenhum módulo de `ai/`. Deve funcionar completamente sem modelos de linguagem, GPU ou conexão externa.

**`ai/`** — Caderneta AI  
Contém embeddings, LLM, OCR, RAG e mecanismos de aprendizado. Implementa as interfaces (Protocols) definidas em `core/ports/`. Nunca define regras contábeis. Nunca escreve diretamente no banco de lançamentos.

A comunicação entre os dois módulos ocorre exclusivamente via contratos definidos em `core/ports/`:

```python
# core/ports/classification.py
class ClassificationPort(Protocol):
    def sugerir_categoria(self, documento: Documento) -> Sugestao: ...
    def normalizar_fornecedor(self, nome_raw: str) -> ResultadoNormalizacao: ...

# core/ports/extraction.py  
class ExtractionPort(Protocol):
    def extrair(self, texto: str, tipo_doc: TipoDocumento) -> CamposExtraidos: ...
```

## Alternativas consideradas

**Alternativa 1:** Monólito único com flags de feature  
Rejeitada. Feature flags para desabilitar IA não resolvem o acoplamento de importações — o Core ainda dependeria de bibliotecas de IA no ambiente de execução.

**Alternativa 2:** Dois repositórios separados  
Rejeitada para fase inicial. Aumenta a fricção de desenvolvimento sem ganho proporcional enquanto o projeto ainda está crescendo.

**Alternativa 3:** Separação via microsserviços desde o início  
Rejeitada. Overhead operacional desproporcional para a fase atual. A separação via Protocol permite migrar para microsserviços no futuro sem reescrever o domínio.

## Consequências

**Positivas:**
- Testes do Core rodam em < 5s sem nenhuma dependência de IA
- Componentes de IA podem ser substituídos sem alterar regras contábeis
- Auditores podem revisar o Core independentemente dos plugins de IA
- Possibilidade futura de publicar o Core como biblioteca independente

**Negativas:**
- Curva de aprendizado levemente maior para novos desenvolvedores
- Necessidade de manter os contratos em `core/ports/` atualizados

## Referências

- Martin, R.C. — Clean Architecture, Cap. 22 (The Clean Architecture)
- Proposta de arquitetura por etapas de maturidade — julho/2026

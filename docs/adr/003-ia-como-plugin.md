# ADR 003 — IA como Plugin via Protocol, nunca como Core

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe

---

## Contexto

Sistemas de automação contábil com IA têm um risco específico: a IA pode "alucinar" valores, categorias ou fornecedores, e esse erro entrar silenciosamente nos lançamentos. O risco aumenta quando a IA está no caminho crítico de decisão.

## Decisão

A IA nunca toma decisões contábeis. Ela apenas **sugere**, com um score de confiança. Decisões são tomadas por:
1. Regras determinísticas (prioridade máxima, sempre)
2. Finance Knowledge Base — histórico validado por humanos (segunda prioridade)
3. Sugestão de IA com confidence ≥ threshold configurável (terceira prioridade)
4. Revisão humana obrigatória (fallback)

A arquitetura de plugins é implementada via `typing.Protocol`:

```python
# core/ports/classification.py
class ClassificationPort(Protocol):
    def sugerir_categoria(
        self, documento: Documento, fornecedor: Fornecedor
    ) -> Sugestao: ...

# Implementação padrão (sem IA) — usada nas Etapas 1 a 6
class RegrasDeterministicasPlugin:
    def sugerir_categoria(self, documento, fornecedor) -> Sugestao:
        return self._aplicar_regras(documento, fornecedor)

# Implementação com embeddings — adicionada na Etapa 7
class EmbeddingsPlugin:
    def sugerir_categoria(self, documento, fornecedor) -> Sugestao:
        return self._busca_semantica(documento, fornecedor)

# Implementação com LLM — opcional, para desambiguação
class LLMPlugin:
    def sugerir_categoria(self, documento, fornecedor) -> Sugestao:
        return self._consultar_llm(documento, fornecedor)
```

O Motor Contábil (Etapa 4) recebe qualquer implementação de `ClassificationPort` via injeção de dependência. Nunca importa `ai/` diretamente.

## Alternativas consideradas

**Alternativa 1:** LLM decide a categoria diretamente  
Rejeitada. LLMs alucinam. Contabilidade não admite erro silencioso.

**Alternativa 2:** IA validada por regras (IA decide, regra confirma)  
Rejeitada. A precedência correta é inversa: regra decide, IA complementa onde a regra não cobre.

**Alternativa 3:** Sem IA — apenas regras  
Válida para a Etapa 4. O sistema deve funcionar sem IA. A IA é uma melhoria de precisão, não um requisito.

## Thresholds de confiança (configuráveis por empresa)

| Faixa | Ação |
|-------|------|
| confidence ≥ 0.99 | Pré-aprovação automática (Fase 2+) |
| 0.90 ≤ confidence < 0.99 | Aprovação do Contador |
| confidence < 0.90 | Revisão com flag de atenção |
| Regra determinística | Sempre confidence = 1.0, sem revisão |

## Consequências

**Positivas:**
- O Core passa em todos os testes sem nenhum modelo de IA instalado
- Trocar Ollama por vLLM, ou Qwen por Mistral, não altera uma linha do Core
- Auditores revisam apenas o Core para entender as decisões contábeis

**Negativas:**
- Requer disciplina para não criar atalhos que importem `ai/` dentro do `core/`
- O contrato em `core/ports/` precisa ser suficientemente genérico para acomodar diferentes implementações

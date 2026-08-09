"""LLMPort — contrato para modelos de linguagem (Etapa 7.5).

Define a interface que qualquer provider de LLM deve satisfazer
para ser usado pelo LLMPlugin. O Core define o contrato; ai/ implementa.

Por que um Port separado de ClassificationPort?
  LLMs operam via prompt/resposta — a interação é fundamentalmente
  diferente de um encoder de embeddings ou de um conjunto de regras.
  O LLMPort expõe essa primitiva (completar um prompt), deixando
  para o LLMPlugin a responsabilidade de construir o prompt contábil
  correto e interpretar a resposta.

Princípio (ADR 003): LLM é auxiliar, não decisor. O ClassifierOrchestrator
garante que o LLM só é consultado quando regras + embeddings não cobriram
o caso com confiança suficiente.

Implementações planejadas (Fase 2):
  - OllamaProvider: Ollama local (Qwen3, Mistral, Llama)
  - AnthropicProvider: API Anthropic
  - FakeLLMProvider: testes herméticos (este arquivo)
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Contrato de provider de LLM.

    Primitiva única: completar um prompt e retornar o texto gerado.
    O prompt é responsabilidade do caller (LLMPlugin) — o provider
    apenas executa o modelo.
    """

    def completar(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperatura: float = 0.0,
    ) -> str:
        """Completa um prompt e retorna o texto gerado.

        Args:
            prompt: texto de entrada (instrução + contexto do documento).
            max_tokens: limite de tokens na resposta.
            temperatura: 0.0 para respostas determinísticas (recomendado
                         para classificação contábil — não queremos criatividade).

        Returns:
            Texto gerado pelo modelo. O caller é responsável por parsear
            e validar — nunca confiar cegamente na saída do LLM.
        """
        ...

    @property
    def modelo(self) -> str:
        """Identificador do modelo em uso — registrado na auditoria."""
        ...

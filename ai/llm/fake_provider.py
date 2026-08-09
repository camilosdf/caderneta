"""FakeLLMProvider — stub determinístico para testes herméticos (Etapa 7.5).

NÃO é uma implementação de produção.
NÃO simula qualidade de LLM real.

Apenas satisfaz LLMPort para que LLMPlugin e ClassifierOrchestrator
possam ser testados sem Ollama, sem GPU, sem rede.

Implementações reais (Fase 2):
  - OllamaProvider: Ollama local (Qwen3, Mistral, Llama)
  - AnthropicProvider: API Anthropic
"""

from core.ports.llm import LLMPort


class FakeLLMProvider:
    """Satisfaz LLMPort via duck typing. Retorna resposta configurável."""

    def __init__(
        self,
        resposta_padrao: str = '{"categoria": "Outras Despesas", "confidence": 0.5}',
        modelo_nome: str = "fake-llm-test",
    ) -> None:
        self._resposta = resposta_padrao
        self._modelo_nome = modelo_nome
        self.chamadas: list[str] = []  # registro de prompts recebidos (inspeção em testes)

    @property
    def modelo(self) -> str:
        return self._modelo_nome

    def completar(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperatura: float = 0.0,
    ) -> str:
        self.chamadas.append(prompt)
        return self._resposta

    def satisfaz_protocolo(self) -> bool:
        """Confirma que este stub satisfaz LLMPort."""
        return isinstance(self, LLMPort)

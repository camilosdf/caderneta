"""Use case: ProcessarFaturaCartao — ADR 010, Fase 2.

Fluxo dedicado à fatura de cartão de crédito, decorrente da Opção B do
Gate pré-Fase 2: `FaturaCartao` (D1) não cabe em `ParserProtocol ->
Iterator[Documento]` nem no formato de `ExtractionPort` (dict plano,
um valor por campo) — por isso não é forçado a passar por
`ParserFactory`. `ExtractionPort` permanece inalterado.

Reaproveita, sem duplicar:
  - DetectorDocumento: mesma detecção PDF_TEXTO/PDF_IMAGEM já usada
    pelo restante do pipeline.
  - pdfplumber: mesma biblioteca já usada pelo detector (extração de
    texto completo, para PDF_TEXTO).
  - ExtractionPort (OCRPlugin, em ai/): injetado via porta, nunca
    importado diretamente aqui — core/ não importa ai/ (ADR 001).
  - FaturaCartao.validar_fechamento(): invariante de fechamento já
    implementada no domínio (Fase 1, D5).

Escopo desta etapa (Fase 2): extração estruturada + montagem do
agregado em memória. NÃO persiste (repositório fica para quando for
necessário), NÃO gera lançamento (LancamentoService é Fase 3), NÃO
publica eventos de auditoria (catálogo de eventos é Fase 4).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from core.domain.entities import (
    CompraCartao,
    ConfidenceScore,
    Dinheiro,
    Documento,
    FaturaCartao,
    FonteExtracao,
    StatusFechamentoFatura,
    TipoDocumento,
)
from core.parsers.detector import DetectorDocumento, TipoNaoSuportadoError
from core.parsers.pdf.fatura_cartao_nubank import parsear_fatura_texto


@runtime_checkable
class ExtratorDeArquivoPort(Protocol):
    """Porta mínima para extração de texto a partir de um arquivo (OCR).

    Não é uma extensão de ExtractionPort (core/ports/classification.py)
    — ExtractionPort permanece inalterado, conforme Gate pré-Fase 2.
    Esta é uma porta nova e separada, local a este use case, para o
    único método que falta (extrair texto de um arquivo, não de uma
    string já extraída). OCRPlugin (ai/) já implementa este método por
    duck typing, sem precisar de nenhuma alteração.
    """

    def extrair_de_arquivo(self, filepath: Path) -> dict[str, tuple[str, float]]:
        ...


class DocumentoNaoEhFaturaError(Exception):
    """PDF não tem nenhum campo de cabeçalho de fatura reconhecido
    (vencimento e total ausentes) — não é tratado como fatura suportada."""


class OCRNaoDisponivelError(Exception):
    """PDF_IMAGEM requer um ExtractionPort injetado — nunca construído
    internamente (core/ não importa ai/, ver ADR 001)."""


@dataclass
class ResultadoProcessamentoFatura:
    """Resultado do use case — agregados em memória, sem persistência."""
    documento: Documento
    fatura: FaturaCartao
    itens_baixa_confianca: list[CompraCartao] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


class ProcessarFaturaCartaoUseCase:
    """Orquestra a extração estruturada de uma fatura de cartão em PDF.

    ocr_plugin é opcional na construção — só é exigido em tempo de
    execução se o PDF detectado for PDF_IMAGEM. Faturas PDF_TEXTO
    funcionam sem nenhuma dependência de OCR.
    """

    def __init__(
        self,
        detector: DetectorDocumento | None = None,
        ocr_plugin: ExtratorDeArquivoPort | None = None,
    ) -> None:
        self._detector = detector or DetectorDocumento()
        self._ocr_plugin = ocr_plugin

    def executar(
        self,
        filepath: Path,
        empresa_id: UUID,
        cartao_id: UUID | None = None,
    ) -> ResultadoProcessamentoFatura:
        tipo = self._detector.detectar(filepath)
        if tipo not in (TipoDocumento.PDF_TEXTO, TipoDocumento.PDF_IMAGEM):
            raise TipoNaoSuportadoError(
                f"ProcessarFaturaCartaoUseCase espera PDF, recebeu: {tipo.value}"
            )

        hash_doc = self._detector.calcular_hash(filepath)

        if tipo == TipoDocumento.PDF_TEXTO:
            texto = self._extrair_texto_pdfplumber(filepath)
            fonte = FonteExtracao.PDF_TEXTO
        else:
            texto = self._extrair_texto_ocr(filepath)
            fonte = FonteExtracao.OCR

        documento = Documento(
            empresa_id=empresa_id,
            hash_sha256=hash_doc,
            nome_arquivo=filepath.name,
            tipo=tipo,
            fonte_extracao=fonte,
        )

        extraida = parsear_fatura_texto(texto)

        if extraida.data_vencimento is None and extraida.valor_total_declarado is None:
            raise DocumentoNaoEhFaturaError(
                f"Nenhum campo de fatura reconhecido em {filepath.name} "
                f"(vencimento e total ausentes) — não parece ser uma "
                f"fatura de cartão suportada."
            )

        fatura = FaturaCartao(
            empresa_id=empresa_id,
            cartao_id=cartao_id,
            documento_id=documento.id,
            periodo_referencia=extraida.periodo_referencia,
            data_vencimento=extraida.data_vencimento,
            valor_total_declarado=Dinheiro(
                extraida.valor_total_declarado or Decimal("0")
            ),
        )

        avisos: list[str] = []
        itens_baixa_confianca: list[CompraCartao] = []

        if not extraida.itens:
            avisos.append(
                "Nenhum item de linha reconhecido no texto — fatura "
                "criada apenas com dados de cabeçalho, requer revisão manual."
            )

        for item in extraida.itens:
            compra = CompraCartao(
                empresa_id=empresa_id,
                fatura_id=fatura.id,
                tipo=item.tipo,
                estabelecimento=item.estabelecimento,
                descricao_original=item.descricao_original,
                data_compra=item.data_compra,
                valor=Dinheiro(item.valor),
                parcela_atual=item.parcela_atual,
                total_parcelas=item.total_parcelas,
                posicao_linha=item.posicao_linha,
                confidence=ConfidenceScore(valor=item.confidence, campo="classificacao_item"),
            )
            fatura.itens.append(compra)
            if not compra.confidence.e_confiavel:
                itens_baixa_confianca.append(compra)

        if fatura.itens:
            fatura.validar_fechamento()
            if fatura.status_fechamento == StatusFechamentoFatura.DIVERGENTE:
                avisos.append(
                    "Fatura divergente: soma dos itens não bate com o "
                    "total declarado dentro da tolerância (D5) — "
                    "requer revisão manual."
                )

        if itens_baixa_confianca:
            avisos.append(
                f"{len(itens_baixa_confianca)} de {len(fatura.itens)} itens "
                f"com confiança abaixo do limiar (ConfidenceScore.e_confiavel "
                f"= 0.90) — requerem revisão manual antes de gerar lançamento."
            )

        return ResultadoProcessamentoFatura(
            documento=documento,
            fatura=fatura,
            itens_baixa_confianca=itens_baixa_confianca,
            avisos=avisos,
        )

    def _extrair_texto_pdfplumber(self, filepath: Path) -> str:
        """Extrai texto completo do PDF via pdfplumber — mesma biblioteca
        já usada por DetectorDocumento, sem duplicar a dependência."""
        import pdfplumber
        partes = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                texto_pagina = page.extract_text()
                if texto_pagina:
                    partes.append(texto_pagina)
        return "\n".join(partes)

    def _extrair_texto_ocr(self, filepath: Path) -> str:
        """Extrai texto via ExtractionPort injetado (implementação real:
        OCRPlugin, em ai/) — nunca importado diretamente aqui."""
        if self._ocr_plugin is None:
            raise OCRNaoDisponivelError(
                f"{filepath.name} foi detectado como PDF_IMAGEM e requer "
                f"OCR, mas nenhum ExtractionPort foi injetado no use case."
            )
        campos = self._ocr_plugin.extrair_de_arquivo(filepath)
        if "erro_ocr" in campos:
            raise DocumentoNaoEhFaturaError(
                f"Erro no OCR de {filepath.name}: {campos['erro_ocr'][0]}"
            )
        texto_bruto, _confidence = campos.get("texto_bruto", ("", 0.0))
        return texto_bruto

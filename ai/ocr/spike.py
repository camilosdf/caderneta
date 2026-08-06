"""Spike de PaddleOCR — Emenda E-11.

Prova de conceito técnica rodando em paralelo ao Core.
NÃO integra ao pipeline principal neste momento.
NÃO é código de produção.

Objetivo:
1. Medir performance em documentos brasileiros reais
2. Gerar pares (texto_extraído, campos_esperados) para o Ground Truth Dataset
3. Identificar casos problemáticos antes da Etapa 7

Execução:
  python -m ai.ocr.spike --pasta ./tests/fixtures/pdfs/

Saída:
  - tests/fixtures/ground_truth/ocr_results.jsonl
  - Relatório de métricas (precisão, tempo, casos de erro)
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ResultadoOCR:
    """Resultado do OCR de um documento — para o Ground Truth Dataset."""
    arquivo: str
    texto_extraído: str
    tempo_ms: float
    confiança_media: float
    linhas: list[dict]
    erro: Optional[str] = None


@dataclass
class RelatorioSpike:
    """Relatório agregado da spike de OCR."""
    total_documentos: int = 0
    processados: int = 0
    erros: int = 0
    tempo_total_ms: float = 0.0
    confiança_media: float = 0.0
    resultados: list[ResultadoOCR] = field(default_factory=list)

    @property
    def tempo_medio_ms(self) -> float:
        return self.tempo_total_ms / self.processados if self.processados else 0.0

    def resumo(self) -> str:
        return (
            f"Spike PaddleOCR\n"
            f"  Documentos: {self.total_documentos}\n"
            f"  Processados: {self.processados} | Erros: {self.erros}\n"
            f"  Tempo médio: {self.tempo_medio_ms:.0f}ms\n"
            f"  Confiança média: {self.confiança_media:.1%}\n"
        )


class SpikeOCR:
    """
    Spike técnica de PaddleOCR.
    Configurações otimizadas para CPU (sem GPU) em documentos BR.
    """

    def __init__(self):
        # Importação lazy — PaddleOCR só é importado quando a spike rodar
        # O Core NUNCA chega aqui
        self._ocr = None

    def _inicializar(self):
        """Inicializa PaddleOCR na primeira chamada."""
        if self._ocr is not None:
            return
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                use_angle_cls=False,    # 40% mais rápido sem classificação de ângulo
                lang="pt",              # português
                use_gpu=False,          # CPU mode — sem dependência de GPU
                show_log=False,
            )
        except ImportError:
            raise RuntimeError(
                "PaddleOCR não instalado. Execute: pip install paddleocr paddlepaddle\n"
                "Esta dependência é opcional e pertence ao módulo ai/, não ao core/."
            )

    def processar_documento(self, filepath: Path) -> ResultadoOCR:
        self._inicializar()
        inicio = time.time()

        try:
            resultado = self._ocr.ocr(str(filepath), cls=False)
            linhas = []
            confiancas = []

            for linha in (resultado[0] or []):
                bbox, (texto, confiança) = linha
                linhas.append({
                    "texto": texto,
                    "confiança": round(confiança, 4),
                    "bbox": [[round(c, 1) for c in ponto] for ponto in bbox],
                })
                confiancas.append(confiança)

            texto_completo = "\n".join(l["texto"] for l in linhas)
            confiança_media = sum(confiancas) / len(confiancas) if confiancas else 0.0

            return ResultadoOCR(
                arquivo=filepath.name,
                texto_extraído=texto_completo,
                tempo_ms=round((time.time() - inicio) * 1000, 1),
                confiança_media=round(confiança_media, 4),
                linhas=linhas,
            )

        except Exception as e:
            return ResultadoOCR(
                arquivo=filepath.name,
                texto_extraído="",
                tempo_ms=round((time.time() - inicio) * 1000, 1),
                confiança_media=0.0,
                linhas=[],
                erro=str(e),
            )

    def rodar_spike(
        self,
        pasta_entrada: Path,
        pasta_saida: Path,
    ) -> RelatorioSpike:
        """Processa todos os PDFs/imagens e salva resultados para Ground Truth."""

        pasta_saida.mkdir(parents=True, exist_ok=True)
        extensoes = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}
        arquivos = [
            f for f in pasta_entrada.iterdir()
            if f.suffix.lower() in extensoes
        ]

        relatorio = RelatorioSpike(total_documentos=len(arquivos))
        arquivo_gt = pasta_saida / "ocr_results.jsonl"

        with open(arquivo_gt, "w", encoding="utf-8") as f_out:
            for arquivo in sorted(arquivos):
                resultado = self.processar_documento(arquivo)
                relatorio.resultados.append(resultado)

                if resultado.erro:
                    relatorio.erros += 1
                else:
                    relatorio.processados += 1
                    relatorio.tempo_total_ms += resultado.tempo_ms
                    relatorio.confiança_media = (
                        (relatorio.confiança_media * (relatorio.processados - 1)
                         + resultado.confiança_media)
                        / relatorio.processados
                    )

                # Salvar no Ground Truth Dataset
                f_out.write(json.dumps({
                    "arquivo": resultado.arquivo,
                    "texto": resultado.texto_extraído,
                    "tempo_ms": resultado.tempo_ms,
                    "confianca_media": resultado.confiança_media,
                    "n_linhas": len(resultado.linhas),
                    "erro": resultado.erro,
                    # campos_esperados: preencher manualmente para criar o dataset
                    "campos_esperados": None,
                }, ensure_ascii=False) + "\n")

        # Salvar relatório de métricas
        with open(pasta_saida / "relatorio_spike.json", "w", encoding="utf-8") as f:
            json.dump({
                "total": relatorio.total_documentos,
                "processados": relatorio.processados,
                "erros": relatorio.erros,
                "tempo_medio_ms": round(relatorio.tempo_medio_ms, 1),
                "confianca_media": round(relatorio.confiança_media, 4),
            }, f, ensure_ascii=False, indent=2)

        return relatorio


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Spike PaddleOCR — Caderneta E-11")
    parser.add_argument("--pasta", required=True, help="Pasta com PDFs/imagens")
    parser.add_argument("--saida", default="tests/fixtures/ground_truth")
    args = parser.parse_args()

    spike = SpikeOCR()
    relatorio = spike.rodar_spike(Path(args.pasta), Path(args.saida))
    print(relatorio.resumo())
    print(f"Resultados salvos em: {args.saida}/ocr_results.jsonl")

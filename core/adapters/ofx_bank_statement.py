"""OFXBankStatementAdapter — implementa BankStatementPort (Etapa 8.3).

Conecta o OFXParser existente ao BankStatementPort, convertendo
arquivos OFX em listas de TransacaoBancaria prontas para o MotorConciliacao.

Responsabilidade: conversão de formato externo (OFX) para domínio.
Não decide, não concilia — apenas importa.

Separação de responsabilidades:
  OFXParser              → já existia; extrai Documento do OFX
  OFXBankStatementAdapter → usa ofxparse diretamente (mais eficiente
                            do que passar por Documento) para extrair
                            TransacaoBancaria; também detecta ContaBancaria

Por que não reusar OFXParser?
  OFXParser produz Documento (com empresa_id gerado aleatoriamente,
  sem conta bancária, sem FITID como campo explícito). Para conciliação
  precisamos de TransacaoBancaria com FITID explícito e ContaBancaria.
  Mais limpo criar um adapter especializado do que contorcer o parser
  existente.

Idempotência: o caller deve verificar chave_idempotencia() antes de
  persistir — duas importações do mesmo OFX não devem criar duplicatas.
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from core.domain.entities import (
    ContaBancaria,
    Dinheiro,
    NaturezaLancamento,
    OrigemExtrato,
    TransacaoBancaria,
)


class OFXBankStatementAdapter:
    """Implementa BankStatementPort via ofxparse.

    Satisfaz BankStatementPort via duck typing.
    Importação lazy de ofxparse — não carregada até importar() ser chamado.
    """

    # ── BankStatementPort ─────────────────────────────────────────────────

    def importar(
        self,
        fonte: Path | str,
        empresa_id: UUID,
        id_importacao: str,
    ) -> list[TransacaoBancaria]:
        """Importa transações de um arquivo OFX.

        Args:
            fonte: caminho do arquivo OFX/QFX.
            empresa_id: UUID da empresa dona das transações.
            id_importacao: identificador único desta importação.

        Returns:
            Lista de TransacaoBancaria. O caller verifica idempotência
            via chave_idempotencia() antes de persistir.
        """
        from ofxparse import OfxParser as _OfxParser

        filepath = Path(fonte)
        transacoes: list[TransacaoBancaria] = []

        with open(filepath, "rb") as f:
            ofx = _OfxParser.parse(f)

        for conta in ofx.accounts:
            conta_bancaria = self._extrair_conta(conta)

            for tx in conta.statement.transactions:
                transacoes.append(
                    self._converter_transacao(
                        tx=tx,
                        conta_bancaria=conta_bancaria,
                        empresa_id=empresa_id,
                        id_importacao=id_importacao,
                    )
                )

        return transacoes

    def detectar_conta(self, fonte: Path | str) -> ContaBancaria | None:
        """Extrai ContaBancaria do arquivo sem importar todas as transações."""
        try:
            from ofxparse import OfxParser as _OfxParser

            with open(Path(fonte), "rb") as f:
                ofx = _OfxParser.parse(f)

            for conta in ofx.accounts:
                return self._extrair_conta(conta)
        except Exception:
            return None

        return None

    # ── Conversão interna ─────────────────────────────────────────────────

    def _extrair_conta(self, conta_ofx) -> ContaBancaria:
        """Extrai ContaBancaria de uma conta OFX."""
        numero = str(getattr(conta_ofx, "account_id", "") or "")
        # routing_number é o código de roteamento bancário (similar a agência+banco no BR)
        routing = str(getattr(conta_ofx, "routing_number", "") or "")
        tipo = str(getattr(conta_ofx, "account_type", "") or "corrente").lower()

        # Instituição: extrair código numérico do routing se disponível
        instituicao = routing[:3] if routing else "000"

        return ContaBancaria(
            instituicao=instituicao,
            agencia="",         # OFX BR frequentemente omite agência
            numero_conta=numero,
            tipo_conta=tipo,
        )

    def _converter_transacao(
        self,
        tx,
        conta_bancaria: ContaBancaria,
        empresa_id: UUID,
        id_importacao: str,
    ) -> TransacaoBancaria:
        """Converte uma transação ofxparse em TransacaoBancaria."""
        valor = Decimal(str(tx.amount))
        data_tx: date = (
            tx.date.date() if hasattr(tx.date, "date") else tx.date
        )

        fitid = str(getattr(tx, "id", "") or "")
        if not fitid:
            # Fallback: hash dos campos principais se FITID ausente
            import hashlib
            fitid = hashlib.md5(
                f"{data_tx}{valor}{getattr(tx, 'memo', '')}".encode()
            ).hexdigest()[:16]

        descricao = _limpar_descricao(
            getattr(tx, "payee", None) or getattr(tx, "memo", "")
        )
        referencia = str(getattr(tx, "checknum", "") or "")

        return TransacaoBancaria(
            empresa_id=empresa_id,
            conta_bancaria=conta_bancaria,
            fitid=fitid,
            data=data_tx,
            valor=Dinheiro(abs(valor)),
            natureza=(
                NaturezaLancamento.CREDITO if valor > 0
                else NaturezaLancamento.DEBITO
            ),
            descricao=descricao,
            referencia=referencia,
            origem=OrigemExtrato.OFX,
            id_importacao=id_importacao,
        )


def _limpar_descricao(texto: str) -> str:
    """Remove espaços extras, converte para maiúsculas."""
    if not texto:
        return ""
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto.upper()

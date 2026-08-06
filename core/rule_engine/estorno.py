"""Motor de Estorno Contábil — Emenda do Comitê, Etapa 4.

Estorno é uma partida dobrada reversa.
Não é rollback de sistema — é uma operação contábil autônoma.
O Core precisa saber estornar independente de interface ou IA.

Princípio: nunca apagar um lançamento. Sempre criar o estorno como
um novo lançamento que anula o original — rastreável no audit log.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

_UTC = timezone.utc


def _agora() -> datetime:
    """Retorna datetime UTC aware — substitui utcnow() depreciado."""
    return datetime.now(_UTC)
from decimal import Decimal
from uuid import uuid4

from core.domain.entities import (
    Lancamento,
    NaturezaLancamento,
    Split,
    StatusLancamento,
    NivelAprovacao,
)


@dataclass
class ResultadoEstorno:
    lancamento_estorno: Lancamento
    lancamento_original_id: str
    motivo: str
    gerado_por: str
    gerado_em: datetime = field(default_factory=_agora)


class MotorEstorno:
    """
    Gera lançamentos de estorno como partidas dobradas reversas.

    Regras contábeis aplicadas:
    1. O estorno nunca altera o lançamento original
    2. O estorno é um novo lançamento que inverte todos os splits
    3. A data do estorno é a data atual (não a data do lançamento original)
    4. O histórico do estorno referencia explicitamente o lançamento original
    5. O estorno requer o mesmo nível de aprovação que o original
    """

    def estornar(
        self,
        lancamento_original: Lancamento,
        motivo: str,
        responsavel: str,
        data_estorno: date | None = None,
    ) -> ResultadoEstorno:
        """
        Cria um lançamento de estorno invertendo todos os splits do original.
        """
        if lancamento_original.status == StatusLancamento.RASCUNHO:
            raise ValueError(
                "Não é possível estornar um lançamento em rascunho. "
                "Rejeite-o em vez de estornar."
            )

        if not lancamento_original.splits:
            raise ValueError(
                f"Lançamento {lancamento_original.id} não possui splits para estornar."
            )

        # Inverter cada split (débito vira crédito e vice-versa)
        splits_estorno = [
            Split(
                conta=split.conta,
                natureza=(
                    NaturezaLancamento.CREDITO
                    if split.natureza == NaturezaLancamento.DEBITO
                    else NaturezaLancamento.DEBITO
                ),
                valor=split.valor,
                centro_custo=split.centro_custo,
                descricao=f"Estorno: {split.descricao or ''}".strip(),
            )
            for split in lancamento_original.splits
        ]

        historico = (
            f"ESTORNO | Ref.: {str(lancamento_original.id)[:8].upper()} | "
            f"{lancamento_original.descricao[:40]} | "
            f"Motivo: {motivo[:60]}"
        )

        lancamento_estorno = Lancamento(
            empresa_id=lancamento_original.empresa_id,
            documento_id=lancamento_original.documento_id,
            fornecedor_id=lancamento_original.fornecedor_id,
            data_lancamento=data_estorno or date.today(),
            data_competencia=data_estorno or date.today(),
            descricao=historico,
            historico_padronizado=historico,
            splits=splits_estorno,
            categoria=lancamento_original.categoria,
            # Estorno precisa de aprovação — nunca é automático
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=lancamento_original.nivel_aprovacao or NivelAprovacao.UM_APROVADOR,
            pre_aprovado=False,
            # Rastreabilidade: aponta para o lançamento original
            lancamento_pai_id=lancamento_original.id,
        )

        # Verificar invariante de partidas dobradas no estorno
        lancamento_estorno.validar()

        return ResultadoEstorno(
            lancamento_estorno=lancamento_estorno,
            lancamento_original_id=str(lancamento_original.id),
            motivo=motivo,
            gerado_por=responsavel,
        )

    def pode_estornar(self, lancamento: Lancamento) -> tuple[bool, str]:
        """Verifica se um lançamento pode ser estornado."""
        if lancamento.status == StatusLancamento.RASCUNHO:
            return False, "Lançamentos em rascunho devem ser rejeitados, não estornados."

        if lancamento.status == StatusLancamento.REJEITADO:
            return False, "Lançamento já foi rejeitado."

        if not lancamento.splits:
            return False, "Lançamento sem splits não pode ser estornado."

        return True, ""

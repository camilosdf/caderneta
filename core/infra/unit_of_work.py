"""UnitOfWork — transação única para operações que tocam múltiplos repositórios.

Uso:
    with UnitOfWork(session_factory) as uow:
        uow.documentos.salvar(documento)
        uow.lancamentos.salvar(lancamento)
        uow.audit.registrar(tipo=..., payload=...)
        uow.commit()

Se uma exceção ocorrer antes de uow.commit(), o rollback é automático.
Se o bloco `with` terminar sem commit() explícito, também há rollback —
o commit precisa ser intencional, nunca implícito.
"""

from types import TracebackType
from typing import Optional

from core.infra.db.session import SessionFactory
from core.infra.repositories.audit_repository import AuditRepository
from core.infra.repositories.cartao_repository import (
    CartaoCreditoRepository,
    FaturaCartaoRepository,
    PagamentoFaturaCartaoRepository,
)
from core.infra.repositories.centro_custo_repository import CentroCustoRepository
from core.infra.repositories.conta_contabil_repository import ContaContabilRepository
from core.infra.repositories.documento_repository import DocumentoRepository
from core.infra.repositories.lancamento_repository import LancamentoRepository
from core.infra.repositories.periodo_contabil_repository import PeriodoContabilRepository
from core.infra.repositories.transacao_bancaria_repository import TransacaoBancariaRepository
from core.infra.repositories.usuario_repository import UsuarioRepository


class UnitOfWork:
    """Agrupa DocumentoRepository, LancamentoRepository, AuditRepository,
    PeriodoContabilRepository, CentroCustoRepository, ContaContabilRepository
    e UsuarioRepository em uma única transação.

    Commit é explícito — chamar uow.commit() é obrigatório para persistir.
    Sair do bloco `with` sem commit() reverte tudo.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session = None
        self._comitado = False

        self.documentos: Optional[DocumentoRepository] = None
        self.lancamentos: Optional[LancamentoRepository] = None
        self.audit: Optional[AuditRepository] = None
        self.periodos: Optional[PeriodoContabilRepository] = None
        self.centros_custo: Optional[CentroCustoRepository] = None
        self.contas_contabeis: Optional[ContaContabilRepository] = None
        self.usuarios: Optional[UsuarioRepository] = None
        self.transacoes_bancarias: Optional[TransacaoBancariaRepository] = None
        self.cartoes_credito: Optional[CartaoCreditoRepository] = None
        self.faturas_cartao: Optional[FaturaCartaoRepository] = None
        self.pagamentos_faturas_cartao: Optional[PagamentoFaturaCartaoRepository] = None

    def __enter__(self) -> "UnitOfWork":
        self._session = self._session_factory._session_factory()
        self._comitado = False

        self.documentos = DocumentoRepository(self._session)
        self.lancamentos = LancamentoRepository(self._session)
        self.audit = AuditRepository(self._session)
        self.periodos = PeriodoContabilRepository(self._session)
        self.centros_custo = CentroCustoRepository(self._session)
        self.contas_contabeis = ContaContabilRepository(self._session)
        self.usuarios = UsuarioRepository(self._session)
        self.transacoes_bancarias = TransacaoBancariaRepository(self._session)
        self.cartoes_credito = CartaoCreditoRepository(self._session)
        self.faturas_cartao = FaturaCartaoRepository(self._session)
        self.pagamentos_faturas_cartao = PagamentoFaturaCartaoRepository(self._session)

        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        try:
            if exc_type is not None:
                self._session.rollback()
            elif not self._comitado:
                # Saiu do bloco `with` sem commit() explícito — reverte por segurança
                self._session.rollback()
        finally:
            self._session.close()
            self.documentos = None
            self.lancamentos = None
            self.audit = None
            self.periodos = None
            self.centros_custo = None
            self.contas_contabeis = None
            self.usuarios = None
            self.transacoes_bancarias = None
            self.cartoes_credito = None
            self.faturas_cartao = None
            self.pagamentos_faturas_cartao = None

    def commit(self) -> None:
        """Confirma todas as operações realizadas nos repositórios desta UoW."""
        self._session.commit()
        self._comitado = True

    def rollback(self) -> None:
        """Reverte todas as operações não confirmadas."""
        self._session.rollback()
        self._comitado = False

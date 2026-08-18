"""Testes do ContaContabilRepository — DT-CC-01 / ADR 011, etapa B.2.1.

Cobre: criar, salvar, buscar por código, listar por empresa, mapa_por_codigo
para uso com LancamentoService em lote, unicidade (empresa_id, codigo).

Escopo desta etapa (B.2.1): cadastro apenas. Nenhuma FK está ativa ainda
entre splits e contas_contabeis (ver ADR 011, sequência B.2.1-B.2.4) —
não testado aqui, é objeto de B.2.4.
"""

from uuid import uuid4

import pytest

from core.domain.entities import CodigoConta, ContaContabil, NaturezaLancamento
from core.infra.db import SessionFactory
from core.infra.repositories import ContaContabilRepository
from core.infra.repositories.conta_contabil_repository import ContaContabilJaExisteError


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


class TestContaContabilRepository:
    def test_salvar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        conta = ContaContabil(
            empresa_id=empresa_id, codigo=CodigoConta("4.1.01.001"), nome="Despesas Operacionais",
        )
        with sf.session() as session:
            ContaContabilRepository(session).salvar(conta)

        with sf.session() as session:
            encontrada = ContaContabilRepository(session).buscar_por_id(conta.id)
            assert encontrada is not None
            assert encontrada.codigo.codigo == "4.1.01.001"
            assert encontrada.nome == "Despesas Operacionais"

    def test_buscar_por_codigo(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        conta = ContaContabil(
            empresa_id=empresa_id, codigo=CodigoConta("1.1.01.002"), nome="Caixa",
        )
        with sf.session() as session:
            ContaContabilRepository(session).salvar(conta)

        with sf.session() as session:
            encontrada = ContaContabilRepository(session).buscar_por_codigo(
                empresa_id, "1.1.01.002"
            )
            assert encontrada is not None
            assert encontrada.id == conta.id

    def test_buscar_codigo_inexistente_retorna_none(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            resultado = ContaContabilRepository(session).buscar_por_codigo(
                uuid4(), "9.9.99.999"
            )
            assert resultado is None

    def test_criar_nova_conta(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            conta = ContaContabilRepository(session).criar(
                empresa_id, "4.1.01.003", "Combustível",
            )
            assert conta.permite_lancamento is True
            assert conta.natureza == NaturezaLancamento.DEBITO

        with sf.session() as session:
            encontrada = ContaContabilRepository(session).buscar_por_codigo(
                empresa_id, "4.1.01.003"
            )
            assert encontrada is not None

    def test_criar_codigo_duplicado_lanca_erro(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            ContaContabilRepository(session).criar(empresa_id, "2.1.05.001", "Cartão Nubank")

        with pytest.raises(ContaContabilJaExisteError):
            with sf.session() as session:
                ContaContabilRepository(session).criar(
                    empresa_id, "2.1.05.001", "Duplicada"
                )

    def test_mesmo_codigo_empresas_diferentes_permitido(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = ContaContabilRepository(session)
            repo.criar(uuid4(), "4.1.01.005", "Empresa A")
            repo.criar(uuid4(), "4.1.01.005", "Empresa B")
        # não deve lançar erro — códigos são únicos por empresa, não globalmente

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = ContaContabilRepository(session)
            repo.criar(empresa_id, "4.1.01.006", "A")
            repo.criar(empresa_id, "4.1.01.007", "B")
            repo.criar(uuid4(), "4.1.01.008", "Outra empresa")

        with sf.session() as session:
            lista = ContaContabilRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_mapa_por_codigo(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = ContaContabilRepository(session)
            repo.criar(empresa_id, "4.1.01.009", "A")
            repo.criar(empresa_id, "4.1.01.010", "B")

        with sf.session() as session:
            mapa = ContaContabilRepository(session).mapa_por_codigo(empresa_id)
            assert "4.1.01.009" in mapa
            assert "4.1.01.010" in mapa
            assert len(mapa) == 2

    def test_unique_constraint_empresa_codigo(self, sf: SessionFactory) -> None:
        from sqlalchemy.exc import IntegrityError
        empresa_id = uuid4()
        with pytest.raises(IntegrityError):
            with sf.session() as session:
                repo = ContaContabilRepository(session)
                repo.salvar(ContaContabil(
                    empresa_id=empresa_id, codigo=CodigoConta("4.1.01.011"), nome="A",
                ))
                repo.salvar(ContaContabil(
                    empresa_id=empresa_id, codigo=CodigoConta("4.1.01.011"), nome="B",
                ))

    def test_campos_persistidos_no_round_trip(self, sf: SessionFactory) -> None:
        """Round-trip de todos os campos, não só codigo/nome — inclusive
        guid_gnucash e centro_custo_obrigatorio, usados por
        LancamentoService e pela integração GnuCash (D18)."""
        empresa_id = uuid4()
        conta = ContaContabil(
            empresa_id=empresa_id,
            codigo=CodigoConta("4.1.01.012"),
            nome="Requer CC",
            tipo="despesa",
            natureza=NaturezaLancamento.DEBITO,
            guid_gnucash="11111111-1111-1111-1111-111111111111",
            permite_lancamento=True,
            centro_custo_obrigatorio=True,
        )
        with sf.session() as session:
            ContaContabilRepository(session).salvar(conta)

        with sf.session() as session:
            encontrada = ContaContabilRepository(session).buscar_por_codigo(
                empresa_id, "4.1.01.012"
            )
            assert encontrada.tipo == "despesa"
            assert encontrada.natureza == NaturezaLancamento.DEBITO
            assert encontrada.guid_gnucash == "11111111-1111-1111-1111-111111111111"
            assert encontrada.centro_custo_obrigatorio is True

    def test_conta_nao_lancavel_round_trip(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        conta = ContaContabil(
            empresa_id=empresa_id, codigo=CodigoConta("4.1.01"), nome="Sintética",
            permite_lancamento=False,
        )
        with sf.session() as session:
            ContaContabilRepository(session).salvar(conta)

        with sf.session() as session:
            encontrada = ContaContabilRepository(session).buscar_por_codigo(
                empresa_id, "4.1.01"
            )
            assert encontrada.permite_lancamento is False
            with pytest.raises(ValueError):
                encontrada.validar_para_lancamento()


class TestSplitEmpresaIdSchemaB21:
    """Contrato explícito da etapa B.2.1: splits.empresa_id existe e é
    nullable. Nenhum código ainda o popula (isso é B.2.2) e nenhuma FK
    o usa (isso é B.2.4) — este teste documenta o estado intermediário
    e deve ser atualizado (não removido silenciosamente) quando B.2.2
    tornar a coluna obrigatoriamente populada."""

    def test_split_sem_empresa_id_ainda_e_aceito(self, sf: SessionFactory) -> None:
        from datetime import date
        from decimal import Decimal

        from core.domain.entities import (
            Dinheiro,
            Lancamento,
            NivelAprovacao,
            Split,
            StatusLancamento,
        )
        from core.infra.repositories import LancamentoRepository

        lancamento = Lancamento(
            data_lancamento=date(2026, 8, 18),
            descricao="teste B.2.1",
            status=StatusLancamento.APROVADO,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
            splits=[
                Split(conta=CodigoConta("4.1.01.001"), natureza=NaturezaLancamento.DEBITO,
                      valor=Dinheiro(Decimal("10.00"))),
                Split(conta=CodigoConta("1.1.01.002"), natureza=NaturezaLancamento.CREDITO,
                      valor=Dinheiro(Decimal("10.00"))),
            ],
        )
        lancamento.validar()
        with sf.session() as session:
            LancamentoRepository(session).salvar(lancamento)

        # Confirma via ORM direto (não via domínio, que não expõe
        # empresa_id em Split) que a coluna existe e ficou None — B.2.1
        # não popula, só declara o schema.
        from core.infra.db.models import SplitORM
        with sf.session() as session:
            orm = session.get(SplitORM, str(lancamento.splits[0].id))
            assert orm is not None
            assert orm.empresa_id is None

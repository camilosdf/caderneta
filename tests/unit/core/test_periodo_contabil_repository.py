"""Testes do PeriodoContabilRepository.

Cobre: salvar, buscar por competência, obter_ou_criar, listar por empresa,
mapa_por_competencia para uso com LancamentoService em lote.
"""

from uuid import uuid4

import pytest

from core.domain.entities import PeriodoContabil, StatusPeriodo
from core.infra.db import SessionFactory
from core.infra.repositories import PeriodoContabilRepository


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


class TestPeriodoContabilRepository:
    def test_salvar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        periodo = PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=3)
        with sf.session() as session:
            PeriodoContabilRepository(session).salvar(periodo)

        with sf.session() as session:
            encontrado = PeriodoContabilRepository(session).buscar_por_id(periodo.id)
            assert encontrado is not None
            assert encontrado.ano == 2024
            assert encontrado.mes == 3

    def test_buscar_por_competencia(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        periodo = PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=3)
        with sf.session() as session:
            PeriodoContabilRepository(session).salvar(periodo)

        with sf.session() as session:
            encontrado = PeriodoContabilRepository(session).buscar_por_competencia(
                empresa_id, 2024, 3
            )
            assert encontrado is not None
            assert encontrado.id == periodo.id

    def test_buscar_competencia_inexistente_retorna_none(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            resultado = PeriodoContabilRepository(session).buscar_por_competencia(
                uuid4(), 2024, 3
            )
            assert resultado is None

    def test_obter_ou_criar_cria_se_nao_existe(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            periodo = PeriodoContabilRepository(session).obter_ou_criar(empresa_id, 2024, 5)
            assert periodo.status == StatusPeriodo.ABERTO

        with sf.session() as session:
            encontrado = PeriodoContabilRepository(session).buscar_por_competencia(
                empresa_id, 2024, 5
            )
            assert encontrado is not None

    def test_obter_ou_criar_retorna_existente(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = PeriodoContabilRepository(session)
            p1 = repo.obter_ou_criar(empresa_id, 2024, 6)
            p1.fechar("gerente")
            repo.salvar(p1)

        with sf.session() as session:
            p2 = PeriodoContabilRepository(session).obter_ou_criar(empresa_id, 2024, 6)
            assert p2.status == StatusPeriodo.FECHADO
            assert p2.fechado_por == "gerente"

    def test_fechar_persiste_status(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        periodo = PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=7)
        with sf.session() as session:
            PeriodoContabilRepository(session).salvar(periodo)

        with sf.session() as session:
            repo = PeriodoContabilRepository(session)
            p = repo.buscar_por_competencia(empresa_id, 2024, 7)
            p.fechar("supervisor")
            repo.salvar(p)

        with sf.session() as session:
            p = PeriodoContabilRepository(session).buscar_por_competencia(empresa_id, 2024, 7)
            assert p.status == StatusPeriodo.FECHADO
            assert p.fechado_por == "supervisor"
            assert p.fechado_em is not None

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = PeriodoContabilRepository(session)
            repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=1))
            repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=2))
            repo.salvar(PeriodoContabil(empresa_id=uuid4(), ano=2024, mes=1))

        with sf.session() as session:
            lista = PeriodoContabilRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_listar_por_empresa_filtra_status(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = PeriodoContabilRepository(session)
            aberto = PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=1)
            fechado = PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=2)
            fechado.fechar("gerente")
            repo.salvar(aberto)
            repo.salvar(fechado)

        with sf.session() as session:
            abertos = PeriodoContabilRepository(session).listar_por_empresa(
                empresa_id, status=StatusPeriodo.ABERTO
            )
            assert len(abertos) == 1
            assert abertos[0].mes == 1

    def test_mapa_por_competencia(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = PeriodoContabilRepository(session)
            repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=1))
            repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=2))

        with sf.session() as session:
            mapa = PeriodoContabilRepository(session).mapa_por_competencia(empresa_id)
            assert (2024, 1) in mapa
            assert (2024, 2) in mapa
            assert len(mapa) == 2

    def test_unique_constraint_empresa_ano_mes(self, sf: SessionFactory) -> None:
        from sqlalchemy.exc import IntegrityError
        empresa_id = uuid4()
        with pytest.raises(IntegrityError):
            with sf.session() as session:
                repo = PeriodoContabilRepository(session)
                repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=3))
                repo.salvar(PeriodoContabil(empresa_id=empresa_id, ano=2024, mes=3))

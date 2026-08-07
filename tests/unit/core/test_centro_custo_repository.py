"""Testes do CentroCustoRepository.

Cobre: criar, salvar, buscar por código, listar por empresa, ativos/inativos,
mapa_por_codigo para uso com LancamentoService em lote.
"""

from uuid import uuid4

import pytest

from core.domain.entities import CentroCusto
from core.infra.db import SessionFactory
from core.infra.repositories import CentroCustoRepository
from core.infra.repositories.centro_custo_repository import CentroCustoJaExisteError


@pytest.fixture
def sf() -> SessionFactory:
    factory = SessionFactory("sqlite:///:memory:")
    factory.criar_tabelas()
    return factory


class TestCentroCustoRepository:
    def test_salvar_e_buscar_por_id(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        centro = CentroCusto(empresa_id=empresa_id, codigo="CC-001", nome="Vendas")
        with sf.session() as session:
            CentroCustoRepository(session).salvar(centro)

        with sf.session() as session:
            encontrado = CentroCustoRepository(session).buscar_por_id(centro.id)
            assert encontrado is not None
            assert encontrado.codigo == "CC-001"
            assert encontrado.nome == "Vendas"

    def test_buscar_por_codigo(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        centro = CentroCusto(empresa_id=empresa_id, codigo="CC-002", nome="Marketing")
        with sf.session() as session:
            CentroCustoRepository(session).salvar(centro)

        with sf.session() as session:
            encontrado = CentroCustoRepository(session).buscar_por_codigo(empresa_id, "CC-002")
            assert encontrado is not None
            assert encontrado.id == centro.id

    def test_buscar_codigo_inexistente_retorna_none(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            resultado = CentroCustoRepository(session).buscar_por_codigo(uuid4(), "NAO-EXISTE")
            assert resultado is None

    def test_criar_novo_centro(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            centro = CentroCustoRepository(session).criar(empresa_id, "CC-003", "TI")
            assert centro.ativo is True

        with sf.session() as session:
            encontrado = CentroCustoRepository(session).buscar_por_codigo(empresa_id, "CC-003")
            assert encontrado is not None

    def test_criar_codigo_duplicado_lanca_erro(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            CentroCustoRepository(session).criar(empresa_id, "CC-004", "Financeiro")

        with pytest.raises(CentroCustoJaExisteError):
            with sf.session() as session:
                CentroCustoRepository(session).criar(empresa_id, "CC-004", "Duplicado")

    def test_mesmo_codigo_empresas_diferentes_permitido(self, sf: SessionFactory) -> None:
        with sf.session() as session:
            repo = CentroCustoRepository(session)
            repo.criar(uuid4(), "CC-005", "Empresa A")
            repo.criar(uuid4(), "CC-005", "Empresa B")
        # não deve lançar erro — códigos são únicos por empresa, não globalmente

    def test_listar_por_empresa(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = CentroCustoRepository(session)
            repo.criar(empresa_id, "CC-006", "A")
            repo.criar(empresa_id, "CC-007", "B")
            repo.criar(uuid4(), "CC-008", "Outra empresa")

        with sf.session() as session:
            lista = CentroCustoRepository(session).listar_por_empresa(empresa_id)
            assert len(lista) == 2

    def test_listar_apenas_ativos(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = CentroCustoRepository(session)
            repo.criar(empresa_id, "CC-009", "Ativo")
            inativo = repo.criar(empresa_id, "CC-010", "Inativo")
            inativo.ativo = False
            repo.salvar(inativo)

        with sf.session() as session:
            ativos = CentroCustoRepository(session).listar_por_empresa(
                empresa_id, apenas_ativos=True
            )
            assert len(ativos) == 1
            assert ativos[0].codigo == "CC-009"

    def test_desativar_e_reativar(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = CentroCustoRepository(session)
            centro = repo.criar(empresa_id, "CC-011", "Toggle")

        with sf.session() as session:
            repo = CentroCustoRepository(session)
            c = repo.buscar_por_codigo(empresa_id, "CC-011")
            c.ativo = False
            repo.salvar(c)

        with sf.session() as session:
            c = CentroCustoRepository(session).buscar_por_codigo(empresa_id, "CC-011")
            assert c.ativo is False

        with sf.session() as session:
            repo = CentroCustoRepository(session)
            c = repo.buscar_por_codigo(empresa_id, "CC-011")
            c.ativo = True
            repo.salvar(c)

        with sf.session() as session:
            c = CentroCustoRepository(session).buscar_por_codigo(empresa_id, "CC-011")
            assert c.ativo is True

    def test_mapa_por_codigo(self, sf: SessionFactory) -> None:
        empresa_id = uuid4()
        with sf.session() as session:
            repo = CentroCustoRepository(session)
            repo.criar(empresa_id, "CC-012", "A")
            repo.criar(empresa_id, "CC-013", "B")

        with sf.session() as session:
            mapa = CentroCustoRepository(session).mapa_por_codigo(empresa_id)
            assert "CC-012" in mapa
            assert "CC-013" in mapa
            assert len(mapa) == 2

    def test_unique_constraint_empresa_codigo(self, sf: SessionFactory) -> None:
        from sqlalchemy.exc import IntegrityError
        empresa_id = uuid4()
        with pytest.raises(IntegrityError):
            with sf.session() as session:
                repo = CentroCustoRepository(session)
                repo.salvar(CentroCusto(empresa_id=empresa_id, codigo="CC-014", nome="A"))
                repo.salvar(CentroCusto(empresa_id=empresa_id, codigo="CC-014", nome="B"))

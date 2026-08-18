"""Teste de D18 (ADR 010) — validação do mapeamento GnuCash via ExportadorCSV.

D18 decide "sem alteração no exportador; validar mapeamento via teste" —
ou seja, a decisão já aprovada (`docs/adr/010-fatura-cartao-credito.md:521`)
é que `ExportadorCSV` deveria funcionar sem modificação para lançamentos
de cartão, porque D7 (compra) e D8 (pagamento) produzem `Lancamento`/
`Split` comuns, sem nenhum campo novo. O que faltava era só a evidência
de teste — nenhum código de produção é alterado por este arquivo.

Fluxo real, não fixtures artificiais: FaturaCartao persistida e fechada
-> GerarLancamentosFaturaCartaoUseCase (B6-0) gera e persiste D7 (compra)
e D8 (pagamento) -> lançamentos recarregados do banco -> ExportadorCSV
(sem alteração) -> confirma que a conta de Passivo do cartão (D6,
conta_codigo textual) aparece corretamente mapeada nas duas pontas:
crédito na compra (aumenta o passivo), débito no pagamento (baixa o
passivo) — mesmo conta_codigo, direções opostas.

CartaoCredito.guid_gnucash é preenchido no fixture e deliberadamente
NÃO verificado no CSV — comprova que o exportador mapeia corretamente
sem depender desse campo, confirmando a hipótese de D18 de que nenhuma
alteração no exportador é necessária.
"""

import csv
from datetime import date
from decimal import Decimal
from uuid import uuid4

from core.adapters.csv_exporter import ExportadorCSV
from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
    GerarLancamentosFaturaCartaoUseCase,
)
from core.domain.entities import (
    CartaoCredito,
    CodigoConta,
    CompraCartao,
    Dinheiro,
    FaturaCartao,
    TipoItemFatura,
)
from core.infra.db.session import SessionFactory
from core.infra.unit_of_work import UnitOfWork

CONTA_CARTAO = CodigoConta("2.1.05.001")
CONTA_BANCO = CodigoConta("1.1.01.001")
CONTAS_DESPESA = {
    TipoItemFatura.COMPRA: CodigoConta("4.1.01.001"),
}


def _session_factory() -> SessionFactory:
    sf = SessionFactory("sqlite:///:memory:")
    sf.criar_tabelas()
    return sf


class TestD18ExportacaoGnucash:
    def test_conta_passivo_do_cartao_mapeada_corretamente_compra_e_pagamento(
        self, tmp_path
    ) -> None:
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = CartaoCredito(
                empresa_id=empresa_id, emissor="Nubank", final_numero="1234",
                titular="Camilo", conta_codigo=CONTA_CARTAO,
                # Preenchido deliberadamente — o exportador não deve
                # precisar dele para mapear a conta corretamente (D18).
                guid_gnucash="00000000-0000-0000-0000-000000000001",
            )
            uow.cartoes_credito.salvar_se_novo(cartao)

            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("250.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("250.00")), posicao_linha=1,
                estabelecimento="MERCADO TESTE",
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )

        with UnitOfWork(sf) as uow2:
            lancamento_compra = uow2.lancamentos.buscar_por_id(
                resultado.lancamentos_compra_ids[0]
            )
            lancamento_pagamento = uow2.lancamentos.buscar_por_id(
                resultado.lancamento_pagamento_id
            )

        exportador = ExportadorCSV()
        exportado = exportador.exportar(
            [lancamento_compra, lancamento_pagamento], tmp_path
        )
        assert exportado.conferencia.valido is True

        with open(exportado.caminho, encoding="utf-8-sig", newline="") as f:
            linhas = list(csv.DictReader(f, delimiter=";"))

        linhas_conta_cartao = [
            l for l in linhas if l["Account"] == CONTA_CARTAO.codigo
        ]
        # D7 (compra) credita conta_cartao (aumenta o Passivo) e
        # D8 (pagamento) debita conta_cartao (baixa o Passivo) — mesma
        # conta, duas linhas, direções opostas.
        assert len(linhas_conta_cartao) == 2

        linha_compra = next(
            l for l in linhas_conta_cartao if l["Withdrawal"] == "250,00"
        )
        assert linha_compra["Deposit"] == ""

        linha_pagamento = next(
            l for l in linhas_conta_cartao if l["Deposit"] == "250,00"
        )
        assert linha_pagamento["Withdrawal"] == ""

        # guid_gnucash não é usado pelo exportador — nenhuma coluna do
        # CSV carrega esse valor; o mapeamento depende só de conta_codigo.
        conteudo_bruto = exportado.caminho.read_text(encoding="utf-8-sig")
        assert "00000000-0000-0000-0000-000000000001" not in conteudo_bruto

    def test_lancamento_de_compra_cartao_sozinho_exporta_sem_erro(
        self, tmp_path
    ) -> None:
        """Confirma que D7 isolado (sem D8) já é suficiente para o
        exportador genérico funcionar — não há dependência oculta em
        ambos os lançamentos estarem presentes juntos."""
        sf = _session_factory()
        empresa_id = uuid4()

        with UnitOfWork(sf) as uow:
            cartao = CartaoCredito(
                empresa_id=empresa_id, emissor="Nubank", final_numero="5678",
                titular="Camilo", conta_codigo=CONTA_CARTAO,
            )
            uow.cartoes_credito.salvar_se_novo(cartao)
            fatura = FaturaCartao(
                empresa_id=empresa_id, cartao_id=cartao.id,
                periodo_referencia=date(2026, 8, 1), data_vencimento=date(2026, 9, 15),
                valor_total_declarado=Dinheiro(Decimal("80.00")),
            )
            fatura.itens.append(CompraCartao(
                empresa_id=empresa_id, tipo=TipoItemFatura.COMPRA,
                valor=Dinheiro(Decimal("80.00")), posicao_linha=1,
                estabelecimento="FARMACIA TESTE",
            ))
            fatura.validar_fechamento()
            uow.faturas_cartao.salvar_se_nova(fatura)
            uow.commit()
            fatura_id = fatura.id

        uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)
        resultado = uc.executar(
            fatura_id, conta_cartao=CONTA_CARTAO, conta_banco=CONTA_BANCO,
            contas_despesa_por_tipo=CONTAS_DESPESA,
        )
        with UnitOfWork(sf) as uow2:
            lancamento_compra = uow2.lancamentos.buscar_por_id(
                resultado.lancamentos_compra_ids[0]
            )

        exportador = ExportadorCSV()
        exportado = exportador.exportar([lancamento_compra], tmp_path)
        assert exportado.conferencia.valido is True
        conteudo = exportado.caminho.read_text(encoding="utf-8-sig")
        assert CONTA_CARTAO.codigo in conteudo
        assert CONTAS_DESPESA[TipoItemFatura.COMPRA].codigo in conteudo

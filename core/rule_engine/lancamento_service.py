"""LancamentoService — Motor Contábil (Etapa 4/5).

Consolida em um único lugar as regras que hoje estavam espalhadas
entre ProcessarDocumentoUseCase._construir_lancamento e core/cli.py:

  1. Gerar splits a partir de uma Sugestao de classificação
  2. Validar balanço (débitos = créditos) — já existe em Lancamento.validar()
  3. Validar período contábil aberto
  4. Validar centro de custo obrigatório por conta
  5. Persistir via LancamentoRepository (injetado pela UnitOfWork)

Este serviço não decide categoria/conta — isso é responsabilidade do
ClassificationPort. O LancamentoService apenas garante que o lançamento
resultante é estruturalmente e contabilmente válido antes de persistir.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from core.domain.entities import (
    CentroCusto,
    CodigoConta,
    CompraCartao,
    ContaContabil,
    Dinheiro,
    Documento,
    FaturaCartao,
    Lancamento,
    NaturezaLancamento,
    NivelAprovacao,
    PeriodoContabil,
    Split,
    StatusLancamento,
)
from core.ports.classification import Sugestao


class PeriodoFechadoError(Exception):
    """Lançamento rejeitado — período contábil já fechado."""
    pass


class CentroCustoObrigatorioError(Exception):
    """Lançamento rejeitado — conta exige centro de custo e nenhum foi informado."""
    pass


class ContaNaoLancavelError(Exception):
    """Lançamento rejeitado — conta é sintética ou não permite lançamentos."""
    pass


class LancamentoService:
    """Motor Contábil — constrói, valida e persiste Lancamento.

    Recebe repositórios de contas/período/centro de custo opcionalmente;
    quando não fornecidos, as validações correspondentes são puladas
    (uso em contextos onde o plano de contas ainda não está cadastrado,
    ex.: pipeline inicial ou testes).
    """

    def __init__(
        self,
        contas_por_codigo: Optional[dict[str, ContaContabil]] = None,
        centros_por_codigo: Optional[dict[str, CentroCusto]] = None,
        periodo_atual: Optional[PeriodoContabil] = None,
        periodos_por_competencia: Optional[dict[tuple[int, int], PeriodoContabil]] = None,
    ) -> None:
        self._contas = contas_por_codigo or {}
        self._centros = centros_por_codigo or {}
        self._periodo = periodo_atual
        self._periodos = periodos_por_competencia or {}

    # ── Construção ───────────────────────────────────────────────────────

    def construir(
        self,
        documento: Documento,
        sugestao: Sugestao,
    ) -> Lancamento:
        """Gera um Lancamento a partir de um Documento e uma Sugestao de classificação.

        Não persiste — apenas monta o agregado em memória.
        """
        valor = documento.valor_liquido or documento.valor_total
        if valor is None:
            valor = Dinheiro(Decimal("0"))

        splits = self._gerar_splits(sugestao, valor)

        lancamento = Lancamento(
            empresa_id=documento.empresa_id,
            documento_id=documento.id,
            data_lancamento=documento.data_emissao,
            descricao=documento.nome_emitente or "SEM DESCRIÇÃO",
            splits=splits,
            categoria=sugestao.categoria,
            confidence=sugestao.confidence,
            metodo_classificacao=sugestao.metodo,
            regra_aplicada_id=sugestao.regra_aplicada_id,
            versao_regra=sugestao.versao_regra,
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )

        return lancamento

    def _gerar_splits(self, sugestao: Sugestao, valor: Dinheiro) -> list[Split]:
        if not (sugestao.conta_debito and sugestao.conta_credito):
            return []
        return [
            Split(
                conta=sugestao.conta_debito,
                natureza=NaturezaLancamento.DEBITO,
                valor=valor,
                centro_custo=sugestao.centro_custo,
            ),
            Split(
                conta=sugestao.conta_credito,
                natureza=NaturezaLancamento.CREDITO,
                valor=valor,
                centro_custo=sugestao.centro_custo,
            ),
        ]

    # ── Validação ────────────────────────────────────────────────────────

    def validar(self, lancamento: Lancamento) -> None:
        """Executa todas as validações do Motor Contábil, em ordem.

        Lança a primeira exceção encontrada. Não retorna nada em caso de sucesso.
        """
        if not lancamento.splits:
            raise ValueError("Lançamento sem splits.")

        # 1. Balanço contábil (débitos = créditos)
        lancamento.validar()

        # 2. Período contábil aberto
        self._validar_periodo(lancamento)

        # 3. Contas lançáveis + centro de custo obrigatório
        self._validar_contas_e_centro_custo(lancamento)

    def _validar_periodo(self, lancamento: Lancamento) -> None:
        if lancamento.data_lancamento is None:
            return

        competencia = (lancamento.data_lancamento.year, lancamento.data_lancamento.month)

        # Prioridade 1: mapa de múltiplas competências (uso em lote/CLI)
        if self._periodos:
            periodo = self._periodos.get(competencia)
            if periodo is not None:
                self._verificar_periodo_aberto(periodo)
            return

        # Prioridade 2: período único injetado (uso simples/testes)
        if self._periodo is None:
            return
        if (self._periodo.ano, self._periodo.mes) != competencia:
            return  # período informado não corresponde à data do lançamento
        self._verificar_periodo_aberto(self._periodo)

    def _verificar_periodo_aberto(self, periodo: PeriodoContabil) -> None:
        """Relança como PeriodoFechadoError — a exceção específica já
        estava definida neste módulo mas nunca era efetivamente lançada;
        o código anterior deixava propagar o ValueError genérico de
        PeriodoContabil.verificar_aberto() (achado registrado no ADR 008,
        corrigido no W3 — necessário para o mapeamento HTTP 409 funcionar
        como descrito no ADR)."""
        try:
            periodo.verificar_aberto()
        except ValueError as e:
            raise PeriodoFechadoError(str(e)) from e

    def _validar_contas_e_centro_custo(self, lancamento: Lancamento) -> None:
        for split in lancamento.splits:
            conta = self._contas.get(split.conta.codigo)
            if conta is not None:
                try:
                    conta.validar_para_lancamento()
                except ValueError as e:
                    raise ContaNaoLancavelError(str(e)) from e

                if conta.centro_custo_obrigatorio and not split.centro_custo:
                    raise CentroCustoObrigatorioError(
                        f"Conta {conta.codigo.codigo} exige centro de custo, "
                        f"nenhum foi informado no split."
                    )

            if split.centro_custo and self._centros:
                centro = self._centros.get(split.centro_custo)
                if centro is not None and not centro.ativo:
                    raise ValueError(
                        f"Centro de custo '{split.centro_custo}' está inativo."
                    )

    # ── Construção + Validação combinadas ───────────────────────────────

    def processar(self, documento: Documento, sugestao: Sugestao) -> Lancamento:
        """Constrói e valida um Lancamento em uma única chamada.

        Se a validação falhar por ausência de splits (sugestão sem contas),
        o lançamento é retornado sem levantar exceção — cabe ao chamador
        decidir o que fazer com um lançamento vazio (ex.: marcar para revisão).
        """
        lancamento = self.construir(documento, sugestao)
        if lancamento.splits:
            self.validar(lancamento)
        return lancamento

    # ── ADR 010 — Cartão de Crédito (Fase 3: D7, D8) ───────────────────────
    #
    # Métodos dedicados, deliberadamente separados de construir()/
    # _gerar_splits() (que operam sobre Documento+Sugestao — um par de
    # splits por documento). CompraCartao e FaturaCartao representam dois
    # fatos contábeis distintos (aquisição vs. liquidação do passivo) que
    # NÃO podem ser encaixados no mesmo caminho sem violar D7/D8 — ver
    # Gate de Fase 3, "não aceitar implementação que simplesmente encaixe
    # cartão no comportamento atual de _gerar_splits".
    #
    # Nenhuma conta é decidida aqui — mesmo princípio já documentado para
    # Sugestao ("Este serviço não decide categoria/conta"). conta_despesa,
    # conta_cartao e conta_banco são sempre fornecidos pelo chamador.

    def construir_lancamento_compra_cartao(
        self,
        compra: CompraCartao,
        conta_despesa: CodigoConta,
        conta_cartao: CodigoConta,
    ) -> Lancamento:
        """D7 — Lançamento de aquisição de um item de fatura de cartão.

        Compra/juros/multa/IOF/encargo/anuidade (D9, D10):
            D — conta_despesa (financeira ou operacional, conforme o
                tipo já classificado em CompraCartao.tipo — Fase 2)
            C — conta_cartao (Passivo do cartão)

        Estorno (D11 — inversão, não incorporação):
            D — conta_cartao (reduz o passivo)
            C — conta_despesa

        Um lançamento por CompraCartao — nunca agregado com outros
        itens da mesma fatura. O valor lançado é sempre compra.valor
        (o total da compra, mesmo quando parcelada — D12).
        """
        if compra.e_estorno:
            conta_debito, conta_credito = conta_cartao, conta_despesa
        else:
            conta_debito, conta_credito = conta_despesa, conta_cartao

        splits = [
            Split(
                conta=conta_debito,
                natureza=NaturezaLancamento.DEBITO,
                valor=compra.valor,
            ),
            Split(
                conta=conta_credito,
                natureza=NaturezaLancamento.CREDITO,
                valor=compra.valor,
            ),
        ]

        lancamento = Lancamento(
            empresa_id=compra.empresa_id,
            data_lancamento=compra.data_compra,
            data_competencia=compra.data_compra,
            descricao=(
                compra.estabelecimento
                or compra.descricao_original
                or compra.tipo.value
            ),
            splits=splits,
            # D12 — metadado informativo apenas; nenhum lançamento
            # mensal adicional é gerado a partir dele.
            e_parcelado=bool(compra.parcela_atual and compra.total_parcelas),
            parcela_atual=compra.parcela_atual,
            total_parcelas=compra.total_parcelas,
            categoria=compra.tipo.value,
            confidence=compra.confidence.valor if compra.confidence else None,
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        lancamento.validar()  # equilíbrio D=C
        return lancamento

    def construir_lancamento_pagamento_fatura(
        self,
        fatura: FaturaCartao,
        conta_cartao: CodigoConta,
        conta_banco: CodigoConta,
    ) -> Lancamento:
        """D8 — Lançamento de liquidação (pagamento) de uma fatura de cartão.

            D — conta_cartao (baixa do Passivo)
            C — conta_banco (saída do Ativo)

        Um ÚNICO lançamento agregado por fatura, no valor total
        declarado (fatura.valor_total_declarado) — nunca um lançamento
        por CompraCartao. Este método não itera fatura.itens; não
        existe caminho neste serviço que transforme compras individuais
        em lançamentos de pagamento (ver teste negativo dedicado).
        """
        splits = [
            Split(
                conta=conta_cartao,
                natureza=NaturezaLancamento.DEBITO,
                valor=fatura.valor_total_declarado,
            ),
            Split(
                conta=conta_banco,
                natureza=NaturezaLancamento.CREDITO,
                valor=fatura.valor_total_declarado,
            ),
        ]

        lancamento = Lancamento(
            empresa_id=fatura.empresa_id,
            data_lancamento=fatura.data_vencimento,
            descricao=f"Pagamento fatura cartão — período {fatura.periodo_referencia}",
            splits=splits,
            status=StatusLancamento.PENDENTE,
            nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
        )
        lancamento.validar()  # equilíbrio D=C
        return lancamento

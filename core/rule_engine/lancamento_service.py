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
    ContaContabil,
    Dinheiro,
    Documento,
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

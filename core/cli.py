"""Interface de linha de comando — Caderneta v0.3.

Subcomandos disponíveis:
  caderneta processar <arquivo|pasta>   Processa documentos e gera CSV
  caderneta revisar <csv>               Exibe lançamentos para revisão
  caderneta importar <csv>              Registra importação no audit log
  caderneta dry-run <arquivo|pasta>     Simula sem gerar arquivos ou eventos
  caderneta verificar-integridade       Verifica hash chain do audit log
  caderneta status                      Exibe estado do sistema

Princípio (ADR 001, E-10):
  A CLI é o primeiro frontend do sistema.
  A interface web (Etapa 6) melhora a experiência — não é pré-requisito.

Persistência (A5):
  A CLI usa SQLAlchemy/SQLite por padrão via --datalake (arquivo caderneta.db).
  Defina DATABASE_URL para apontar a um PostgreSQL em produção.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.versao import VERSAO as _VERSAO

app = typer.Typer(
    name="caderneta",
    help=f"Plataforma de automação contábil — {_VERSAO.exibicao}",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

VERSAO = _VERSAO.pep440      # usado internamente
VERSAO_EXIBICAO = _VERSAO.exibicao  # ex: v0.003.001


# =============================================================
# HELPERS DE BOOTSTRAP
# =============================================================

def _session_factory(pasta_datalake: Path):
    """Retorna SessionFactory apontando para SQLite em pasta_datalake,
    ou para DATABASE_URL se definida (produção/PostgreSQL)."""
    import os

    from core.infra.db.session import SessionFactory

    url = os.getenv("DATABASE_URL")
    if not url:
        pasta_datalake.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{pasta_datalake / 'caderneta.db'}"

    factory = SessionFactory(url)
    factory.criar_tabelas()
    return factory


def _event_bus():
    from core.events.catalog import EventBusEmMemoria
    return EventBusEmMemoria()


def _policy_engine():
    from decimal import Decimal

    from core.policies.engine import PolicyEngine
    try:
        import os
        limite = Decimal(os.getenv("LIMITE_APROVACAO_SIMPLES", "5000.00"))
    except Exception:
        limite = Decimal("5000.00")
    return PolicyEngine(limite_aprovacao_simples=limite)


def _classification_port():
    """Carrega regras do arquivo JSON se disponível, senão lista vazia."""
    import json
    import uuid as _uuid

    from core.domain.entities import CodigoConta
    from core.rule_engine.classification_impl import RegrasDeterministicasPlugin
    from core.rule_engine.rule_entity import RegraClassificacaoV2

    regras_file = Path("dados/regras/regras_padrao.json")
    regras = []
    if regras_file.exists():
        with open(regras_file, encoding="utf-8") as f:
            dados = json.load(f)
        for r in dados:
            conta_d = CodigoConta(r["conta_debito"]) if r.get("conta_debito") else None
            conta_c = CodigoConta(r["conta_credito"]) if r.get("conta_credito") else None
            regras.append(RegraClassificacaoV2(
                id=r.get("id", str(_uuid.uuid4())),
                nome=r["nome"],
                condicao=r["condicao_json"],
                categoria=r.get("categoria"),
                conta_debito=conta_d,
                conta_credito=conta_c,
                prioridade=r.get("prioridade", 100),
            ))
    return RegrasDeterministicasPlugin(regras=regras, fornecedores=[])


def _construir_use_case(session_factory, pasta_saida: Path, empresa: str):
    from core.adapters.csv_exporter import ExportadorCSV
    from core.application.use_cases.processar_documento import ProcessarDocumentoUseCase
    from core.infra.unit_of_work import UnitOfWork
    from core.parsers.detector import DetectorDocumento
    from core.pipeline.parser_factory import ParserFactory
    from core.rule_engine.lancamento_service import LancamentoService
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    with UnitOfWork(session_factory) as uow:
        periodos = uow.periodos.mapa_por_competencia(empresa_id)
        centros = uow.centros_custo.mapa_por_codigo(empresa_id)

    lancamento_service = LancamentoService(
        periodos_por_competencia=periodos,
        centros_por_codigo=centros,
    )

    return ProcessarDocumentoUseCase(
        detector=DetectorDocumento(),
        parser_factory=ParserFactory(),
        classification_port=_classification_port(),
        policy_engine=_policy_engine(),
        session_factory=session_factory,
        event_bus=_event_bus(),
        exporter=ExportadorCSV(),
        pasta_saida=pasta_saida,
        lancamento_service=lancamento_service,
    )


# =============================================================
# PROCESSAR
# =============================================================

@app.command()
def processar(
    caminho: Annotated[Path, typer.Argument(help="Arquivo ou pasta a processar")],
    usuario: Annotated[str, typer.Option("--usuario", "-u", help="Identificação do operador")] = "operador",
    empresa: Annotated[str, typer.Option("--empresa", help="Identificador da empresa")] = "local",
    saida: Annotated[Path, typer.Option("--saida", "-o", help="Pasta de saída do CSV")] = Path("./dados/saida"),
    datalake: Annotated[Path, typer.Option("--datalake", help="Pasta do banco de auditoria")] = Path("./dados/datalake"),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Processa documentos financeiros e gera CSV para importação no GnuCash."""

    if not caminho.exists():
        rprint(f"[red]Erro: caminho não encontrado: {caminho}[/red]")
        raise typer.Exit(1)

    rprint(Panel(
        f"[bold]Caderneta[/bold] [dim]{VERSAO_EXIBICAO}[/dim]\n"
        f"Operador: [cyan]{usuario}[/cyan]  |  "
        f"Entrada: [cyan]{caminho}[/cyan]  |  "
        f"Saída: [cyan]{saida}[/cyan]",
        border_style="blue",
    ))

    arquivos = _listar_arquivos(caminho)
    if not arquivos:
        rprint("[yellow]Nenhum arquivo suportado encontrado.[/yellow]")
        raise typer.Exit(0)

    session_factory = _session_factory(datalake)
    use_case = _construir_use_case(session_factory, saida, empresa)

    sucesso = falha = revisao = 0

    for arquivo in arquivos:
        resultado = _executar_para_arquivo(use_case, arquivo, usuario, empresa)
        if resultado["sucesso"]:
            sucesso += 1
            revisao += resultado.get("revisao", 0)
            icon = "✅" if resultado.get("revisao", 0) == 0 else "⚠️ "
            msg = (
                f"{icon} [green]{arquivo.name}[/green] — "
                f"{resultado['lancamentos']} lançamentos"
            )
            if resultado.get("revisao"):
                msg += f" ([yellow]{resultado['revisao']} para revisão[/yellow])"
            rprint(msg)
            if verbose and resultado.get("avisos"):
                for a in resultado["avisos"]:
                    rprint(f"   [yellow]⚠  {a}[/yellow]")
        else:
            falha += 1
            rprint(f"[red]❌ {arquivo.name}[/red]")
            for e in resultado.get("erros", []):
                rprint(f"   [red]• {e}[/red]")

    rprint(f"\n[bold]Resultado:[/bold] {sucesso} processados, {falha} com erro, {revisao} para revisão.")

    if falha > 0:
        raise typer.Exit(1)


# =============================================================
# REVISAR
# =============================================================

@app.command()
def revisar(
    caminho_csv: Annotated[Path, typer.Argument(help="CSV gerado pelo comando processar")],
):
    """Exibe os lançamentos do CSV para revisão antes da importação no GnuCash."""

    if not caminho_csv.exists():
        rprint(f"[red]Arquivo não encontrado: {caminho_csv}[/red]")
        raise typer.Exit(1)

    import csv
    from decimal import Decimal

    tabela = Table(
        title=f"Revisão: {caminho_csv.name}",
        show_header=True,
        header_style="bold cyan",
    )
    tabela.add_column("Data", width=12)
    tabela.add_column("Descrição", width=38)
    tabela.add_column("Conta", width=16)
    tabela.add_column("Depósito", justify="right", style="green", width=14)
    tabela.add_column("Retirada", justify="right", style="red", width=14)
    tabela.add_column("Categoria", width=18)

    total_dep = Decimal("0")
    total_ret = Decimal("0")
    linhas = 0

    with open(caminho_csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            dep = (row.get("Deposit") or "").replace(",", ".")
            ret = (row.get("Withdrawal") or "").replace(",", ".")
            if dep:
                total_dep += Decimal(dep)
            if ret:
                total_ret += Decimal(ret)
            tabela.add_row(
                row.get("Date", ""),
                (row.get("Description") or "")[:38],
                (row.get("Account") or ""),
                f"R$ {dep}" if dep else "",
                f"R$ {ret}" if ret else "",
                (row.get("Category") or ""),
            )
            linhas += 1

    console.print(tabela)
    rprint(
        f"\n[bold]{linhas} linhas[/bold] | "
        f"Depósitos: [green]R$ {total_dep:,.2f}[/green] | "
        f"Retiradas: [red]R$ {total_ret:,.2f}[/red]"
    )
    rprint(
        "\n[dim]GnuCash → Arquivo → Importar → Importar Transações de CSV[/dim]"
    )


# =============================================================
# IMPORTAR
# =============================================================

@app.command()
def importar(
    caminho_csv: Annotated[Path, typer.Argument(help="CSV a marcar como importado")],
    aprovado_por: Annotated[str, typer.Option("--aprovado-por", help="E-mail ou nome do aprovador")],
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
    obs: Annotated[str | None, typer.Option("--obs", help="Observações")] = None,
):
    """Registra no audit log que o CSV foi importado manualmente no GnuCash."""

    if not caminho_csv.exists():
        rprint(f"[red]Arquivo não encontrado: {caminho_csv}[/red]")
        raise typer.Exit(1)

    import hashlib

    from core.audit.chain import TipoEvento
    from core.infra.unit_of_work import UnitOfWork

    sha = hashlib.sha256()
    with open(caminho_csv, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    hash_csv = sha.hexdigest()

    session_factory = _session_factory(datalake)
    with UnitOfWork(session_factory) as uow:
        evento = uow.audit.registrar(
            tipo=TipoEvento.CSV_IMPORTADO,
            payload={
                "caminho_csv": str(caminho_csv),
                "hash_csv": hash_csv,
                "observacoes": obs,
            },
            usuario=aprovado_por,
        )
        uow.commit()

    rprint(Panel(
        f"[bold green]✅ Importação registrada[/bold green]\n\n"
        f"Arquivo:      [cyan]{caminho_csv.name}[/cyan]\n"
        f"Hash SHA-256: [dim]{hash_csv[:32]}…[/dim]\n"
        f"Aprovador:    [cyan]{aprovado_por}[/cyan]\n"
        f"Evento ID:    [dim]{evento.id}[/dim]"
        + (f"\nObservações:  {obs}" if obs else ""),
        border_style="green",
        title="Auditoria",
    ))


# =============================================================
# DRY-RUN
# =============================================================

@app.command(name="dry-run")
def dry_run(
    caminho: Annotated[Path, typer.Argument(help="Arquivo ou pasta para simular")],
    usuario: Annotated[str, typer.Option("--usuario", "-u")] = "simulacao",
    empresa: Annotated[str, typer.Option("--empresa")] = "simulacao",
):
    """Simula o processamento sem afetar o banco de dados de produção.

    Use antes de alterar regras de classificação para ver o impacto.
    Ex: caderneta dry-run ./documentos/janeiro/
    """
    if not caminho.exists():
        rprint(f"[red]Erro: caminho não encontrado: {caminho}[/red]")
        raise typer.Exit(1)

    import tempfile

    from core.infra.db.session import SessionFactory

    rprint(Panel(
        f"[bold yellow]DRY RUN[/bold yellow] — nenhum arquivo será gerado\n"
        f"Entrada: [cyan]{caminho}[/cyan]",
        border_style="yellow",
    ))

    arquivos = _listar_arquivos(caminho)

    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("Arquivo")
    tabela.add_column("Lançamentos", justify="right")
    tabela.add_column("Revisão", justify="right")
    tabela.add_column("Status")

    total_l = total_r = 0

    with tempfile.TemporaryDirectory() as tmp:
        # Banco isolado e descartável — nenhum efeito persistente
        session_factory = SessionFactory(f"sqlite:///{tmp}/dry_run.db")
        session_factory.criar_tabelas()
        saida_tmp = Path(tmp) / "saida"
        use_case = _construir_use_case(session_factory, saida_tmp, empresa)

        for arquivo in arquivos:
            r = _executar_para_arquivo(use_case, arquivo, usuario, empresa)
            l = r.get("lancamentos", 0)  # noqa: E741
            rv = r.get("revisao", 0)
            total_l += l
            total_r += rv
            status_txt = "[green]OK[/green]" if r["sucesso"] else "[red]ERRO[/red]"
            tabela.add_row(arquivo.name, str(l), str(rv) if rv else "—", status_txt)
            if not r["sucesso"]:
                for e in r.get("erros", []):
                    tabela.add_row("", "", "", f"[red dim]{e}[/red dim]")

    console.print(tabela)
    rprint(
        f"\n[bold]Simulação:[/bold] {len(arquivos)} arquivos | "
        f"{total_l} lançamentos | {total_r} para revisão"
    )
    rprint("[dim]Nenhum arquivo gerado. Nenhum evento persistido.[/dim]")


# =============================================================
# VERIFICAR INTEGRIDADE
# =============================================================

@app.command(name="verificar-integridade")
def verificar_integridade(
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Verifica a integridade da hash chain do audit log."""
    from core.infra.unit_of_work import UnitOfWork

    session_factory = _session_factory(datalake)
    with UnitOfWork(session_factory) as uow:
        integra, erros = uow.audit.verificar_integridade()

    if integra:
        rprint(Panel(
            "[bold green]✅ Hash chain íntegra[/bold green]\n"
            "Nenhuma adulteração detectada no histórico de auditoria.",
            border_style="green",
        ))
    else:
        rprint(Panel(
            f"[bold red]❌ INTEGRIDADE COMPROMETIDA[/bold red]\n"
            f"{len(erros)} problema(s) detectado(s):\n\n"
            + "\n".join(f"  • {e}" for e in erros),
            border_style="red",
            title="⚠ ATENÇÃO",
        ))
        raise typer.Exit(2)


# =============================================================
# STATUS
# =============================================================

@app.command()
def status(
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Exibe o estado do sistema e estatísticas do audit log."""
    from core.infra.unit_of_work import UnitOfWork
    from core.versao import VERSAO as _v  # noqa: N811
    cor_status = "green" if _v.e_producao else "yellow"
    rprint(Panel(
        f"[bold]Caderneta[/bold] [bold]{_v.exibicao}[/bold]\n"
        f"Etapa: [cyan]{_v.etapa_nome}[/cyan]  |  "
        f"Status: [{cor_status}]{_v.status}[/{cor_status}]",
        border_style="blue",
        title="Status",
    ))

    banco = datalake / "caderneta.db"
    if not banco.exists():
        rprint("[dim]Nenhum evento registrado ainda. Execute 'caderneta processar' para começar.[/dim]")
        return

    session_factory = _session_factory(datalake)
    with UnitOfWork(session_factory) as uow:
        contadores = uow.audit.contar_por_tipo()

    if not contadores:
        rprint("[dim]Nenhum evento registrado ainda. Execute 'caderneta processar' para começar.[/dim]")
        return

    tabela = Table(title="Eventos no Audit Log", show_header=True, header_style="bold")
    tabela.add_column("Tipo de Evento")
    tabela.add_column("Quantidade", justify="right")

    total = 0
    for tipo, qtd in sorted(contadores.items()):
        tabela.add_row(tipo, str(qtd))
        total += qtd

    tabela.add_section()
    tabela.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]")
    console.print(tabela)


# =============================================================
# PERÍODO CONTÁBIL
# =============================================================

periodo_app = typer.Typer(help="Gerencia períodos contábeis (abertura/fechamento).")
app.add_typer(periodo_app, name="periodo")


@periodo_app.command(name="fechar")
def periodo_fechar(
    ano: Annotated[int, typer.Argument(help="Ano da competência")],
    mes: Annotated[int, typer.Argument(help="Mês da competência (1-12)")],
    responsavel: Annotated[str, typer.Option("--responsavel", "-r", help="Quem está fechando o período")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Fecha um período contábil — bloqueia novos lançamentos na competência."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    if not (1 <= mes <= 12):
        rprint(f"[red]Mês inválido: {mes}. Use 1-12.[/red]")
        raise typer.Exit(1)

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    try:
        with UnitOfWork(session_factory) as uow:
            periodo = uow.periodos.obter_ou_criar(empresa_id, ano, mes)
            periodo.fechar(responsavel)
            uow.periodos.salvar(periodo)
            uow.commit()
    except ValueError as e:
        rprint(f"[red]❌ {e}[/red]")
        raise typer.Exit(1)  # noqa: B904

    rprint(Panel(
        f"[bold green]✅ Período fechado[/bold green]\n\n"
        f"Competência:  [cyan]{ano}/{mes:02d}[/cyan]\n"
        f"Responsável:  [cyan]{responsavel}[/cyan]\n"
        f"Empresa:      [dim]{empresa}[/dim]",
        border_style="green",
        title="Período Contábil",
    ))


@periodo_app.command(name="abrir")
def periodo_abrir(
    ano: Annotated[int, typer.Argument(help="Ano da competência")],
    mes: Annotated[int, typer.Argument(help="Mês da competência (1-12)")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Garante que um período contábil existe e está aberto."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    if not (1 <= mes <= 12):
        rprint(f"[red]Mês inválido: {mes}. Use 1-12.[/red]")
        raise typer.Exit(1)

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    with UnitOfWork(session_factory) as uow:
        periodo = uow.periodos.obter_ou_criar(empresa_id, ano, mes)
        uow.commit()

    rprint(Panel(
        f"[bold green]✅ Período {periodo.status.value}[/bold green]\n\n"
        f"Competência: [cyan]{ano}/{mes:02d}[/cyan]",
        border_style="green",
        title="Período Contábil",
    ))


@periodo_app.command(name="listar")
def periodo_listar(
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Lista os períodos contábeis cadastrados para a empresa."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    with UnitOfWork(session_factory) as uow:
        periodos = uow.periodos.listar_por_empresa(empresa_id)

    if not periodos:
        rprint("[dim]Nenhum período cadastrado ainda.[/dim]")
        return

    tabela = Table(title="Períodos Contábeis", show_header=True, header_style="bold")
    tabela.add_column("Competência")
    tabela.add_column("Status")
    tabela.add_column("Fechado por")
    tabela.add_column("Fechado em")

    for p in periodos:
        status_str = (
            "[green]aberto[/green]" if p.status.value == "aberto" else "[red]fechado[/red]"
        )
        tabela.add_row(
            f"{p.ano}/{p.mes:02d}",
            status_str,
            p.fechado_por or "—",
            p.fechado_em.strftime("%Y-%m-%d %H:%M") if p.fechado_em else "—",
        )

    console.print(tabela)


# =============================================================
# LANÇAMENTOS (integração GnuCash/ERP)
# =============================================================

lancamentos_app = typer.Typer(help="Consulta e concilia lançamentos exportados.")
app.add_typer(lancamentos_app, name="lancamentos")


@lancamentos_app.command(name="listar")
def lancamentos_listar(
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    status: Annotated[str | None, typer.Option(
        "--status", help="rascunho|pendente|aprovado|rejeitado|exportado"
    )] = None,
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
    limite: Annotated[int, typer.Option("--limite")] = 50,
):
    """Lista lançamentos persistidos — visibilidade do que foi gerado e exportado."""
    from core.domain.entities import StatusLancamento
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    status_filtro = None
    if status:
        try:
            status_filtro = StatusLancamento(status)
        except ValueError:
            rprint(
                f"[red]Status inválido: '{status}'. "
                f"Use: {', '.join(s.value for s in StatusLancamento)}[/red]"
            )
            raise typer.Exit(1)  # noqa: B904

    with UnitOfWork(session_factory) as uow:
        lancamentos = uow.lancamentos.listar_por_empresa(
            empresa_id, status=status_filtro, limit=limite,
        )

    if not lancamentos:
        rprint("[dim]Nenhum lançamento encontrado.[/dim]")
        return

    tabela = Table(title="Lançamentos", show_header=True, header_style="bold")
    tabela.add_column("ID", width=10)
    tabela.add_column("Data")
    tabela.add_column("Descrição", width=30)
    tabela.add_column("Valor", justify="right")
    tabela.add_column("Status")
    tabela.add_column("GUID GnuCash", width=12)

    for l in lancamentos:  # noqa: E741
        status_cor = {
            "exportado": "cyan",
            "aprovado": "green",
            "rejeitado": "red",
            "pendente": "yellow",
        }.get(l.status.value, "white")
        tabela.add_row(
            str(l.id)[:8],
            l.data_lancamento.strftime("%Y-%m-%d") if l.data_lancamento else "—",
            l.descricao[:30],
            f"R$ {l.valor_total.valor:,.2f}" if l.splits else "—",
            f"[{status_cor}]{l.status.value}[/{status_cor}]",
            str(l.guid_gnucash)[:8] if l.guid_gnucash else "—",
        )

    console.print(tabela)


@lancamentos_app.command(name="vincular-guid")
def lancamentos_vincular_guid(
    lancamento_id: Annotated[str, typer.Argument(help="ID (completo ou prefixo) do lançamento")],
    guid: Annotated[str, typer.Argument(help="GUID gerado pelo GnuCash após importação")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Vincula manualmente o GUID do GnuCash a um lançamento já exportado.

    Use após importar o CSV no GnuCash e conferir o GUID gerado — completa
    a trilha de conciliação entre Caderneta e GnuCash.
    """
    from uuid import UUID

    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)  # noqa: F841
    session_factory = _session_factory(datalake)

    try:
        lanc_uuid = UUID(lancamento_id)
    except ValueError:
        rprint(f"[red]ID inválido: '{lancamento_id}'. Informe o UUID completo.[/red]")
        raise typer.Exit(1)  # noqa: B904

    with UnitOfWork(session_factory) as uow:
        lancamento = uow.lancamentos.buscar_por_id(lanc_uuid)
        if lancamento is None:
            rprint(f"[red]Lançamento não encontrado: {lancamento_id}[/red]")
            raise typer.Exit(1)
        lancamento.guid_gnucash = guid
        uow.lancamentos.salvar(lancamento)
        uow.commit()

    rprint(Panel(
        f"[bold green]✅ GUID vinculado[/bold green]\n\n"
        f"Lançamento: [dim]{lancamento_id}[/dim]\n"
        f"GUID GnuCash: [cyan]{guid}[/cyan]",
        border_style="green",
        title="Conciliação GnuCash",
    ))


# =============================================================
# CENTRO DE CUSTO
# =============================================================

centro_custo_app = typer.Typer(help="Gerencia centros de custo.")
app.add_typer(centro_custo_app, name="centro-custo")


@centro_custo_app.command(name="criar")
def centro_custo_criar(
    codigo: Annotated[str, typer.Argument(help="Código do centro de custo (ex: CC-VENDAS)")],
    nome: Annotated[str, typer.Argument(help="Nome descritivo")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Cria um novo centro de custo para a empresa."""
    from core.infra.repositories.centro_custo_repository import CentroCustoJaExisteError
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    try:
        with UnitOfWork(session_factory) as uow:
            uow.centros_custo.criar(empresa_id, codigo, nome)
            uow.commit()
    except CentroCustoJaExisteError as e:
        rprint(f"[red]❌ {e}[/red]")
        raise typer.Exit(1)  # noqa: B904

    rprint(Panel(
        f"[bold green]✅ Centro de custo criado[/bold green]\n\n"
        f"Código: [cyan]{codigo}[/cyan]\n"
        f"Nome:   [cyan]{nome}[/cyan]\n"
        f"Empresa: [dim]{empresa}[/dim]",
        border_style="green",
        title="Centro de Custo",
    ))


@centro_custo_app.command(name="listar")
def centro_custo_listar(
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
    apenas_ativos: Annotated[bool, typer.Option("--apenas-ativos")] = False,
):
    """Lista os centros de custo cadastrados para a empresa."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    with UnitOfWork(session_factory) as uow:
        centros = uow.centros_custo.listar_por_empresa(empresa_id, apenas_ativos=apenas_ativos)

    if not centros:
        rprint("[dim]Nenhum centro de custo cadastrado ainda.[/dim]")
        return

    tabela = Table(title="Centros de Custo", show_header=True, header_style="bold")
    tabela.add_column("Código")
    tabela.add_column("Nome")
    tabela.add_column("Status")

    for c in centros:
        status_str = "[green]ativo[/green]" if c.ativo else "[red]inativo[/red]"
        tabela.add_row(c.codigo, c.nome, status_str)

    console.print(tabela)


@centro_custo_app.command(name="desativar")
def centro_custo_desativar(
    codigo: Annotated[str, typer.Argument(help="Código do centro de custo")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Desativa um centro de custo — impede seu uso em novos lançamentos."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    with UnitOfWork(session_factory) as uow:
        centro = uow.centros_custo.buscar_por_codigo(empresa_id, codigo)
        if centro is None:
            rprint(f"[red]Centro de custo '{codigo}' não encontrado.[/red]")
            raise typer.Exit(1)
        centro.ativo = False
        uow.centros_custo.salvar(centro)
        uow.commit()

    rprint(f"[yellow]⚠  Centro de custo '{codigo}' desativado.[/yellow]")


@centro_custo_app.command(name="ativar")
def centro_custo_ativar(
    codigo: Annotated[str, typer.Argument(help="Código do centro de custo")],
    empresa: Annotated[str, typer.Option("--empresa")] = "local",
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Reativa um centro de custo previamente desativado."""
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    empresa_id = empresa_id_from_string(empresa)
    session_factory = _session_factory(datalake)

    with UnitOfWork(session_factory) as uow:
        centro = uow.centros_custo.buscar_por_codigo(empresa_id, codigo)
        if centro is None:
            rprint(f"[red]Centro de custo '{codigo}' não encontrado.[/red]")
            raise typer.Exit(1)
        centro.ativo = True
        uow.centros_custo.salvar(centro)
        uow.commit()

    rprint(f"[green]✅ Centro de custo '{codigo}' ativado.[/green]")


# =============================================================
# HELPERS INTERNOS

# =============================================================
# CONCILIAÇÃO BANCÁRIA — Etapa 8
# =============================================================

conciliacao_app = typer.Typer(help="Motor de Conciliação Bancária (Etapa 8).")
app.add_typer(conciliacao_app, name="conciliacao")


@conciliacao_app.command(name="importar")
def conciliacao_importar(
    arquivo: Path = typer.Argument(..., help="Arquivo OFX/QFX do extrato bancário."),  # noqa: B008
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Importa um extrato OFX e persiste as transações bancárias.

    Idempotente: reimportar o mesmo arquivo não cria duplicatas.
    """
    import uuid

    from rich.console import Console

    from core.adapters.ofx_bank_statement import OFXBankStatementAdapter
    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    console = Console()

    if not arquivo.exists():
        console.print(f"[red]Arquivo não encontrado: {arquivo}[/red]")
        raise typer.Exit(1)

    empresa_id = empresa_id_from_string(empresa)
    id_importacao = str(uuid.uuid4())
    sf = _session_factory(pasta_datalake)
    adapter = OFXBankStatementAdapter()

    # Detectar conta antes de importar
    conta = adapter.detectar_conta(arquivo)
    if conta:
        console.print(f"Conta detectada: [cyan]{conta}[/cyan]")

    transacoes = adapter.importar(arquivo, empresa_id, id_importacao)

    inseridas = 0
    duplicatas = 0

    with UnitOfWork(sf) as uow:
        for tx in transacoes:
            if uow.transacoes_bancarias.salvar_se_nova(tx):
                inseridas += 1
            else:
                duplicatas += 1
        uow.commit()

    console.print(
        f"[green]✓[/green] Importadas: [bold]{inseridas}[/bold] transações "
        f"| Duplicatas ignoradas: [yellow]{duplicatas}[/yellow]"
    )


@conciliacao_app.command(name="executar")
def conciliacao_executar(
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    periodo: str = typer.Option(
        ..., "--periodo", "-p",
        help="Período no formato YYYY-MM (ex: 2026-07)."
    ),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
    tolerancia_valor: float = typer.Option(
        0.10, "--tol-valor", help="Tolerância de valor em R$."
    ),
    tolerancia_dias: int = typer.Option(
        2, "--tol-dias", help="Tolerância de data em dias."
    ),
) -> None:
    """Executa o motor de conciliação para o período informado."""
    import calendar
    from datetime import date
    from decimal import Decimal

    from rich.console import Console
    from rich.table import Table

    from core.domain.entities import StatusLancamento
    from core.infra.unit_of_work import UnitOfWork
    from core.rule_engine.motor_conciliacao import MotorConciliacao, ToleranciasConciliacao
    from shared.identifiers import empresa_id_from_string

    console = Console()

    try:
        ano, mes = int(periodo[:4]), int(periodo[5:7])
        data_inicio = date(ano, mes, 1)
        data_fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    except (ValueError, IndexError):
        console.print("[red]Formato de período inválido. Use YYYY-MM (ex: 2026-07).[/red]")
        raise typer.Exit(1)  # noqa: B904

    empresa_id = empresa_id_from_string(empresa)
    sf = _session_factory(pasta_datalake)

    with UnitOfWork(sf) as uow:
        transacoes = uow.transacoes_bancarias.listar_por_empresa_e_periodo(
            empresa_id, data_inicio, data_fim
        )
        lancamentos = uow.lancamentos.listar_por_empresa(
            empresa_id, status=StatusLancamento.APROVADO
        )
        lancamentos = [
            lanc for lanc in lancamentos
            if lanc.data_lancamento
            and data_inicio <= lanc.data_lancamento <= data_fim
        ]

        # Fase 6, B6-2 (ADR 010): exclui compras individuais de cartão
        # (D7) da lista de candidatos — nunca via categoria/valor/data,
        # somente via CompraCartao.lancamento_id. O lançamento de
        # pagamento (D8) nunca aparece em compras_cartao — preservado
        # automaticamente. Lançamentos não relacionados a cartão também
        # são preservados (não têm linha correspondente em compras_cartao).
        ids_compras_cartao = uow.faturas_cartao.listar_lancamento_ids_de_compras(empresa_id)
        lancamentos = [lanc for lanc in lancamentos if lanc.id not in ids_compras_cartao]

        # Fase 5 (ADR 010, D14, B4-B): resolve o FITID de cada lançamento
        # via Lancamento.documento_id -> Documento.numero_documento, sem
        # alterar Lancamento nem o motor. Lançamentos sem documento_id
        # (ex.: cartão de crédito, D7/D8) não entram no mapa — nunca
        # ativam a Camada 1, permanecem na Camada 2 (D15, inalterado).
        fitids_por_lancamento: dict = {}
        for lanc in lancamentos:
            if lanc.documento_id is None:
                continue
            documento = uow.documentos.buscar_por_id(lanc.documento_id)
            if documento is not None and documento.numero_documento:
                fitids_por_lancamento[lanc.id] = documento.numero_documento

    console.print(
        f"Período: [cyan]{data_inicio}[/cyan] a [cyan]{data_fim}[/cyan] | "
        f"Transações bancárias: [bold]{len(transacoes)}[/bold] | "
        f"Lançamentos aprovados: [bold]{len(lancamentos)}[/bold]"
    )

    tol = ToleranciasConciliacao(
        valor=Decimal(str(tolerancia_valor)),
        dias=tolerancia_dias,
    )
    motor = MotorConciliacao(tolerancias=tol)
    relatorio = motor.conciliar(
        lancamentos=lancamentos,
        transacoes=transacoes,
        empresa_id=empresa_id,
        periodo_inicio=data_inicio,
        periodo_fim=data_fim,
        fitids_por_lancamento=fitids_por_lancamento,
    )

    # Exibir resumo
    tabela = Table(title=f"Relatório de Conciliação — {periodo}")
    tabela.add_column("Status", style="bold")
    tabela.add_column("Quantidade", justify="right")
    tabela.add_column("% do total", justify="right")

    total = relatorio.total_itens or 1
    for status, itens in [
        ("✓ Conciliado",   relatorio.conciliados),
        ("⚠ Divergente",   relatorio.divergentes),
        ("? Ambíguo",      relatorio.ambiguos),
        ("○ Pendente",     relatorio.pendentes),
        ("✗ Sem documento", relatorio.sem_documento),
        ("⊗ Duplicado",    relatorio.duplicados),
    ]:
        pct = f"{len(itens)/total*100:.1f}%"
        tabela.add_row(status, str(len(itens)), pct)

    console.print(tabela)
    console.print(
        f"Conciliação automática: [bold]{relatorio.percentual_conciliado:.1f}%[/bold]"
    )


@conciliacao_app.command(name="listar")
def conciliacao_listar(
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    periodo: str = typer.Option(
        ..., "--periodo", "-p", help="Período YYYY-MM."
    ),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Lista transações bancárias importadas para o período."""
    import calendar
    from datetime import date

    from rich.console import Console
    from rich.table import Table

    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    console = Console()

    try:
        ano, mes = int(periodo[:4]), int(periodo[5:7])
        data_inicio = date(ano, mes, 1)
        data_fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    except (ValueError, IndexError):
        console.print("[red]Formato inválido. Use YYYY-MM.[/red]")
        raise typer.Exit(1)  # noqa: B904

    empresa_id = empresa_id_from_string(empresa)
    sf = _session_factory(pasta_datalake)

    with UnitOfWork(sf) as uow:
        transacoes = uow.transacoes_bancarias.listar_por_empresa_e_periodo(
            empresa_id, data_inicio, data_fim
        )

    if not transacoes:
        console.print("[yellow]Nenhuma transação bancária encontrada para o período.[/yellow]")
        return

    tabela = Table(title=f"Transações Bancárias — {periodo}")
    tabela.add_column("Data")
    tabela.add_column("FITID")
    tabela.add_column("Descrição")
    tabela.add_column("Natureza")
    tabela.add_column("Valor", justify="right")

    for tx in transacoes:
        tabela.add_row(
            str(tx.data),
            tx.fitid[:20],
            tx.descricao[:40],
            tx.natureza.value,
            f"R$ {tx.valor.valor:,.2f}",
        )

    console.print(tabela)
    console.print(f"Total: [bold]{len(transacoes)}[/bold] transações")


# =============================================================
# CARTÃO DE CRÉDITO (ADR 010)
# =============================================================

cartao_app = typer.Typer(help="Faturas de Cartão de Crédito (ADR 010).")
app.add_typer(cartao_app, name="cartao")


@cartao_app.command(name="importar")
def cartao_importar(
    arquivo: Path = typer.Argument(..., help="Arquivo PDF da fatura."),  # noqa: B008
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    emissor: str = typer.Option(..., "--emissor", help="Emissor do cartão (ex: Nubank)."),
    final_numero: str = typer.Option(..., "--final", help="Últimos 4 dígitos do cartão."),
    titular: str = typer.Option(..., "--titular", help="Nome do titular do cartão."),
    conta_codigo: str = typer.Option(
        ..., "--conta", help="Código da conta contábil de Passivo do cartão (DT-CC-01)."
    ),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Importa uma fatura de cartão de crédito em PDF.

    Cria ou reaproveita o CartaoCredito pela chave de identidade
    (emissor, final do número, titular — idempotente, B1). Idempotente
    também ao nível de fatura: reimportar a mesma fatura (mesmo cartão
    e período) não duplica (D13).

    PDF_IMAGEM (fatura escaneada) não é suportado por este comando —
    o pipeline de OCR não está conectado à CLI (nenhum comando desta
    CLI usa OCR hoje; core/ nunca importa ai/, ADR 001).
    """
    from rich.console import Console

    from core.application.use_cases.processar_fatura_cartao import (
        DocumentoNaoEhFaturaError,
        OCRNaoDisponivelError,
        ProcessarFaturaCartaoUseCase,
    )
    from core.domain.entities import CartaoCredito, CodigoConta
    from core.infra.unit_of_work import UnitOfWork
    from core.parsers.detector import DetectorDocumento, TipoNaoSuportadoError
    from shared.identifiers import empresa_id_from_string

    console = Console()

    if not arquivo.exists():
        console.print(f"[red]Arquivo não encontrado: {arquivo}[/red]")
        raise typer.Exit(1)

    empresa_id = empresa_id_from_string(empresa)
    sf = _session_factory(pasta_datalake)

    with UnitOfWork(sf) as uow:
        cartao = CartaoCredito(
            empresa_id=empresa_id,
            emissor=emissor,
            final_numero=final_numero,
            titular=titular,
            conta_codigo=CodigoConta(conta_codigo),
        )
        cartao_novo = uow.cartoes_credito.salvar_se_novo(cartao)
        if not cartao_novo:
            cartao = uow.cartoes_credito.buscar_por_chave(
                empresa_id, emissor, final_numero, titular
            )
        uow.commit()

    console.print(
        f"Cartão: [cyan]{emissor} ****{final_numero}[/cyan] "
        f"({'novo' if cartao_novo else 'já cadastrado'})"
    )

    uc = ProcessarFaturaCartaoUseCase(
        detector=DetectorDocumento(),
        session_factory=sf,
        event_bus=_event_bus(),
    )

    try:
        resultado = uc.executar(arquivo, empresa_id=empresa_id, cartao_id=cartao.id)
    except OCRNaoDisponivelError:
        console.print(
            "[red]Fatura em PDF_IMAGEM requer OCR, não conectado a esta CLI.[/red]"
        )
        raise typer.Exit(1)  # noqa: B904
    except (DocumentoNaoEhFaturaError, TipoNaoSuportadoError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904

    if resultado.duplicada:
        console.print("[yellow]Fatura já processada anteriormente — ignorada (D13).[/yellow]")
        return

    console.print(
        f"[green]✓[/green] Fatura importada: [bold]{len(resultado.fatura.itens)}[/bold] itens | "
        f"Status: [bold]{resultado.fatura.status_fechamento.value}[/bold] | "
        f"Total: R$ {resultado.fatura.valor_total_declarado.valor:,.2f}"
    )
    for aviso in resultado.avisos:
        console.print(f"[yellow]⚠[/yellow] {aviso}")


@cartao_app.command(name="listar")
def cartao_listar(
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Lista faturas de cartão de crédito importadas."""
    from rich.console import Console
    from rich.table import Table

    from core.infra.unit_of_work import UnitOfWork
    from shared.identifiers import empresa_id_from_string

    console = Console()
    empresa_id = empresa_id_from_string(empresa)
    sf = _session_factory(pasta_datalake)

    with UnitOfWork(sf) as uow:
        faturas = uow.faturas_cartao.listar_por_empresa(empresa_id)

    if not faturas:
        console.print("[yellow]Nenhuma fatura de cartão encontrada.[/yellow]")
        return

    tabela = Table(title="Faturas de Cartão de Crédito")
    tabela.add_column("Período")
    tabela.add_column("Vencimento")
    tabela.add_column("Itens", justify="right")
    tabela.add_column("Total", justify="right")
    tabela.add_column("Status")

    for fatura in faturas:
        tabela.add_row(
            str(fatura.periodo_referencia),
            str(fatura.data_vencimento) if fatura.data_vencimento else "—",
            str(len(fatura.itens)),
            f"R$ {fatura.valor_total_declarado.valor:,.2f}",
            fatura.status_fechamento.value,
        )

    console.print(tabela)
    console.print(f"Total: [bold]{len(faturas)}[/bold] faturas")


@cartao_app.command(name="gerar-lancamentos")
def cartao_gerar_lancamentos(
    fatura_id: str = typer.Argument(..., help="ID da fatura (UUID)."),
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    conta_cartao: str = typer.Option(..., "--conta-cartao", help="Conta de Passivo do cartão (D6)."),
    conta_banco: str = typer.Option(..., "--conta-banco", help="Conta bancária de origem do pagamento (D8)."),
    conta_compra: str = typer.Option(..., "--conta-compra", help="Conta de despesa/ativo para itens tipo COMPRA (D7)."),
    conta_iof: str = typer.Option(None, "--conta-iof", help="Conta de despesa financeira para IOF (D9) — obrigatória se a fatura tiver item IOF."),
    conta_juros: str = typer.Option(None, "--conta-juros", help="Conta de despesa financeira para juros (D10) — obrigatória se a fatura tiver item de juros."),
    conta_multa: str = typer.Option(None, "--conta-multa", help="Conta de despesa financeira para multa (D10) — obrigatória se a fatura tiver item de multa."),
    conta_encargo: str = typer.Option(None, "--conta-encargo", help="Conta de despesa financeira para encargo (D10) — obrigatória se a fatura tiver item de encargo."),
    conta_anuidade: str = typer.Option(None, "--conta-anuidade", help="Conta para anuidade — usa --conta-compra se omitida."),
    conta_estorno: str = typer.Option(None, "--conta-estorno", help="Conta para estorno — usa --conta-compra se omitida."),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Gera e persiste os lançamentos de compra (D7) e pagamento (D8) de
    uma fatura FECHADA (B6-0). Idempotente — reexecutar reaproveita os
    lançamentos já gerados, sem duplicar (garantia do próprio use case,
    não desta camada de CLI).
    """
    from uuid import UUID

    from rich.console import Console

    from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
        ContaDespesaNaoMapeadaError,
        FaturaNaoEncontradaError,
        FaturaNaoFechadaError,
        GerarLancamentosFaturaCartaoUseCase,
    )
    from core.domain.entities import CodigoConta, TipoItemFatura

    console = Console()

    contas_despesa_por_tipo = {TipoItemFatura.COMPRA: CodigoConta(conta_compra)}
    if conta_iof:
        contas_despesa_por_tipo[TipoItemFatura.IOF] = CodigoConta(conta_iof)
    if conta_juros:
        contas_despesa_por_tipo[TipoItemFatura.JUROS] = CodigoConta(conta_juros)
    if conta_multa:
        contas_despesa_por_tipo[TipoItemFatura.MULTA] = CodigoConta(conta_multa)
    if conta_encargo:
        contas_despesa_por_tipo[TipoItemFatura.ENCARGO] = CodigoConta(conta_encargo)
    contas_despesa_por_tipo[TipoItemFatura.ANUIDADE] = CodigoConta(conta_anuidade or conta_compra)
    contas_despesa_por_tipo[TipoItemFatura.ESTORNO] = CodigoConta(conta_estorno or conta_compra)

    sf = _session_factory(pasta_datalake)
    uc = GerarLancamentosFaturaCartaoUseCase(session_factory=sf)

    try:
        resultado = uc.executar(
            UUID(fatura_id),
            conta_cartao=CodigoConta(conta_cartao),
            conta_banco=CodigoConta(conta_banco),
            contas_despesa_por_tipo=contas_despesa_por_tipo,
        )
    except FaturaNaoEncontradaError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904
    except FaturaNaoFechadaError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904
    except ContaDespesaNaoMapeadaError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904

    if resultado.ja_processado:
        console.print("[yellow]Fatura já processada anteriormente — lançamentos reaproveitados (idempotente).[/yellow]")
    else:
        console.print(
            f"[green]✓[/green] Lançamentos gerados: "
            f"[bold]{len(resultado.lancamentos_compra_ids)}[/bold] de compra + 1 de pagamento."
        )
    console.print(f"Lançamento de pagamento: [cyan]{resultado.lancamento_pagamento_id}[/cyan]")


@cartao_app.command(name="conciliar-pagamento")
def cartao_conciliar_pagamento(
    fatura_id: str = typer.Argument(..., help="ID da fatura (UUID)."),
    empresa: str = typer.Option(..., "--empresa", "-e", help="ID da empresa."),
    periodo: str = typer.Option(..., "--periodo", help="Período de busca de transações, formato AAAA-MM."),
    pasta_datalake: Path = typer.Option(  # noqa: B008
        Path("datalake"), "--datalake", "-d", help="Pasta do datalake."
    ),
) -> None:
    """Concilia o lançamento de pagamento agregado de uma fatura contra
    o extrato bancário (B6-3), persiste o vínculo quando CONCILIADO
    (B6-5/6/14), registra auditoria (B6-7) e publica o evento (B6-8).
    Idempotente — reexecutar reaproveita o vínculo já persistido, sem
    duplicar (garantia dos use cases, não desta camada de CLI).
    """
    from datetime import datetime
    from uuid import UUID

    from rich.console import Console

    from core.application.use_cases.gerar_lancamentos_fatura_cartao import (
        FaturaNaoEncontradaError,
    )
    from core.application.use_cases.localizar_pagamento_fatura_cartao import (
        PagamentoNaoGeradoError,
    )
    from core.application.use_cases.persistir_conciliacao_pagamento_fatura_cartao import (
        PersistirConciliacaoPagamentoFaturaCartaoUseCase,
    )
    from core.domain.entities import TipoConciliacao

    console = Console()

    ano, mes = (int(p) for p in periodo.split("-"))
    data_inicio = datetime(ano, mes, 1).date()
    if mes == 12:
        data_fim = datetime(ano, 12, 31).date()
    else:
        data_fim = datetime(ano, mes + 1, 1).date()
        from datetime import timedelta
        data_fim = data_fim - timedelta(days=1)

    sf = _session_factory(pasta_datalake)
    uc = PersistirConciliacaoPagamentoFaturaCartaoUseCase(session_factory=sf, event_bus=_event_bus())

    try:
        resultado = uc.executar(UUID(fatura_id), data_inicio=data_inicio, data_fim=data_fim)
    except FaturaNaoEncontradaError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904
    except PagamentoNaoGeradoError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)  # noqa: B904

    if resultado.item.status == TipoConciliacao.CONCILIADO:
        if resultado.persistido:
            console.print(f"[green]✓[/green] Conciliado e persistido. Transação: [cyan]{resultado.item.transacao_bancaria_id}[/cyan]")
        else:
            console.print(f"[yellow]Conciliado, mas já vinculado por outra execução ({resultado.motivo_nao_persistido}).[/yellow]")
    else:
        console.print(f"[yellow]Status: {resultado.item.status.value} ({resultado.item.metodo.value}) — nenhum vínculo persistido.[/yellow]")

# =============================================================

def _listar_arquivos(caminho: Path) -> list[Path]:
    extensoes = {".ofx", ".qfx", ".csv", ".xml", ".pdf", ".jpg", ".jpeg", ".png"}
    if caminho.is_file():
        return [caminho] if caminho.suffix.lower() in extensoes else []
    return sorted(f for f in caminho.iterdir() if f.suffix.lower() in extensoes)


def _executar_para_arquivo(use_case, arquivo: Path, usuario: str, empresa: str) -> dict:
    """Adapta ProcessarDocumentoUseCase.executar() ao formato de dict usado pela CLI."""
    from core.application.use_cases.processar_documento import ComandoProcessarDocumento

    resultado = use_case.executar(ComandoProcessarDocumento(
        filepath=arquivo,
        usuario=usuario,
        empresa_id=empresa,
    ))

    return {
        "sucesso": resultado.sucesso,
        "lancamentos": resultado.lancamentos_criados,
        "revisao": resultado.lancamentos_revisao,
        "erros": resultado.erros,
        "avisos": resultado.avisos,
    }


if __name__ == "__main__":
    app()

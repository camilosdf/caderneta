"""Interface de linha de comando — Caderneta v0.3.

Subcomandos disponíveis:
  caderneta processar <arquivo|pasta>   Processa documentos e gera CSV
  caderneta revisar <csv>               Exibe lançamentos para revisão
  caderneta importar <csv>              Registra importação no audit log
  caderneta dry-run <arquivo|pasta>     Simula sem gerar arquivos ou eventos
  caderneta replay <arquivo_audit>      Reproduz eventos de um período
  caderneta verificar-integridade       Verifica hash chain do audit log
  caderneta status                      Exibe estado do sistema

Princípio (ADR 001, E-10):
  A CLI é o primeiro frontend do sistema.
  A interface web (Etapa 6) melhora a experiência — não é pré-requisito.
"""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

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

def _audit_chain(pasta_datalake: Path):
    from core.audit.chain import AuditChain
    return AuditChain(pasta_datalake / "audit.jsonl")


def _event_bus():
    from core.events.catalog import EventBusEmMemoria
    return EventBusEmMemoria()


def _policy_engine():
    from decimal import Decimal
    from core.policies.engine import PolicyEngine
    limite = Decimal(typer.get_app_dir("caderneta"))
    try:
        import os
        limite = Decimal(os.getenv("LIMITE_APROVACAO_SIMPLES", "5000.00"))
    except Exception:
        limite = Decimal("5000.00")
    return PolicyEngine(limite_aprovacao_simples=limite)


# =============================================================
# PROCESSAR
# =============================================================

@app.command()
def processar(
    caminho: Annotated[Path, typer.Argument(help="Arquivo ou pasta a processar")],
    usuario: Annotated[str, typer.Option("--usuario", "-u", help="Identificação do operador")] = "operador",
    saida: Annotated[Path, typer.Option("--saida", "-o", help="Pasta de saída do CSV")] = Path("./dados/saida"),
    datalake: Annotated[Path, typer.Option("--datalake", help="Pasta do audit log")] = Path("./dados/datalake"),
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

    audit = _audit_chain(datalake)
    bus = _event_bus()

    sucesso = falha = revisao = 0

    for arquivo in arquivos:
        try:
            resultado = _processar_arquivo(arquivo, usuario, saida, audit, bus)
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
                if resultado.get("csv"):
                    msg += f" → [cyan]{resultado['csv']}[/cyan]"
                rprint(msg)
                if verbose and resultado.get("avisos"):
                    for a in resultado["avisos"]:
                        rprint(f"   [yellow]⚠  {a}[/yellow]")
            else:
                falha += 1
                rprint(f"[red]❌ {arquivo.name}[/red]")
                for e in resultado.get("erros", []):
                    rprint(f"   [red]• {e}[/red]")
        except Exception as e:
            falha += 1
            rprint(f"[red]❌ {arquivo.name}: {e}[/red]")

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
    obs: Annotated[Optional[str], typer.Option("--obs", help="Observações")] = None,
):
    """Registra no audit log que o CSV foi importado manualmente no GnuCash."""

    if not caminho_csv.exists():
        rprint(f"[red]Arquivo não encontrado: {caminho_csv}[/red]")
        raise typer.Exit(1)

    import hashlib
    from core.audit.chain import TipoEvento

    sha = hashlib.sha256()
    with open(caminho_csv, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    hash_csv = sha.hexdigest()

    audit = _audit_chain(datalake)
    evento = audit.registrar(
        tipo=TipoEvento.CSV_IMPORTADO,
        payload={
            "caminho_csv": str(caminho_csv),
            "hash_csv": hash_csv,
            "observacoes": obs,
        },
        usuario=aprovado_por,
    )

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
):
    """Simula o processamento sem gerar arquivos nem registrar eventos.

    Use antes de alterar regras de classificação para ver o impacto.
    Ex: caderneta dry-run ./documentos/janeiro/
    """
    if not caminho.exists():
        rprint(f"[red]Erro: caminho não encontrado: {caminho}[/red]")
        raise typer.Exit(1)

    from core.audit.chain import AuditChain
    from core.events.catalog import EventBusEmMemoria
    import tempfile, os

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
        audit_tmp = AuditChain(Path(tmp) / "dry_run_audit.jsonl")
        saida_tmp = Path(tmp) / "saida"
        bus = EventBusEmMemoria()

        for arquivo in arquivos:
            try:
                r = _processar_arquivo(arquivo, usuario, saida_tmp, audit_tmp, bus)
                l = r.get("lancamentos", 0)
                rv = r.get("revisao", 0)
                total_l += l
                total_r += rv
                status = "[green]OK[/green]" if r["sucesso"] else "[red]ERRO[/red]"
                tabela.add_row(arquivo.name, str(l), str(rv) if rv else "—", status)
                if not r["sucesso"]:
                    for e in r.get("erros", []):
                        tabela.add_row("", "", "", f"[red dim]{e}[/red dim]")
            except Exception as e:
                tabela.add_row(arquivo.name, "—", "—", f"[red]ERRO: {e}[/red]")

    console.print(tabela)
    rprint(
        f"\n[bold]Simulação:[/bold] {len(arquivos)} arquivos | "
        f"{total_l} lançamentos | {total_r} para revisão"
    )
    rprint("[dim]Nenhum arquivo gerado. Nenhum evento registrado.[/dim]")


# =============================================================
# VERIFICAR INTEGRIDADE
# =============================================================

@app.command(name="verificar-integridade")
def verificar_integridade(
    datalake: Annotated[Path, typer.Option("--datalake")] = Path("./dados/datalake"),
):
    """Verifica a integridade da hash chain do audit log."""

    audit = _audit_chain(datalake)
    integra, erros = audit.verificar_integridade()

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
    import json

    from core.versao import VERSAO as _v
    cor_status = "green" if _v.e_producao else "yellow"
    rprint(Panel(
        f"[bold]Caderneta[/bold] [bold]{_v.exibicao}[/bold]\n"
        f"Etapa: [cyan]{_v.etapa_nome}[/cyan]  |  "
        f"Status: [{cor_status}]{_v.status}[/{cor_status}]",
        border_style="blue",
        title="Status",
    ))

    arquivo_log = datalake / "audit.jsonl"

    if not arquivo_log.exists():
        rprint("[dim]Nenhum evento registrado ainda. Execute 'caderneta processar' para começar.[/dim]")
        return

    contadores: dict[str, int] = {}
    with open(arquivo_log, encoding="utf-8") as f:
        for linha in f:
            try:
                ev = json.loads(linha)
                t = ev.get("tipo", "DESCONHECIDO")
                contadores[t] = contadores.get(t, 0) + 1
            except json.JSONDecodeError:
                continue

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
# HELPERS INTERNOS
# =============================================================

def _listar_arquivos(caminho: Path) -> list[Path]:
    extensoes = {".ofx", ".qfx", ".csv", ".xml", ".pdf", ".jpg", ".jpeg", ".png"}
    if caminho.is_file():
        return [caminho] if caminho.suffix.lower() in extensoes else []
    return sorted(f for f in caminho.iterdir() if f.suffix.lower() in extensoes)


def _processar_arquivo(arquivo: Path, usuario: str, saida: Path, audit, bus) -> dict:
    """
    Tenta processar um arquivo com os parsers disponíveis.
    Retorna dict com resultado padronizado.
    """
    from core.motores_detector import DetectorDocumento, TipoNaoSuportadoError
    from core.motores_parsers_ofx import OFXParser
    from core.motores_parsers_csv import parsear_csv
    from core.rule_engine.classification_impl import RegrasDeterministicasPlugin
    from core.adapters.csv_exporter import ExportadorCSV
    from core.domain.entities import TipoDocumento
    import json

    resultado = {"sucesso": False, "lancamentos": 0, "revisao": 0, "erros": [], "avisos": []}

    try:
        detector = DetectorDocumento()
        hash_doc = detector.calcular_hash(arquivo)

        duplicata = audit.buscar_por_hash_documento(hash_doc)
        if duplicata:
            resultado["erros"].append(f"Duplicata: já processado em {duplicata.get('timestamp', '?')}")
            return resultado

        tipo = detector.detectar(arquivo)

        if tipo == TipoDocumento.OFX_STATEMENT:
            documentos = list(OFXParser().parsear(arquivo))
        elif tipo == TipoDocumento.CSV_STATEMENT:
            documentos = list(parsear_csv(arquivo))
        else:
            resultado["erros"].append(f"Tipo {tipo.value} ainda não suportado nos parsers determinísticos.")
            return resultado

        if not documentos:
            resultado["erros"].append("Nenhuma transação encontrada.")
            return resultado

        # Carrega regras do arquivo JSON se disponível
        regras_file = Path("dados/regras/regras_padrao.json")
        if regras_file.exists():
            from core.rule_engine.rule_entity import RegraClassificacaoV2
            from core.domain.entities import CodigoConta
            import uuid as _uuid
            with open(regras_file, encoding="utf-8") as f:
                dados = json.load(f)
            regras = []
            for r in dados:
                conta_d = CodigoConta(r["conta_debito"]) if r.get("conta_debito") else None
                conta_c = CodigoConta(r["conta_credito"]) if r.get("conta_credito") else None
                from core.rule_engine.rule_entity import RegraClassificacaoV2
                from core.domain.entities import CodigoConta as CC
                regras.append(RegraClassificacaoV2(
                    id=r.get("id", str(_uuid.uuid4())),
                    nome=r["nome"],
                    condicao=r["condicao_json"],
                    categoria=r.get("categoria"),
                    conta_debito=conta_d,
                    conta_credito=conta_c,
                    prioridade=r.get("prioridade", 100),
                ))
        else:
            regras = []

        classificador = RegrasDeterministicasPlugin(regras=regras, fornecedores=[])
        exportador = ExportadorCSV()

        lancamentos = []
        for doc in documentos:
            norm = classificador.normalizar_fornecedor(doc.nome_emitente or "")
            sugestao = classificador.sugerir_categoria(doc, None)

            from core.domain.entities import (
                Lancamento, Split, NaturezaLancamento,
                StatusLancamento, NivelAprovacao
            )

            splits = []
            if sugestao.conta_debito and sugestao.conta_credito and doc.valor_liquido:
                splits = [
                    Split(conta=sugestao.conta_debito,
                          natureza=NaturezaLancamento.DEBITO,
                          valor=doc.valor_liquido),
                    Split(conta=sugestao.conta_credito,
                          natureza=NaturezaLancamento.CREDITO,
                          valor=doc.valor_liquido),
                ]

            l = Lancamento(
                data_lancamento=doc.data_emissao,
                descricao=doc.nome_emitente or "SEM DESCRIÇÃO",
                splits=splits,
                categoria=sugestao.categoria,
                confidence=sugestao.confidence,
                metodo_classificacao=sugestao.metodo,
                status=StatusLancamento.PENDENTE,
                nivel_aprovacao=NivelAprovacao.UM_APROVADOR,
                pre_aprovado=sugestao.confidence >= 0.99,
            )
            if splits:
                try:
                    l.validar()
                    lancamentos.append(l)
                except ValueError as e:
                    resultado["avisos"].append(str(e))
                    continue

            if norm.precisa_revisao:
                resultado["avisos"].append(f"Fornecedor não reconhecido: '{doc.nome_emitente}'")

        if not lancamentos:
            resultado["erros"].append("Nenhum lançamento válido gerado.")
            return resultado

        exportacao = exportador.exportar(lancamentos, saida, prefixo=arquivo.stem)

        from core.audit.chain import TipoEvento
        audit.registrar(
            tipo=TipoEvento.DOCUMENTO_PROCESSADO,
            payload={"nome_arquivo": arquivo.name, "lancamentos": len(lancamentos)},
            documento_hash=hash_doc,
            usuario=usuario,
        )

        resultado["sucesso"] = True
        resultado["lancamentos"] = len(lancamentos)
        resultado["revisao"] = sum(1 for l in lancamentos if l.precisa_revisao)
        resultado["csv"] = exportacao.caminho.name
        resultado["hash_csv"] = exportacao.hash_sha256

    except TipoNaoSuportadoError as e:
        resultado["erros"].append(str(e))
    except Exception as e:
        resultado["erros"].append(str(e))

    return resultado


# Atalhos para imports internos que a CLI usa
# (evita importar diretamente — centraliza aqui)
try:
    from core.motores_detector import DetectorDocumento, TipoNaoSuportadoError  # type: ignore
except ImportError:
    # Durante instalação podem não estar disponíveis ainda
    pass


if __name__ == "__main__":
    app()

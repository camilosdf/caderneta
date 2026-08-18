#!/usr/bin/env python3
"""Script de release — gera pacote com nome versionado conforme ADR 007.

Uso:
  python infra/scripts/release.py               # gera pacote da versão atual
  python infra/scripts/release.py --next-rev    # incrementa revisão e gera
  python infra/scripts/release.py --next-etapa  # avança para próxima etapa
  python infra/scripts/release.py --producao    # promove 0.999.x → 1.0.0 (requer confirmação)

Saída:
  dist/caderneta-v0.003.001.tar.gz
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Adiciona raiz ao path para importar core.versao
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.versao import VERSAO, Versao, versao_para_audit


def registrar_homologacao(nova: Versao) -> None:
    """Registra VERSAO_HOMOLOGADA na trilha de auditoria (Gate 0 — B1).

    Antes desta função, o script apenas imprimia um lembrete para o
    operador registrar manualmente o evento — nunca chamava
    uow.audit.registrar(). A promoção para produção acontecia sem
    nenhuma evidência correspondente na trilha imutável.

    Falha fechada e propositalmente síncrona ao restante do fluxo: se o
    evento não puder ser gravado, a promoção inteira é abortada antes de
    qualquer arquivo ser alterado (pyproject.toml, core/versao.py) ou
    pacote gerado — auditoria é componente crítico, não um passo
    best-effort que pode ser pulado silenciosamente.
    """
    import os

    from core.audit.chain import TipoEvento
    from core.infra.db.session import SessionFactory
    from core.infra.unit_of_work import UnitOfWork

    url = os.getenv("DATABASE_URL")
    if not url:
        print(
            "\nERRO: DATABASE_URL não definida — não é possível registrar "
            "VERSAO_HOMOLOGADA na trilha de auditoria. Promoção abortada "
            "(nenhum arquivo foi alterado)."
        )
        sys.exit(1)

    try:
        factory = SessionFactory(url)
        with UnitOfWork(factory) as uow:
            uow.audit.registrar(
                tipo=TipoEvento.VERSAO_HOMOLOGADA,
                payload=versao_para_audit(nova),
            )
            uow.commit()
    except Exception as e:
        print(
            f"\nERRO ao registrar VERSAO_HOMOLOGADA na trilha de auditoria: {e}\n"
            f"Promoção abortada (nenhum arquivo foi alterado)."
        )
        sys.exit(1)

    print(f"\n✅ Evento VERSAO_HOMOLOGADA registrado na trilha de auditoria "
          f"({nova.exibicao}).")


def ler_versao_pyproject() -> str:
    toml = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
    if not m:
        raise ValueError("Versão não encontrada no pyproject.toml")
    return m.group(1)


def atualizar_pyproject(nova_versao: Versao) -> None:
    caminho = ROOT / "pyproject.toml"
    conteudo = caminho.read_text()
    conteudo = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{nova_versao.pep440}"',
        conteudo,
        flags=re.MULTILINE,
    )
    caminho.write_text(conteudo)
    print(f"  pyproject.toml → version = \"{nova_versao.pep440}\"")


def atualizar_versao_py(nova_versao: Versao) -> None:
    caminho = ROOT / "core" / "versao.py"
    conteudo = caminho.read_text()
    conteudo = re.sub(
        r'^(VERSAO_ATUAL\s*=\s*)"[^"]+"',
        f'\\1"{nova_versao.pep440}"',
        conteudo,
        flags=re.MULTILINE,
    )
    caminho.write_text(conteudo)
    print(f"  core/versao.py → VERSAO_ATUAL = \"{nova_versao.pep440}\"")


def gerar_pacote(versao: Versao, pasta_dist: Path) -> Path:
    pasta_dist.mkdir(parents=True, exist_ok=True)

    print(f"\nGerando pacote {versao.exibicao}...")

    # Gera o tar.gz com nome padrão do hatchling
    resultado = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(pasta_dist)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if resultado.returncode != 0:
        print("ERRO ao gerar pacote:")
        print(resultado.stderr)
        sys.exit(1)

    # Renomeia para o formato versionado do ADR 007
    arquivos_gerados = list(pasta_dist.glob("caderneta-*.tar.gz"))
    if not arquivos_gerados:
        # Fallback: criar arquivo diretamente
        destino = pasta_dist / f"{versao.nome_pacote}.tar.gz"
        resultado2 = subprocess.run(
            ["tar", "-czf", str(destino), "core", "shared", "ai", "README.md"],
            cwd=ROOT,
            capture_output=True,
        )
        if resultado2.returncode != 0:
            print("ERRO ao criar tar.gz de fallback")
            sys.exit(1)
        return destino

    arquivo = arquivos_gerados[0]
    destino = pasta_dist / f"{versao.nome_pacote}.tar.gz"

    if arquivo != destino:
        shutil.move(str(arquivo), str(destino))

    return destino


def main():
    parser = argparse.ArgumentParser(description="Release do Caderneta — ADR 007")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--next-rev",    action="store_true", help="Incrementar revisão")
    grupo.add_argument("--next-etapa",  action="store_true", help="Avançar para próxima etapa")
    grupo.add_argument("--producao",    action="store_true", help="Promover 0.999.x → 1.0.0")
    parser.add_argument("--dry-run",    action="store_true", help="Mostrar o que seria feito sem executar")
    parser.add_argument("--dist",       default="dist",      help="Pasta de saída")
    args = parser.parse_args()

    versao_atual = Versao.parse(ler_versao_pyproject())
    print(f"Versão atual: {versao_atual}")

    # Determinar nova versão
    if args.next_rev:
        nova = versao_atual.proxima_revisao()
        print(f"Nova versão:  {nova}")
    elif args.next_etapa:
        nova = versao_atual.proxima_etapa()
        print(f"Nova versão:  {nova}")
    elif args.producao:
        if not versao_atual.e_candidato:
            print(f"\nERRO: apenas versões 0.999.x podem ser promovidas para produção.")
            print(f"Versão atual: {versao_atual.exibicao} (etapa: {versao_atual.etapa})")
            print(f"Execute com --next-etapa até chegar em 0.999.x")
            sys.exit(1)
        confirmacao = input(
            f"\n⚠  ATENÇÃO: Promover {versao_atual.exibicao} → v1.000.000\n"
            f"Esta ação marca o sistema como APTO PARA DADOS REAIS.\n"
            f"Confirmar apenas após aprovação formal do CRC responsável.\n"
            f"Digite 'CONFIRMO' para prosseguir: "
        )
        if confirmacao.strip() != "CONFIRMO":
            print("Promoção cancelada.")
            sys.exit(0)
        nova = versao_atual.promover_producao()
        print(f"\n🎉 Promovendo para produção: {nova}")
    else:
        nova = versao_atual  # gerar pacote da versão atual sem alterar

    if args.dry_run:
        print(f"\n[DRY RUN] Seria gerado: {nova.nome_pacote}.tar.gz")
        print(f"[DRY RUN] Nenhum arquivo alterado.")
        return

    # Gate 0 — B1: registra a promoção na trilha de auditoria ANTES de
    # qualquer arquivo ser alterado (pyproject.toml, core/versao.py) ou
    # pacote gerado. Se a gravação falhar, a promoção inteira é abortada
    # aqui — não é aceitável marcar o sistema como produção sem o evento
    # correspondente na cadeia imutável (ver registrar_homologacao()).
    if args.producao:
        registrar_homologacao(nova)

    # Atualizar arquivos se a versão mudou
    if nova != versao_atual:
        print(f"\nAtualizando arquivos de versão...")
        atualizar_pyproject(nova)
        atualizar_versao_py(nova)

    # Gerar pacote
    pasta_dist = ROOT / args.dist
    arquivo = gerar_pacote(nova, pasta_dist)

    print(f"\n✅ Pacote gerado: {arquivo.name}")
    print(f"   Caminho:  {arquivo}")
    print(f"   Versão:   {nova}")
    print(f"   Status:   {nova.status}")

    if nova.e_producao:
        print(f"\n🎉 VERSÃO DE PRODUÇÃO — VERSAO_HOMOLOGADA já registrado "
              f"na trilha de auditoria (Gate 0 — B1).")


if __name__ == "__main__":
    main()

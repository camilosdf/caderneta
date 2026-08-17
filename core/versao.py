"""Controle de versão do Caderneta — ADR 007.

Formato interno (PEP 440): FASE.ETAPA.REVISÃO  ex: 0.3.1
Formato exibição:          vF.EEE.RRR           ex: v0.003.001

FASE    0 = pré-produção | 1+ = produção
ETAPA   0-9 mapeia às 10 etapas de maturidade | 999 = candidato a produção
REVISÃO incremento sequencial dentro da etapa
"""

from dataclasses import dataclass


# Versão canônica — única fonte da verdade
# Sincronizada com pyproject.toml (atualizar ambos juntos)
#
# Etapa 9 (Integração GnuCash) concluída fora de ordem — ver Emenda E-12
# (ADR 004). Etapas 6 (Interface Web), 7 (IA) e 8 (Conciliação avançada)
# permanecem pendentes apesar do dígito ETAPA=9.
VERSAO_ATUAL = "0.9.0"


@dataclass(frozen=True)
class Versao:
    fase: int      # 0 = pré-produção, 1+ = produção
    etapa: int     # 0-9 ou 999 (candidato)
    revisao: int   # incremento sequencial

    @classmethod
    def parse(cls, texto: str) -> "Versao":
        """Aceita '0.3.1' ou 'v0.003.001'."""
        limpo = texto.lstrip("v").strip()
        # Normaliza zeros à esquerda: '0.003.001' → '0.3.1'
        partes = [str(int(p)) for p in limpo.split(".")]
        if len(partes) != 3:
            raise ValueError(
                f"Versão inválida: '{texto}'. Esperado FASE.ETAPA.REVISÃO"
            )
        return cls(
            fase=int(partes[0]),
            etapa=int(partes[1]),
            revisao=int(partes[2]),
        )

    @property
    def e_producao(self) -> bool:
        return self.fase >= 1

    @property
    def e_candidato(self) -> bool:
        return self.fase == 0 and self.etapa == 999

    @property
    def etapa_nome(self) -> str:
        nomes = {
            0: "Fundação",
            1: "Domínio",
            2: "Pipeline",
            3: "Parsers",
            4: "Motor Contábil",
            5: "Auditoria",
            6: "Interface",
            7: "IA",
            8: "Conciliação",
            9: "Integrações",
            999: "Candidato a Produção",
        }
        return nomes.get(self.etapa, f"Etapa {self.etapa}")

    @property
    def pep440(self) -> str:
        """Formato PEP 440 para pyproject.toml e PyPI: '0.3.1'"""
        return f"{self.fase}.{self.etapa}.{self.revisao}"

    @property
    def exibicao(self) -> str:
        """Formato de exibição para humanos: 'v0.003.001'"""
        return f"v{self.fase}.{self.etapa:03d}.{self.revisao:03d}"

    @property
    def nome_pacote(self) -> str:
        """Nome do arquivo de pacote: 'caderneta-v0.003.001'"""
        return f"caderneta-{self.exibicao}"

    @property
    def status(self) -> str:
        if self.e_producao:
            return "produção"
        if self.e_candidato:
            return "candidato a produção"
        return "pré-produção"

    def __str__(self) -> str:
        return f"{self.exibicao} ({self.etapa_nome} — {self.status})"

    def __lt__(self, other: "Versao") -> bool:
        return (self.fase, self.etapa, self.revisao) < (other.fase, other.etapa, other.revisao)

    def proxima_revisao(self) -> "Versao":
        return Versao(self.fase, self.etapa, self.revisao + 1)

    def proxima_etapa(self) -> "Versao":
        proxima = 999 if self.etapa == 9 else self.etapa + 1
        return Versao(self.fase, proxima, 0)

    def promover_producao(self) -> "Versao":
        """v0.999.x → v1.000.000 — requer aprovação formal do CRC."""
        if not self.e_candidato:
            raise ValueError(
                f"Apenas candidatos (etapa 999) podem ser promovidos. "
                f"Versão atual: {self.exibicao}"
            )
        return Versao(1, 0, 0)


# Instância da versão atual — importar de qualquer lugar do sistema
VERSAO = Versao.parse(VERSAO_ATUAL)


def versao_para_audit(versao: "Versao | None" = None) -> dict:
    """Retorna dict para gravação no audit log.

    versao é opcional e usa o singleton global VERSAO por padrão — mas
    chamadores que já têm uma Versao recém-calculada em mãos (ex.:
    infra/scripts/release.py registrando VERSAO_HOMOLOGADA antes de
    reescrever core/versao.py em disco) devem passá-la explicitamente.
    O singleton global só reflete o valor gravado em VERSAO_ATUAL no
    momento em que este processo foi iniciado — não a versão sendo
    promovida na chamada atual.
    """
    v = versao if versao is not None else VERSAO
    return {
        "versao_pep440": v.pep440,
        "versao_exibicao": v.exibicao,
        "etapa": v.etapa_nome,
        "status": v.status,
        "e_producao": v.e_producao,
    }

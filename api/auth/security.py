"""Hash e verificação de senha — Argon2id (ADR 008, Seção 4).

Funções puras, sem estado. Nunca importadas por core/ — a direção de
dependência é sempre api/ → core/, nunca o inverso (ADR 008, matriz de
importação). core/infra/repositories/usuario_repository.py armazena e
retorna o hash como dado opaco; só este módulo o interpreta.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_senha(senha_texto: str) -> str:
    """Gera o hash Argon2id de uma senha em texto puro.

    O hash resultante já inclui salt e parâmetros do algoritmo — nunca
    armazenar a senha em texto puro em nenhum lugar (incluindo audit log).
    """
    return _hasher.hash(senha_texto)


def verificar_senha(senha_texto: str, hash_armazenado: str) -> bool:
    """Verifica se a senha em texto puro corresponde ao hash armazenado.

    Retorna False tanto para senha incorreta quanto para hash malformado —
    nunca levanta exceção para o chamador tratar como caso especial, para
    evitar vazar informação sobre por que a verificação falhou.
    """
    try:
        return _hasher.verify(hash_armazenado, senha_texto)
    except VerifyMismatchError:
        return False
    except Exception:
        # Hash malformado, vazio, ou qualquer outra falha de verificação —
        # trata como senha incorreta, nunca propaga o erro interno.
        return False

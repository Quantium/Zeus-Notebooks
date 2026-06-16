"""
lisa_client.py
──────────────
Cliente Python para la API de Integración LISA (Libra Fármacos / Plataforma Galileo).

╔══════════════════════════════════════════════════════════════════════════╗
║  ÚNICO ENDPOINT: entradas_almacen (SGA)                                  ║
║                                                                          ║
║  Este archivo expone el único endpoint canónico. Los wrappers heredados  ║
║  (pedidos, albaranes, licitaciones, catálogos) viven en                  ║
║  `lisa_old_client.py` durante el periodo de deprecación.                 ║
║                                                                          ║
║  NO agregues aquí endpoints que no sean del módulo SGA.                  ║
║                                                                          ║
║  Uso:  client.entradas_almacen(fecha_gen="01/06/2026", almacen="5460D")  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Configuración por defecto ──────────────────────────────────────────────
BASE_URL = "https://interfaces.librafarmacos.com.mx"
DEFAULT_TOKEN = os.getenv("LISA_TOKEN", "")
TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lisa")


# ─── Excepción ───────────────────────────────────────────────────────────────
class LisaAPIError(Exception):
    """Error en la comunicación con la API LISA."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[HTTP {status_code}] {message}")


# ─── Protocolo — ISP ─────────────────────────────────────────────────────────
@runtime_checkable
class EntradasAPI(Protocol):
    def entradas_almacen(self, fecha_gen: str, almacen: str = "", **kwargs: Any) -> dict: ...


# ─── Presentación — SRP ──────────────────────────────────────────────────────
class Presenter:
    @staticmethod
    def pretty(obj: Any) -> str:
        return json.dumps(obj, indent=2, ensure_ascii=False)

    @classmethod
    def resumen(cls, response: dict, etiqueta: str) -> None:
        print(f"\n{'─' * 60}")
        print(f"▶ {etiqueta}")
        print("─" * 60)

        registros = response.get("registros", {})
        reg = registros.get("reg") or []
        if isinstance(reg, dict):
            reg = [reg]

        total = registros.get("rowstat", {}).get("numero_registros", len(reg))
        print(f"Total de registros: {total}")

        if reg:
            print("\nPrimer registro:")
            print(cls.pretty(reg[0]))
        else:
            print("(sin registros)")


# ─── Cliente principal ───────────────────────────────────────────────────────
class LisaClient:
    """
    Cliente REST para la API de Integración LISA — sólo endpoint canónico SGA.
    Implementa EntradasAPI.

    El parámetro `session` permite inyectar un objeto compatible con
    requests.Session (p.ej. un mock en tests) sin tocar el transporte real.
    """

    # OCP: extender el mapeo no requiere modificar la lógica de _post.
    _HTTP_MESSAGES: dict[int, str] = {
        400: "Parámetros incorrectos en la llamada.",
        401: "No autorizado (token inválido o expirado).",
        403: "Sin permisos para acceder al recurso.",
        404: "Recurso no encontrado.",
        500: "Error interno del servidor de EDISA.",
    }

    def __init__(
        self,
        token: str = DEFAULT_TOKEN,
        base_url: str = BASE_URL,
        timeout: int = TIMEOUT,
        session: requests.Session | None = None,  # DIP: inyectable para tests
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def _post(
        self,
        path: str,
        data: dict[str, Any],
        pag: int | None = None,
        regs: int | None = None,
    ) -> dict[str, Any]:
        """Transporte compartido. Subclases (ej. LisaOldClient) lo reutilizan."""
        url = f"{self.base_url}{path}"

        params: dict[str, Any] = {"l$token": self.token}
        if pag is not None:
            params["l$pag"] = pag
        if regs is not None:
            params["l$regs"] = regs

        clean_data = {k: v for k, v in data.items() if v not in (None, "")}
        log.info("POST %s | body: %s", path, clean_data)

        try:
            r = self._session.post(url, params=params, data=clean_data, timeout=self.timeout)
        except requests.RequestException as e:
            raise LisaAPIError(0, f"Error de red: {e}") from e

        if r.status_code != 200:
            message = self._HTTP_MESSAGES.get(r.status_code, f"Error HTTP {r.status_code}")
            raise LisaAPIError(r.status_code, message)

        try:
            return r.json()
        except ValueError as e:
            raise LisaAPIError(
                r.status_code,
                f"Respuesta no es JSON válido: {e} | body={r.text[:200]}",
            ) from e

    # ════════════════════════════════════════════════════════════════════════
    # ★ ENDPOINT PRINCIPAL — SGA / Entradas a almacén  ★
    # ════════════════════════════════════════════════════════════════════════
    def entradas_almacen(
        self,
        fecha_gen: str,
        almacen: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Recepciones de mercancía (entradas) registradas en el SGA.

        Parámetros:
            fecha_gen: obligatorio, formato dd/mm/aaaa.
            almacen:   código de almacén (ej. "5460D"). Vacío = todos.
            pag:       número de página. None = sin paginar.
            regs:      registros por página. -1 (default) = todos.

        El parámetro de "traer todos los registros" es `l$regs=-1`,
        NO `l$pag=-1` — confundirlos hace que el servidor caiga al default.
        """
        if not fecha_gen:
            raise ValueError("fecha_gen es obligatorio (formato dd/mm/aaaa)")
        return self._post(
            "/galileo/lisa/geninf/isp/sga_entradas",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
            },
            pag=pag,
            regs=regs,
        )


# ─── Ejecución directa ───────────────────────────────────────────────────────
def main() -> None:
    """Corre el endpoint canónico contra el servidor con un ejemplo."""
    client = LisaClient()
    etiqueta = "★ Entradas SGA | fecha_gen=01/06/2026, almacen=5460D"
    try:
        Presenter.resumen(
            client.entradas_almacen(fecha_gen="01/06/2026", almacen="5460D"),
            etiqueta,
        )
    except LisaAPIError as e:
        log.error("❌ %s — %s", etiqueta, e)
    except Exception as e:  # noqa: BLE001
        log.exception("❌ %s — error inesperado: %s", etiqueta, e)


if __name__ == "__main__":
    main()

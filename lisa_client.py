"""
lisa_client.py
──────────────
Cliente Python para la API de Integración LISA (Libra Fármacos / Plataforma Galileo).

╔══════════════════════════════════════════════════════════════════════════╗
║  ENDPOINTS DEL MÓDULO SGA — contrato: edisa.json (EDISA)                 ║
║                                                                          ║
║  entradas_almacen · entradas_almacen_2 · colocacion · colocacion_2      ║
║  preparacion · preparacion_2 · embalaje · embalaje_2                    ║
║  actividad_maquina · actividad_maquina_2 · actividad_maquina_historico  ║
║                                                                          ║
║  Los wrappers heredados (pedidos, albaranes, licitaciones, catálogos)    ║
║  viven en `lisa_old_client.py` durante el periodo de deprecación.        ║
║  NO agregues aquí endpoints que no sean del módulo SGA.                  ║
║                                                                          ║
║  Fechas de PETICIÓN en ISO `AAAA-MM-DD` (jul-2026: la máscara Oracle     ║
║  cambió; `dd/mm/aaaa` da ORA-01830 y `dd/mm/aa` se malinterpreta como    ║
║  año 1 en silencio). Las fechas de RESPUESTA quedaron mixtas:            ║
║  entradas/entradas_2/colocacion_2/embalaje_2 en dd/mm/aaaa;              ║
║  preparacion(_2)/embalaje en ISO 8601.                                   ║
║                                                                          ║
║  Uso:  client.entradas_almacen(fecha_gen="2026-06-01", almacen="5460D")  ║
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
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Recepciones de mercancía (entradas) registradas en el SGA.
        Nivel tarea; NO expone cantidades — para piezas usa entradas_almacen_2.

        Parámetros:
            fecha_gen: obligatorio, formato ISO AAAA-MM-DD (cota inferior).
            almacen:   código de almacén (ej. "5460D"). Vacío = todos.
            empresa:   código de empresa Libra. Vacío = todas.
            pag:       número de página. None = sin paginar.
            regs:      registros por página. -1 (default) = todos.

        El parámetro de "traer todos los registros" es `l$regs=-1`,
        NO `l$pag=-1` — confundirlos hace que el servidor caiga al default.
        """
        if not fecha_gen:
            raise ValueError("fecha_gen es obligatorio (formato ISO AAAA-MM-DD)")
        return self._post(
            "/galileo/lisa/geninf/isp/sga_entradas",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def entradas_almacen_2(
        self,
        fecha_gen: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Entradas con detalle de LÍNEA: artículo, lote, palet y
        `cantidad_presentacion` (piezas) — el único endpoint de entradas
        que expone cantidades. Incluye descripciones (d_*) y `numero_tarea`
        para ligar con entradas_almacen.

        OJO (verificado jul-2026): el servidor IGNORA el filtro de fecha en
        este endpoint (devuelve toda la historia); se acepta el parámetro por
        simetría/futuro. `p_almacen` sí filtra.
        """
        return self._post(
            "/galileo/lisa/geninf/isp/sga_entradas_2",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    # ════════════════════════════════════════════════════════════════════════
    # Resto de endpoints SGA (contrato edisa.json)
    # Todos los filtros son opcionales; vacío = sin filtrar.
    # Fechas ISO AAAA-MM-DD.
    # ════════════════════════════════════════════════════════════════════════
    def colocacion(
        self,
        fecha_gen: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """Tareas de colocación (ubicación de mercancía recibida) del SGA."""
        return self._post(
            "/galileo/lisa/geninf/isp/sga_colocacion",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def colocacion_2(
        self,
        fecha_gen: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """Colocación con descripciones (campos d_*: máquina, zona, artículo…)."""
        return self._post(
            "/galileo/lisa/geninf/isp/sga_colocacion_2",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def preparacion(
        self,
        fecha_gen: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Tareas de preparación/surtido (picking) con detalle de líneas de pedido.
        Desde jul-2026 incluye piezas por línea: `cantidad_unidad1_ped`,
        `cantidad_unidad1_res` y `cantidad_facturada`.
        """
        return self._post(
            "/galileo/lisa/geninf/isp/sga_preparacion",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def preparacion_2(
        self,
        fecha_tarea: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Resumen de preparación por usuario/máquina (tareas, líneas, cantidades,
        tiempo_segundos). OJO: el filtro de fecha es `p_fecha_tarea`,
        no `p_fecha_gen`.

        OJO (verificado 21-jul-2026): los datos siguen congelados — el servidor
        solo devuelve el periodo 09-feb → 10-abr-2026, sin importar el filtro.
        Para series vivas de surtido usa `preparacion` (cantidad_unidad1_ped).
        """
        return self._post(
            "/galileo/lisa/geninf/isp/sga_preparacion_2",
            {
                "p_fecha_tarea": fecha_tarea,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def embalaje(
        self,
        fecha_gen: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Tareas de embalaje (empaquetado en box para embarque) del SGA.
        Nivel tarea; NO expone cantidades — para piezas usa embalaje_2.
        """
        return self._post(
            "/galileo/lisa/geninf/isp/sga_embalaje",
            {
                "p_fecha_gen": fecha_gen,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def embalaje_2(
        self,
        fecha_tarea: str = "",
        almacen: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """
        Embalaje con detalle de LÍNEA: artículo, lote y `cantidad_presentacion`
        (piezas) — el único endpoint de embalaje que expone cantidades.
        Incluye `tarea` para ligar con embalaje. OJO: el filtro de fecha es
        `p_fecha_tarea`, no `p_fecha_gen`.

        OJO (verificado 21-jul-2026): el servidor IGNORA el filtro de fecha
        (devuelve toda la historia, igual que entradas_almacen_2); se acepta el
        parámetro por simetría/futuro. `p_almacen` sí filtra. A diferencia de
        embalaje (ISO 8601), responde las fechas en `dd/mm/aaaa HH:MM:SS`.
        """
        return self._post(
            "/galileo/lisa/geninf/isp/sga_embalaje_2",
            {
                "p_fecha_tarea": fecha_tarea,
                "p_almacen": almacen,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )

    def actividad_maquina(
        self,
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """Actividad actual por máquina (tareas en curso). Sin filtros."""
        return self._post(
            "/galileo/lisa/geninf/isp/sga_act_maq",
            {},
            pag=pag,
            regs=regs,
        )

    def actividad_maquina_2(
        self,
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """Actividad por usuario con pedido/cliente/artículo y tiempo. Sin filtros."""
        return self._post(
            "/galileo/lisa/geninf/isp/sga_act_maq_2",
            {},
            pag=pag,
            regs=regs,
        )

    def actividad_maquina_historico(
        self,
        fecha: str = "",
        empresa: str = "",
        pag: int | None = None,
        regs: int | None = -1,
    ) -> dict:
        """Histórico de acciones sobre tareas (endpoint sga_act_maq_3)."""
        return self._post(
            "/galileo/lisa/geninf/isp/sga_act_maq_3",
            {
                "p_fecha": fecha,
                "p_empresa": empresa,
            },
            pag=pag,
            regs=regs,
        )


# ─── Ejecución directa ───────────────────────────────────────────────────────
def main() -> None:
    """Corre el endpoint canónico contra el servidor con un ejemplo."""
    client = LisaClient()
    etiqueta = "★ Entradas SGA | fecha_gen=2026-06-01, almacen=5460D"
    try:
        Presenter.resumen(
            client.entradas_almacen(fecha_gen="2026-06-01", almacen="5460D"),
            etiqueta,
        )
    except LisaAPIError as e:
        log.error("❌ %s — %s", etiqueta, e)
    except Exception as e:  # noqa: BLE001
        log.exception("❌ %s — error inesperado: %s", etiqueta, e)


if __name__ == "__main__":
    main()

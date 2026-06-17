# Zeus-Notebooks

## ⚠️ Deuda técnica — fuente de datos del dashboard horario

**Principio:** la *fuente única de la verdad* debe ser el **API SGA** (`POST
/galileo/lisa/geninf/isp/sga_entradas`). Todo lo demás se construye sobre esa importación.

**Excepción temporal (a revertir):** el dashboard de *carga de trabajo por hora* de
`fuente_unica_entradas.ipynb` (**sección 6**) **NO usa el API**, sino que lee directamente
de la **BD Zeus** (tabla `ds_entradas`, vía `ZEUS_DATABASE_URL`).

**Por qué:** el API SGA devuelve las fechas **sin hora** (`fecha_gen` / `fecha_inicio` /
`fecha_fin` llegan como `dd/mm/aaaa`, todas a las 00:00). La BD Zeus sí conserva la marca de
tiempo completa (esos campos son `TIMESTAMP` con `HH:MM:SS` reales en `ds_entradas`), y sin
hora es imposible analizar la carga por hora ni qué usuarios están activos en cada hora del
día.

**Qué hacer cuando el API entregue las horas (TODO de migración):**

1. Cuando el endpoint `sga_entradas` empiece a devolver `fecha_inicio` (y/o `fecha_gen` /
   `fecha_fin`) **con hora**, hay que **mover la sección 6 de vuelta al API**.
2. En la celda de carga de la sección 6, reemplazar la lectura `pd.read_sql(... ds_entradas
   ..., ZEUS_DATABASE_URL)` por el `df_limpio` que ya produce el API (secciones 1–3), y
   ajustar la limpieza de fechas para que **preserve la hora** (hoy `pd.to_datetime(...,
   format="mixed", dayfirst=True)` ya la conservaría si el API la enviara).
3. Eliminar la dependencia de `ZEUS_DATABASE_URL` en ese notebook y validar que el dashboard
   horario sale igual con datos del API.
4. Tras eso, **el API vuelve a ser la fuente única** (objetivo del repo).

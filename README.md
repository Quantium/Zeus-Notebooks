# Zeus-Notebooks

## Fuente de datos del dashboard horario — API SGA (migración completada)

**Principio:** la *fuente única de la verdad* es el **API SGA** (`POST
/galileo/lisa/geninf/isp/sga_entradas`). Todo se construye sobre esa importación.

**Estado (resuelto):** el dashboard de *carga de trabajo por hora* de
`fuente_unica_entradas.ipynb` (**sección 6**) y el pronóstico de horas hombre de
`prediccion_horas_hombre.ipynb` ya leen del **API SGA**, no de la BD Zeus.

**Antecedente:** durante un tiempo el API SGA devolvía las fechas **sin hora** (`fecha_gen` /
`fecha_inicio` / `fecha_fin` llegaban como `dd/mm/aaaa`, todas a las 00:00), así que esos
análisis horarios leían directamente la BD Zeus (tabla `ds_entradas`, vía `ZEUS_DATABASE_URL`),
donde esos campos eran `TIMESTAMP` con `HH:MM:SS` reales. **Hoy el API ya entrega la hora
real**, por lo que esa excepción quedó cerrada.

**Lo que cambió en la migración:**

1. `fuente_unica_entradas.ipynb` §6 reutiliza el `df_limpio` que ya producen las secciones
   1–5 desde el API; la ventana del dashboard sigue al parámetro `FECHA_GEN`.
2. `prediccion_horas_hombre.ipynb` consulta el API con `fecha_gen` como **cota inferior**
   (una fecha temprana trae toda la historia disponible en una sola llamada) y arma la serie
   horaria sobre `fecha_inicio`.
3. Se eliminó la dependencia de `ZEUS_DATABASE_URL` en ambos notebooks. (Los notebooks
   heredados por dominio —`recibo.ipynb`, `surtido.ipynb`, etc.— no se tocaron.)
4. El API vuelve a ser la **fuente única** (objetivo del repo).

**Nota sobre `p_fecha_gen`:** funciona como cota inferior ("de esta fecha en adelante"), no
como filtro de día exacto; por eso una sola llamada con fecha temprana reconstruye toda la
serie histórica disponible (~5–6 meses al momento de la migración).

# Guía de usuario — PC Parts Organizer

Manual completo de uso de la aplicación. Los nombres de acciones y pestañas se indican en el idioma en que aparecen; el manual está escrito en español (idioma predeterminado).

> **Advertencia epistemológica.** El análisis de compatibilidad no certifica la compatibilidad total de un equipo. Presenta conclusiones acotadas a relaciones concretas y declara lo que **no** evalúa. Un resultado «compatible» en una relación no garantiza que otras dimensiones (eléctricas, térmicas, geométricas) hayan sido comprobadas. Consulta la sección de compatibilidad de `ARQUITECTURA.md`.

---

## A. Primer uso

### Iniciar la aplicación

```bat
python -m pc_parts_organizer
```

Se abre la ventana principal con el tema oscuro y la barra de pestañas: **Inicio**, **Inventario**, **Equipos**, **Catálogo**.

### Pestañas y navegación

| Pestaña | Contenido |
|---|---|
| Inicio | Resumen del inventario: total, distribución por categoría, precios registrados |
| Inventario | Tabla de componentes con búsqueda, filtros, acciones y detalle |
| Equipos | Lista de builds, alta, detalle, comparador |
| Catálogo | Referencias comerciales, importación/exportación, selector |

El selector de idioma está en la cabecera (ES/EN) y se guarda en `settings.json`.

### Dónde se almacenan los datos

Fuera del repositorio, en el directorio de datos local del sistema (Windows):

```
%LOCALAPPDATA%\PCPartsOrganizer\
  components.json     Inventario + builds + perfiles técnicos
  settings.json       Idioma
  catalog.sqlite3     Catálogo de referencias
  backups\            Copias preventivas de restauración
```

No edites estos archivos a mano salvo los procedimientos documentados en `MANTENIMIENTO.md`.

### Catálogo e inventario: la diferencia clave

- **Catálogo**: biblioteca de referencia reutilizable (fabricante, modelo, specs, notas, procedencia comercial). No pertenece a tu colección.
- **Inventario**: tus componentes reales, con estado, ubicación, precios, perfiles técnicos y verificaciones.

Incorporar desde catálogo **copia** solo los campos con equivalencia real (categoría, fabricante, modelo, especificaciones, notas). La procedencia comercial (`source`, URL, licencia, atribución, fecha de verificación comercial) **nunca** se convierte en verificación técnica.

---

## B. Catálogo e inventario

### Buscar componentes en el catálogo

1. Ve a **Catálogo**.
2. Escribe por fabricante o modelo y pulsa **Buscar**.
3. Filtra por categoría y ajusta el tamaño de página (`Mostrar: 100 / Todos`).
4. Usa **Anterior/Siguiente** para paginación.

### Añadir componentes desde el catálogo (selección múltiple)

1. En **Inventario**, pulsa **Añadir desde catálogo**.
2. Selecciona varias filas (clic, Mayús para rango, Ctrl para añadir).
3. Cambia de página si lo necesitas: **la selección se conserva** entre páginas.
4. El indicador **Seleccionados: N** muestra el total acumulado.
5. Pulsa **Añadir seleccionados** para confirmar o **Cancelar**.

**Duplicados y omisiones.** El sistema compara por identidad normalizada (categoría + fabricante + modelo, sin distinción de mayúsculas ni de espacios redundantes). Los duplicados se omiten y se informan por nombre con el componente equivalente. No se crean registros duplicados.

**Informe.** Tras confirmar, se abre un diálogo con los totales y la lista completa y desplazable: creados, duplicados omitidos (con el nombre coincidente) y rechazos (con motivo).

**Rechazo atómico.** Si alguna entrada es inválida, **no se incorpora nada** y se muestra el motivo por entrada. No hay incorporaciones parciales.

> **Nota.** La incorporación crea componentes en el inventario y los deja **sin asignar** a ningún equipo. La asignación a builds se hace de forma individual (sección D).

### Importar componentes desde un CSV

1. En **Inventario**, pulsa **Importar CSV** (o descarga primero la **plantilla CSV** con **Descargar plantilla CSV**).
2. Elige el archivo `.csv`. La aplicación detecta codificación (UTF-8 con/sin BOM, UTF-16, Windows-1252) y delimitador (coma, punto y coma, tabulador).
3. Revisa la **vista previa**: totales por estado y tabla completa con línea de origen, estado, motivo y coincidencia de duplicado.
4. Si la detección no es fiable, cambia codificación o delimitador y pulsa **Volver a analizar**.
5. Pulsa **Importar filas válidas** o **Cancelar**.

**Formato canónico.** Encabezados `category,manufacturer,model,specs,notes` (orden libre; se aceptan alias en español e inglés como `categoría`, `fabricante`, `modelo`, `especificaciones`, `notas`). Solo categoría, fabricante y modelo son obligatorios. Las columnas desconocidas (p. ej. `verified_at`, `source`) se listan como no importables y se ignoran: nunca se convierten en verificaciones.

**Duplicados.** Se detectan contra el inventario y dentro del archivo por identidad normalizada. Los duplicados se omiten y se informan; las filas rechazadas se informan con motivo y número de línea. La incorporación usa una única operación transaccional: o se crean todas las filas válidas o no se escribe nada.

### Crear y editar componentes

- **Añadir componente** (Inventario): abre el formulario con categoría, fabricante, modelo, especificaciones, notas, estado, ubicación, fechas, precio y moneda. Los precios y la moneda deben indicarse juntos o dejarse ambos vacíos.
- **Editar** / **Ver detalles**: disponibles con una única fila seleccionada. El detalle muestra el componente y sus datos técnicos.
- **Buscar en catálogo** dentro del formulario: rellena categoría, fabricante, modelo y especificaciones de la referencia seleccionada. No modifica estado ni ubicación.

### Eliminar varios componentes

1. En **Inventario**, selecciona varias filas.
2. Pulsa **Eliminar seleccionados**.
3. El diálogo de confirmación muestra: seleccionados, eliminables y protegidos por estar asignados, con la **lista completa** de protegidos (nombre + equipo).
4. Confirma con **Eliminar** o cancela.

**Protección de asignados.** Un componente asignado a un equipo **no se puede eliminar**; se conserva íntegramente y se reporta con el nombre del equipo que lo protege. Para eliminarlo, retíralo primero del equipo. El servicio revalida las condiciones al ejecutar: la evaluación visual previa no sustituye la validación transaccional.

**Resultado.** Diálogo desplazable con eliminados, omitidos por asignación (nombre y equipo) y no encontrados. No hay eliminación masiva por atajos accidentales: solo la acción explícita.

---

## C. Perfiles técnicos

Los perfiles técnicos son la base de la compatibilidad. Se crean desde el detalle de un componente (**Añadir datos técnicos**) y solo para categorías con registro de atributos (CPU, GPU, Motherboard, RAM, Storage, PSU, Case, Cooling, Other).

### Crear y completar

1. Abre el detalle del componente.
2. **Añadir datos técnicos**.
3. Completa los atributos que apliquen (p. ej. `memory_generation`, `module_form_factor`, `total_capacity_gb`, `module_count` para RAM).
4. Para cada atributo registra: **valor**, **unidad** (si aplica), **procedencia**, **confianza**, **estado de verificación**, **referencia de evidencia** y **fecha de verificación**.

### Estados de verificación

| Estado | Significado |
|---|---|
| Sin verificar | Valor declarado sin respaldo |
| Verificado con referencia | Requiere evidencia y fecha de verificación |
| Requiere revisión | Dato modificado o pendiente de confirmar |

**Advertencia.** Marcar como verificado exige referencia de evidencia y fecha. No declares verificación sin respaldo: la aplicación no autentica la documentación por ti.

### Confianza y procedencia

- **Procedencia** (`source`): entrada de usuario, importación de catálogo, documentación oficial, inferido/normalizado, desconocida.
- **Confianza**: alta, media, baja.

### Colecciones completas y parciales

Atributos como ranuras M.2, puertos SATA o inventario de cables PSU admiten declarar **exhaustividad** (completa/parcial/desconocida) y un **ámbito** que describa qué cubre. Marca «completa» solo tras comprobar la fuente completa; la aplicación no verifica por sí misma la exhaustividad.

### Revalidar valores modificados

Si un atributo verificado cambia de valor, el sistema lo exige revisión y conserva la evidencia anterior. Confirma explícitamente que la evidencia sigue respaldando el valor actual (o aporta evidencia nueva). Sin este paso, el dato no queda verificado.

---

## D. Builds (equipos)

### Crear una configuración

1. Ve a **Equipos** → **Añadir equipo**.
2. Indica nombre (obligatorio y único, sin distinguir mayúsculas), tipo (Actual/Planificado), notas y componentes.
3. La asignación es **individual y única**: un componente no puede estar en dos equipos a la vez.

### Consultar detalles y analizar

- **Ver detalles** muestra composición agrupada por categoría, análisis de compatibilidad y auditoría técnica.
- **Analizar compatibilidad** ejecuta el motor sobre el estado actual. Los resultados se marcan como obsoletos si cambia el equipo, sus componentes, perfiles o asociaciones; vuelve a analizar.

### Resultados y severidades

| Resultado | Significado |
|---|---|
| Compatible | Las relaciones evaluadas pasaron con datos verificados suficientes |
| Incompatible | Contradicción técnica confirmada (solo con atributos verificados) |
| Requiere verificación | Condiciones no suficientemente verificadas; no es incompatibilidad |
| Datos insuficientes | Faltan atributos necesarios para concluir |

Severidades: **Crítica** (incompatibilidad confirmada), **Advertencia**, **Información**.

### Limitaciones y datos pendientes

El detalle muestra **Relaciones no evaluadas** (categorías sin reglas), **Limitaciones del análisis**, hallazgos con **Información que falta** y **Acción recomendada**. Los participantes implicados se listan con su categoría y nombre; desde el combo de hallazgos puedes abrir el componente implicado.

---

## E. Calidad de datos

Accede desde **Inventario** → **Revisar datos**.

### Resumen y filtros

- **Resumen**: conteos por estado y totales.
- **Filtros** por categoría, estado de atributo y texto de búsqueda, con paginación.
- **Tabla de componentes** con su estado epistémico por atributo.
- **Cola de revisión**: atributos pendientes que consumen reglas del motor (usados por), ordenados por prioridad.

### Corregir datos

Selecciona un componente pendiente y usa **Editar datos técnicos** para corregir valores o completar evidencia. Al guardar, el centro de calidad se recalcula; los hallazgos bloqueados por datos pendientes pueden resolverse o cambiar.

---

## F. Auditoría técnica

Disponible en el detalle de un equipo (sección **Auditoría técnica**), calculada desde el análisis fresco y los perfiles.

### Qué muestra

- **Resumen**: incompatibles, verificación pendiente, datos insuficientes, no evaluado, atributos relevantes pendientes y metadatos inconsistentes.
- **Incompatibilidades demostradas**: regla, resultado, severidad y componentes.
- **Verificación pendiente** e **insuficientes datos**: hallazgo + atributos vinculados, marcados como **Relación directa** (la información que falta nombra el atributo) o **Contexto compartido** (regla que consume el atributo).
- **Relaciones no evaluadas** y **Limitaciones**.
- **Atributos relevantes pendientes** y **Otros atributos pendientes** (no bloqueantes ahora).

### Interpretación

- La auditoría **enuncia hechos e información pendiente**; no es una puntuación ni certifica compatibilidad.
- Una **incompatibilidad demostrada** es una contradicción con atributos verificados.
- Una **incertidumbre** (`requires_verification`) indica falta de verificación, no una incompatibilidad.
- Los enlaces a componentes usan etiquetas legibles (categoría + fabricante/modelo), nunca identificadores internos.

---

## G. Comparador de builds

Accede desde **Equipos** → **Comparar equipos** (requiere al menos dos).

1. Selecciona A y B.
2. Se muestra el resumen: comunes, **añadidos**, **retirados** y **sustituidos**, más hallazgos **nuevos**, **comunes** y **resueltos**.

### Correspondencias

La correspondencia se establece por identidad demostrada (componente equivalente entre A y B), no por simple coincidencia de categoría. Los componentes sin correspondencia demostrada se muestran como independientes.

### Por qué una desaparición no es una mejora

Que un hallazgo desaparezca en B no implica que la compatibilidad global haya mejorado: puede haberse retirado el componente implicado (relación ya no aplicable), o el cambio puede no estar cubierto por reglas implementadas. Los hallazgos **resueltos** se explican con el cambio concreto (componente retirado, atributo corregido, etc.).

---

## H. Fichas de configuración

Desde el detalle de un equipo, pulsa **Exportar ficha**. Se ofrecen **Markdown (`.md`)** y **Texto (`.txt`)**.

### Contenido

- Nombre, tipo y notas del equipo.
- Composición agrupada por categoría con fabricante/modelo y specs/notas disponibles.
- Resultado global y explicación, reglas evaluadas.
- Hallazgos con regla, resultado, severidad, participantes, atributos comparados, explicación, información que falta y acción recomendada.
- Evidencia y procedencia (metadatos registrados).
- **Relaciones no evaluadas** y **Limitaciones**.
- **Auditoría técnica** con pendientes e inconsistencias.

### Garantías y advertencias

- La ficha se genera desde un **análisis fresco** del estado actual, no de un informe guardado.
- **No** contiene UUID como información principal, estructuras internas ni especificaciones inventadas.
- La evidencia se muestra como **metadatos declarados**; la aplicación no autentica la documentación.
- No se sobrescribe silenciosamente: el diálogo de guardado del sistema pide confirmación.
- No se puede exportar sobre el archivo de inventario activo.

---

## I. Importación, exportación y recuperación

### Copias de seguridad (soportado)

- **Exportar copia** (Inventario): exporta el estado completo (componentes + builds + perfiles) a JSON en el destino elegido.
- **Restaurar copia**: selecciona un JSON, se muestra una **vista previa** (recuentos, esquema, categorías/estados) y, tras confirmar, se crea una **copia preventiva** del estado actual antes de sustituirlo.

### Cuándo hacer backup

- Antes de una restauración (automático: la copia preventiva).
- Antes de ediciones masivas o migraciones manuales.
- Periódicamente, para conservar un punto de recuperación.

### Qué archivos proteger

- `components.json` (inventario + builds + perfiles).
- `settings.json` (preferencia de idioma).
- `catalog.sqlite3` (catálogo).
- `backups\` (copias preventivas).

### Operaciones que NO deben realizarse manualmente

- Editar `components.json` a mano sin seguir `MANTENIMIENTO.md`.
- Editar `catalog.sqlite3` con herramientas externas.
- Copiar/mezclar archivos de datos entre equipos sin verificar esquemas.
- Forzar el cierre de la aplicación durante una escritura (usa el cierre normal).

### Importación de catálogo

Desde **Catálogo** → **Importar catálogo**, se admiten CSV y JSON con el esquema documentado; los duplicados se omiten y se informa el recuento de nuevos/omitidos.

### Importación CSV al inventario

Desde **Inventario** → **Importar CSV**. Formato `category,manufacturer,model,specs,notes`
(orden libre, alias ES/EN); codificaciones UTF-8 (±BOM), UTF-16 y Windows-1252; delimitadores coma, punto y coma y tabulador. La vista previa muestra totales y tabla completa por fila (línea, estado, motivo, duplicado). `preview_add_components` reclasifica sin escribir; la incorporación final usa `add_components` (un solo `_commit`). Las columnas no admitidas se ignoran y se listan; jamás aportan verificación. Plantilla descargable desde **Descargar plantilla CSV** (UTF-8 con BOM).

---

## Ejemplos rápidos

**Añadir 20 referencias y ver el informe.** Catálogo → selecciona 20 entre páginas → Inventario → Añadir desde catálogo → confirmar: el diálogo muestra creados y omitidos con sus nombres.

**Detectar una incompatibilidad.** Equipos → crea un equipo con placa y RAM → completa perfiles con `memory_generation` verificado → Analizar: una contradicción con atributos verificados se muestra como **Incompatible**; si el dato no está verificado, será **Requiere verificación**.

**Corregir y revalidar.** Centro de calidad → cola de revisión → editar atributo pendiente → aportar evidencia → revalidar. Vuelve a analizar para actualizar hallazgos.

**Comparar.** Equipos → Comparar → A y B: revisa sustituciones con correspondencia demostrada y hallazgos resueltos con su explicación.

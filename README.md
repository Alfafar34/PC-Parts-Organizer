# PC Parts Organizer

Aplicación de escritorio (Tkinter) para organizar el inventario de componentes de PC, consultar un catálogo de referencias comerciales, registrar datos técnicos con evidencias y evaluar la compatibilidad de los equipos configurados.

> **Importante.** El motor de compatibilidad **no certifica** la compatibilidad total de un ordenador. Presenta conclusiones acotadas a relaciones específicas y exige atributos verificados; todo lo no evaluado se declara explícitamente (`not_evaluated`, limitaciones). Lee `docs/ARQUITECTURA.md` antes de interpretar resultados.

## Funcionalidades principales

- **Inventario de componentes** con búsqueda, filtros por categoría, ordenación y detalle.
- **Catálogo de referencias comerciales** en SQLite, con búsqueda, paginación, importación/exportación CSV/JSON y alta masiva al inventario.
- **Incorporación múltiple desde catálogo**: selección entre páginas, duplicados detectados y omitidos con informe, y rechazo atómico ante entradas inválidas.
- **Importación CSV al inventario**: vista previa con validación por fila, detección de duplicados, cambio de delimitador/codificación y una única incorporación transaccional (con plantilla descargable).
- **Perfiles técnicos** por componente con atributos tipados, procedencia, confianza, evidencia y estados de verificación.
- **Equipos (builds)** con asignación única de componentes, detalle y eliminación.
- **Motor de compatibilidad determinista** (sin I/O): findings con regla, severidad, participantes, evidencia y explicación; resultado global y relaciones no evaluadas.
- **Auditoría técnica por build**: hallazgos vinculados a atributos concretos, pendientes relevantes/futuros, inconsistencias y conteos.
- **Centro de calidad**: resumen global, cola de revisión y corrección de datos pendientes.
- **Comparador de builds**: componentes añadidos/retirados/sustituidos con correspondencias demostradas y findings nuevos/comunes/resueltos.
- **Fichas de configuración** exportables a Markdown (`.md`) y texto (`.txt`) desde un análisis fresco.
- **Copias de seguridad y restauración** con verificación SHA256 y copia preventiva previa a la restauración.
- **Localización ES/EN** persistente con paridad exacta de claves.

## Tecnologías

- **Python 3.14+** (verificado con CPython 3.14.5) y **Tkinter** (widget estándar, requiere un display; en Windows se incluye con Python).
- **SQLite 3** (módulo estándar `sqlite3`) solo para el catálogo.
- **Sin dependencias externas**: no se requiere `pip install` para ejecutar ni para validar.
  La aplicación y sus tests utilizan únicamente Python estándar y Tkinter.
  Pillow es opcional y solo lo usan determinadas herramientas de validación visual
  de `tools/` (capturas de pantalla); no es necesario instalarlo para ejecutar la aplicación.

## Requisitos

1. Python 3.14 o superior con Tkinter disponible.
2. Permisos de escritura en `%LOCALAPPDATA%\PCPartsOrganizer` (Windows) / `~/.local/share/PCPartsOrganizer` (Linux/macOS vía `XDG_DATA_HOME`/carpeta de datos local del sistema).
3. No se necesita red, ni base de datos externa, ni compilación.

## Preparación y ejecución

```bat
REM desde la raíz del repositorio
python -m pc_parts_organizer
```

No hay instalación ni paso de compilación. El primer arranque crea el directorio de datos y los archivos de estado si no existen.

## Estructura del repositorio

```
pc_parts_organizer/        Paquete de la aplicación
  app.py                   Punto de arranque (run())
  __main__.py              python -m pc_parts_organizer
  models.py                Component, Build y validación de modelos
  service.py               InventoryService (autoridad transaccional)
  storage.py               Persistencia JSON, esquemas, backups, importación/exportación
  catalog_models.py        CatalogEntry y clave de duplicado
  catalog_storage.py       SQLite del catálogo (modo lectura/escritura)
  catalog_service.py       Servicio del catálogo
  catalog_io.py            Importación/exportación CSV/JSON del catálogo
  technical_profiles.py    Perfiles, AttributeSpec, registro de atributos, validación
  compatibility/           Motor puro de compatibilidad + reglas por relación
  data_quality.py          Calidad de datos, estados de atributos, CONSUMERS, cola
  build_audit.py           Auditoría técnica por build
  build_compare.py         Comparador de builds
  build_sheet.py           Fichas Markdown/TXT
  localization.py          Translator y preferencia de idioma
  locales/es.json, en.json Localización completa
  ui/                      Vistas y formularios Tkinter
tests/                     Suite unittest (aislamiento fail-closed en TEMP)
tools/                     Preparadores de validación visual sintéticos
docs/                      Guía de usuario, arquitectura, mantenimiento, inicio rápido
```

## Ubicación de los datos

Los datos se guardan **fuera** del repositorio, en el directorio de datos local del sistema:

- Windows: `%LOCALAPPDATA%\PCPartsOrganizer\`
- Linux/macOS: `~/.local/share/PCPartsOrganizer/`

Archivos:

| Archivo | Contenido |
|---|---|
| `components.json` | Inventario + builds + perfiles técnicos (JSON, `schema_version` 4 al escribir; acepta 1–4 al leer) |
| `settings.json` | Preferencia de idioma (`schema_version` 1) |
| `catalog.sqlite3` | Catálogo de referencias comerciales |
| `backups/` | Copias preventivas previas a restauraciones |

El catálogo y el inventario son **almacenes separados**: el catálogo es una biblioteca de referencia reutilizable; el inventario es tu colección personal. Incorporar desde catálogo **copia** los campos con equivalencia real (categoría, fabricante, modelo, especificaciones, notas) y nunca transfiere procedencia comercial como verificación técnica.

## Documentación

- `docs/GUIA_USUARIO.md` — manual completo, paso a paso.
- `docs/INICIO_RAPIDO.md` — recorrido práctico del primer arranque a la ficha exportada.
- `docs/ARQUITECTURA.md` — capas, contratos, motor de compatibilidad y límites técnicos.
- `docs/MANTENIMIENTO.md` — backup, restauración y diagnóstico.

## Limitaciones importantes

- El motor evalúa relaciones concretas; no garantiza compatibilidad física, eléctrica o de funcionamiento total.
- Las incompatibilidades se declaran solo con **atributos verificados**; sin verificación, el resultado será `requires_verification` o `insufficient_data`, nunca una incompatibilidad confirmada.
- `compatible` en una relación no implica que otras dimensiones no evaluadas (p. ej. carriles PCIe, potencia eléctrica, capacidad térmica) hayan sido comprobadas.
- La aplicación no autentica documentación de fabricantes; los metadatos de evidencia se muestran tal cual se registran.
- La base de datos del catálogo es SQLite de un solo proceso; no se debe editar manualmente con herramientas externas.
- Los datos reales no deben editarse a mano; usa las funciones de la interfaz o los procedimientos documentados en `docs/MANTENIMIENTO.md`.

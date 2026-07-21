# Dan's Beacon — Agente de Monitoreo WAHA (Backend), Etapa 1

## Resumen

Un servicio en Python ("Dan's Beacon") que escucha los eventos webhook de WAHA
provenientes de una cuenta de WhatsApp usada únicamente para monitoreo
entrante (sin mensajes salientes en esta etapa). Vigila los grupos de soporte
de WhatsApp configurados/autodescubiertos, segmenta la actividad por
remitente, usa un LLM (con el servidor MCP de WAHA para contexto adicional)
para determinar cuándo una persona terminó de describir un problema, y genera
un ticket (resumen en español + cualquier archivo adjunto) como archivos
locales. Este documento cubre solo el backend/agente. Un diseño separado
cubrirá el dashboard frontend con marca ("Dan's Beacon", estilo americano,
paleta de colores ocre) que leerá los tickets que produce este backend.

## Objetivos

- Escuchar eventos webhook de WAHA para los grupos de WhatsApp monitoreados.
- Autodescubrir grupos desde WAHA; permitir excluir grupos específicos
  (lista de exclusión).
- Segmentar la conversación por `(grupo, remitente)` para que problemas
  distintos y no relacionados de distintas personas en el mismo grupo no se
  mezclen en un solo ticket.
- Decidir cuándo el mensaje de un remitente está "terminado" (ya describió su
  problema) usando tanto una verificación rápida por LLM en cada mensaje como
  un mecanismo de respaldo por tiempo de inactividad.
- Al completarse, usar el servidor MCP de WAHA para obtener contexto más
  amplio, y luego pedirle al LLM que produzca un resumen de ticket en
  español.
- Escribir el ticket (markdown) junto con cualquier archivo adjunto
  descargado (imágenes, audio, documentos) en una carpeta por hilo dentro de
  `tickets/`.
- Soportar el cambio de proveedor de LLM (Anthropic / OpenAI / Ollama) por
  configuración.
- Nunca enviar mensajes salientes de WhatsApp en esta etapa.

## Fuera de alcance (esta etapa)

- Sin respuestas/confirmaciones salientes de WhatsApp.
- Sin frontend/dashboard (diseño separado).
- Sin integración con sistemas externos de tickets (Jira/Zendesk/etc.) — por
  ahora solo archivos locales.
- Sin soporte multi-tenant/multi-cuenta — una sola cuenta/sesión de WAHA.

## Arquitectura y Componentes

- **Receptor de webhook (FastAPI)** — recibe los eventos webhook de WAHA por
  cada mensaje (texto, imagen, audio, documento).
- **Registro de grupos (SQLite)** — sincronizado periódicamente desde la
  lista de grupos de WAHA (autodescubrimiento); incluye una tabla de
  exclusión para grupos ignorados, administrada mediante un CLI pequeño
  (`python -m monitor groups exclude <group_id>` / `groups list`).
- **Rastreador de hilos (SQLite)** — una fila por `(group_id, sender_id)`:
  mensajes acumulados, marca de tiempo de la última actividad, plazo de
  inactividad, indicador de "ya generó ticket". Deduplica eventos entrantes
  por el ID de mensaje de WAHA.
- **Programador (scheduler)** — ciclo en segundo plano que vigila los plazos
  de los hilos; dispara la evaluación profunda cuando se cumple la ventana de
  inactividad de un remitente.
- **Capa de abstracción del LLM** — interfaz agnóstica al proveedor
  (`generate(prompt) -> texto`). Se implementa primero Anthropic; OpenAI y
  Ollama siguen la misma interfaz. La configuración selecciona el proveedor y
  modelo activos. Todos los prompts (verificación rápida, evaluación
  profunda, resumen de ticket) están escritos para conversaciones en español
  y producen salida en español.
- **Cliente MCP** — se conecta al propio servidor MCP de WAHA para que el
  paso de evaluación profunda pueda obtener contexto adicional (historial
  reciente del grupo, información del remitente, medios) más allá de lo que
  incluyó el payload del webhook.
- **Generador de tickets** — redacta un ticket en markdown en español y
  descarga los archivos adjuntos referenciados en una carpeta por hilo.
- **Configuración** (`config.yaml` / `.env`) — URL base y API key de WAHA, URL
  del servidor MCP, proveedor/modelo/API key activos del LLM, ventana de
  inactividad por defecto (p. ej. 10 min), tiempo de vida máximo de un hilo
  antes de archivarse sin resolver.

## Flujo de Datos

1. WAHA envía (POST) un evento de mensaje al receptor de webhook.
2. El receptor deduplica por ID de mensaje de WAHA, resuelve remitente y
   grupo, y actualiza la fila del hilo (agrega el mensaje, reinicia la última
   actividad, extiende el plazo de inactividad).
3. **Verificación rápida** (llamada económica al LLM, prompt en español):
   "¿esta persona ya terminó de describir su problema?" — si es sí, el hilo
   se marca para evaluación profunda de inmediato, sin esperar el temporizador.
4. **Evaluación profunda** (disparada por un "sí" de la verificación rápida o
   por el vencimiento del temporizador de inactividad): el agente llama al
   cliente MCP para obtener contexto adicional de WAHA, y luego le pide al
   LLM que decida si amerita un ticket, y de ser así, que produzca un resumen
   en español + campos extraídos (descripción del problema, nombre del
   grupo, remitente, marcas de tiempo, adjuntos referenciados).
5. Si amerita ticket: el generador de tickets descarga los adjuntos y
   escribe `tickets/<fecha>_<grupo>_<remitente>_<id>/ticket.md` + adjuntos;
   el hilo se marca como "ya tiene ticket".
6. Si no amerita ticket: el hilo permanece abierto, el plazo se reinicia, y
   espera más mensajes o un tiempo máximo mayor antes de archivarse sin
   ticket.

## Configuración y Descubrimiento de Grupos

- Al iniciar y en un intervalo periódico, el agente llama a la API de WAHA
  para listar los grupos de la cuenta, actualizando el registro de grupos —
  los grupos nuevos se detectan automáticamente, sin necesidad de reiniciar.
- La lista de exclusión se guarda en SQLite y se edita mediante el CLI, para
  silenciar grupos específicos.
- `config.yaml` contiene ajustes de conexión/comportamiento no ligados a un
  grupo específico: URL base/API key de WAHA, URL del servidor MCP,
  proveedor/modelo/API key del LLM, ventana de inactividad por defecto,
  tiempo de vida máximo del hilo.
- El agente es estrictamente de solo lectura respecto a WhatsApp — no envía
  nada.

## Manejo de Errores

- **WAHA/MCP no disponible** durante la evaluación profunda: reintentar con
  backoff; si sigue fallando, degradar de forma controlada decidiendo solo
  con los mensajes ya acumulados en el hilo desde el webhook.
- **Falla del proveedor de LLM**: un reintento, y luego marcar el hilo como
  `needs_review` (visible vía CLI / un archivo indicador donde habría ido la
  carpeta del ticket) en lugar de descartar silenciosamente una queja real.
- **Entregas de webhook duplicadas o fuera de orden**: deduplicadas mediante
  una restricción de unicidad sobre el ID de mensaje de WAHA en SQLite.
- **Caída/reinicio**: seguro por diseño — el estado de los hilos, plazos,
  registro de grupos y exclusiones persisten en SQLite; el programador
  retoma desde el estado persistido.

## Pruebas

- Pruebas unitarias: segmentación de hilos por remitente, cálculo de plazos
  de inactividad, lógica de deduplicación, generación del markdown del
  ticket, interfaz de abstracción del LLM (proveedor simulado).
- Pruebas de integración: conectadas directamente a la instancia de WAHA de
  producción y a grupos de soporte reales (sin servidor WAHA simulado) —
  aceptable aquí porque el agente es estrictamente de solo lectura (no envía
  mensajes salientes), por lo que un error en el peor caso produce un ticket
  incorrecto o ausente, no afecta directamente a los clientes. Las primeras
  ejecuciones deben vigilarse de cerca por posibles hilos mal segmentados o
  decisiones incorrectas del LLM, dado que esto opera sobre conversaciones
  reales en vivo.

## Despliegue

- Empaquetado como imagen/contenedor Docker; el destino real de hosting/
  despliegue se decidirá más adelante. Requiere una URL de webhook accesible
  públicamente para que la instancia remota de WAHA pueda entregar eventos
  (detalle de túnel/hosting, pendiente).

## Pendientes para etapas futuras

- Dashboard frontend (marca "Dan's Beacon", estilo americano, paleta de
  colores ocre, tipografía al estilo Stake/Coca-Cola/Canva) — diseño
  separado.
- Mensajería saliente (confirmaciones a clientes) — no está en alcance
  todavía.
- Integración con sistema externo de tickets — no está en alcance todavía.
- Estrategia de hosting/túnel público para el despliegue en Docker.

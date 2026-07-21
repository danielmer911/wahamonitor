from dataclasses import dataclass

from monitor.threads import ThreadRecord


@dataclass
class TicketDecision:
    ticket_worthy: bool
    summary: str
    problem_description: str


def _format_messages(thread: ThreadRecord) -> str:
    return "\n".join(f"- {m.text}" for m in thread.messages)


def quick_check(llm, thread: ThreadRecord) -> bool:
    prompt = (
        f"Eres un asistente que monitorea un grupo de soporte de WhatsApp.\n"
        f"Remitente: {thread.sender_name}\n"
        f"Mensajes hasta ahora:\n{_format_messages(thread)}\n\n"
        f"¿Esta persona ya terminó de describir su problema? "
        f"Responde únicamente con SI o NO."
    )
    response = llm.generate(prompt).strip().upper()
    return response.startswith("SI")


def deep_evaluate(llm, mcp_context: str, thread: ThreadRecord) -> TicketDecision:
    prompt = (
        f"Eres un asistente que revisa conversaciones de soporte de WhatsApp para "
        f"decidir si se debe generar un ticket.\n"
        f"Remitente: {thread.sender_name}\n"
        f"Mensajes del remitente:\n{_format_messages(thread)}\n\n"
        f"Contexto adicional del grupo:\n{mcp_context}\n\n"
        f"Responde exactamente en este formato:\n"
        f"TICKET: SI o NO\n"
        f"RESUMEN: <resumen breve en español>\n"
        f"PROBLEMA: <descripcion detallada del problema en español>"
    )
    response = llm.generate(prompt)

    fields = {"TICKET": "", "RESUMEN": "", "PROBLEMA": ""}
    lines = response.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        key_found = False

        for key in fields:
            prefix = f"{key}:"
            if line.strip().upper().startswith(prefix):
                # Extract text after the colon on this line
                value_part = line.split(":", 1)[1].strip()
                accumulated_value = [value_part] if value_part else []

                # Look ahead for continuation lines (until next key or end)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if this line starts with any key marker
                    is_key_line = False
                    for k in fields:
                        if next_line.strip().upper().startswith(f"{k}:"):
                            is_key_line = True
                            break

                    if is_key_line:
                        # This is the start of the next field, stop accumulating
                        break
                    else:
                        # This is a continuation line
                        accumulated_value.append(next_line.strip())
                        j += 1

                fields[key] = "\n".join(accumulated_value)
                i = j  # Move to the next unprocessed line
                key_found = True
                break

        if not key_found:
            i += 1

    return TicketDecision(
        ticket_worthy=fields["TICKET"].strip().upper().startswith("SI"),
        summary=fields["RESUMEN"],
        problem_description=fields["PROBLEMA"],
    )

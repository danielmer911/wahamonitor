from monitor.evaluator import TicketDecision, deep_evaluate, quick_check
from monitor.threads import Message, ThreadRecord


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def make_thread() -> ThreadRecord:
    return ThreadRecord(
        group_id="g1",
        sender_id="s1",
        sender_name="Juan",
        messages=[Message("m1", "Mi factura llego mal, adjunto foto", None, "2026-07-21T10:00:00")],
        last_activity_at="2026-07-21T10:00:00",
        deadline_at="2026-07-21T10:10:00",
    )


def test_quick_check_returns_true_on_si():
    llm = FakeLLM("SI")
    assert quick_check(llm, make_thread()) is True
    assert "Juan" in llm.last_prompt


def test_quick_check_returns_false_on_no():
    llm = FakeLLM("NO")
    assert quick_check(llm, make_thread()) is False


def test_deep_evaluate_parses_ticket_worthy_response():
    llm = FakeLLM(
        "TICKET: SI\n"
        "RESUMEN: Cliente reporta factura incorrecta con foto adjunta.\n"
        "PROBLEMA: La factura de julio llego con el monto equivocado."
    )

    decision = deep_evaluate(llm, mcp_context="Sin contexto adicional.", thread=make_thread())

    assert isinstance(decision, TicketDecision)
    assert decision.ticket_worthy is True
    assert decision.summary == "Cliente reporta factura incorrecta con foto adjunta."
    assert decision.problem_description == "La factura de julio llego con el monto equivocado."


def test_deep_evaluate_parses_not_ticket_worthy_response():
    llm = FakeLLM("TICKET: NO\nRESUMEN: \nPROBLEMA: ")

    decision = deep_evaluate(llm, mcp_context="", thread=make_thread())

    assert decision.ticket_worthy is False


def test_deep_evaluate_parses_multiline_problema():
    """Verify that multi-line PROBLEMA values are captured in full, not truncated."""
    llm = FakeLLM(
        "TICKET: SI\n"
        "RESUMEN: Cliente reporta un problema.\n"
        "PROBLEMA: La factura llego con el monto equivocado.\n"
        "Ademas el cliente menciona que ya llamo antes\n"
        "sin recibir respuesta."
    )

    decision = deep_evaluate(llm, mcp_context="Sin contexto adicional.", thread=make_thread())

    assert decision.ticket_worthy is True
    assert decision.summary == "Cliente reporta un problema."
    # Verify both first and continuation lines are present
    assert "monto equivocado" in decision.problem_description
    assert "sin recibir respuesta" in decision.problem_description

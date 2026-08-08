"""Alexa-Skill: Request-Handler und Signaturprüfung (Webservice statt AWS Lambda)."""

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_webservice_support.webservice_handler import WebserviceSkillHandler

from . import agent, config

REPROMPT = "Was möchtest du noch wissen?"


def _get_history(handler_input: HandlerInput) -> list[dict]:
    return handler_input.attributes_manager.session_attributes.get("history", [])


def _set_history(handler_input: HandlerInput, history: list[dict]) -> None:
    handler_input.attributes_manager.session_attributes["history"] = history


class LaunchHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder
            .speak("Hallo! Ich höre zu. Was möchtest du wissen?")
            .ask(REPROMPT)
            .response
        )


class ChatHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("ChatIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        slots = handler_input.request_envelope.request.intent.slots or {}
        frage_slot = slots.get("frage")
        question = (frage_slot.value if frage_slot else None) or ""
        if not question.strip():
            return (
                handler_input.response_builder
                .speak("Das habe ich nicht verstanden. Sag es bitte noch einmal.")
                .ask(REPROMPT)
                .response
            )
        spoken, history = agent.answer(question, _get_history(handler_input))
        _set_history(handler_input, history)
        return handler_input.response_builder.speak(spoken).ask(REPROMPT).response


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder
            .speak("Stell mir einfach eine Frage, zum Beispiel: Was steht in meinen Notizen über den Urlaub?")
            .ask(REPROMPT)
            .response
        )


class StopHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            is_intent_name("AMAZON.StopIntent")(handler_input)
            or is_intent_name("AMAZON.CancelIntent")(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        return handler_input.response_builder.speak("Bis bald!").set_should_end_session(True).response


class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return (
            handler_input.response_builder
            .speak("Das habe ich nicht verstanden. Formuliere es bitte anders.")
            .ask(REPROMPT)
            .response
        )


class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        print(f"Fehler im Skill: {exception!r}")
        return (
            handler_input.response_builder
            .speak("Entschuldigung, da ist etwas schiefgegangen. Versuche es bitte noch einmal.")
            .ask(REPROMPT)
            .response
        )


def _build_skill_builder() -> SkillBuilder:
    sb = SkillBuilder()
    if config.ALEXA_SKILL_ID:
        sb.skill_id = config.ALEXA_SKILL_ID
    for handler in (
        LaunchHandler(),
        ChatHandler(),
        HelpHandler(),
        StopHandler(),
        FallbackHandler(),
        SessionEndedHandler(),
    ):
        sb.add_request_handler(handler)
    sb.add_exception_handler(CatchAllExceptionHandler())
    return sb


def build_webservice_handler() -> WebserviceSkillHandler:
    # verify_signature=True prüft, dass Anfragen wirklich von Amazon kommen —
    # wichtig, weil der Endpoint über den Tunnel öffentlich erreichbar ist.
    return WebserviceSkillHandler(
        skill=_build_skill_builder().create(), verify_signature=True, verify_timestamp=True
    )


def build_relay_handler() -> WebserviceSkillHandler:
    # Für den Relay-Weg (Alexa-hosted Skill als Vermittler) gibt es keine
    # Amazon-Signatur mehr; die Absicherung übernimmt das RELAY_TOKEN in main.py.
    return WebserviceSkillHandler(
        skill=_build_skill_builder().create(), verify_signature=False, verify_timestamp=False
    )

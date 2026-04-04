import json
from datetime import datetime

from ai_handler import AI_HANDLER_REGISTRY


def get_speaking_tagline(make, model):
    today_date = datetime.today().strftime('%B %-d, %Y')  # On Mac and Linux, %#d on windows
    tagline = (f"This has been a Cross report, produced {today_date}.  "
               f"This report was generated using AI from {make} with the model {model}. "
               f"Feedback and questions are welcome at github dot com slash b202i slash cross."
               )
    return tagline


def get_tagline_for_reading(make, model):
    return "crossai.dev:" + json.dumps({"make": make, "model": model})


def get_ai_tag(ai_key: str):
    handler_cls = AI_HANDLER_REGISTRY.get(ai_key)
    make = handler_cls.get_make()
    model = handler_cls.get_model()
    return "crossai.dev:" + json.dumps({"make": make, "model": model})


def get_ai_tag_mini(ai_key: str):
    handler_cls = AI_HANDLER_REGISTRY.get(ai_key)
    make = handler_cls.get_make()
    model = handler_cls.get_model()
    return f"crossai.dev:{make}:{model}"


def get_ai_make_model(ai_key: str):
    handler_cls = AI_HANDLER_REGISTRY.get(ai_key)
    make = handler_cls.get_make()
    model = handler_cls.get_model()
    return f"{make}:{model}"


def get_app_tag():
    return "crossai.dev:"

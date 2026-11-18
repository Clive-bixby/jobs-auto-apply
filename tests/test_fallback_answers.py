"""Smoke test: every question class must resolve to SOME answer (never block)."""

from jobs_auto_apply.answers.fields import enrich_field_for_llm
from jobs_auto_apply.answers.fallback import fallback_answer
from jobs_auto_apply.config import load_config


def _field(label: str, kind: str = "text", options: list | None = None) -> dict:
    f = {"label": label, "kind": kind}
    if options:
        f["options"] = options
    return enrich_field_for_llm(f)


def test_unknown_questions_all_get_answers():
    config = load_config()
    cases = [
        ("Are you willing to relocate?", "radio", None),
        ("Do you have experience with LangChain, LangGraph, MLflow?", "radio", None),
        ("How many years of experience do you have in Bedrock?", "text", None),
        ("In which domain have you managed projects or programs?", "text", None),
        ("Is there any gap in your experiences?", "text", None),
        ("Do you have 4+ years of Node dev exp?", "radio", None),
        ("Why do you want to join us?", "textarea", None),
        ("Please share a link to your GitHub profile", "text", None),
        ("What is your current CTC?", "text", None),
        ("When can you start?", "text", None),
        ("How soon can you join?", "text", None),
        ("Are you comfortable working in a permanent remote setup?", "radio", ["Yes", "No"]),
        ("What is your notice period?", "text", None),
        ("Current employment status?", "radio", ["Employed", "Unemployed", "Fresher"]),
        ("Years of experience with React?", "text", None),
        ("Rate your English proficiency", "radio", ["1", "2", "3", "4", "5"]),
        ("Have you worked with AWS?", "checkbox", None),
        ("What are your salary expectations?", "text", None),
        ("Tell us about yourself", "textarea", None),
        ("Which shift can you work?", "radio", ["Day", "Night"]),
    ]
    missing = []
    for label, kind, options in cases:
        ans = fallback_answer(config, label, _field(label, kind, options))
        if not ans or not str(ans).strip():
            missing.append(label)
    assert not missing, f"no fallback answer for: {missing}"


def test_honest_no_on_experience_bar():
    config = load_config()
    ans = fallback_answer(
        config,
        "Do you have 4+ years of Node dev exp?",
        _field("Do you have 4+ years of Node dev exp?", "radio"),
    )
    assert ans and ans.lower().startswith("n"), ans
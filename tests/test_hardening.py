"""Tests for search ambiguity diagnostics and skill-selection correction logging."""
import asyncio
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.models import SearchResult, Skill, SkillMetadata
from src.tools import SkillsTools


class FakeRegistry:
    def __init__(self, results, skills=None):
        self.results = results
        self.skills = skills or {}

    def search_skills(self, query, limit=20, offset=0):
        return self.results[offset:offset + limit]

    def get_skill(self, skill_id):
        return self.skills.get(skill_id)


def result(skill_id, score, name=None):
    return SearchResult(
        skill_id=skill_id,
        name=name or skill_id,
        description="description",
        category="testing",
        score=score,
    )


def skill(skill_id):
    metadata = SkillMetadata(
        id=skill_id,
        name=skill_id,
        description="description",
    )
    return Skill(metadata=metadata, content=f"Instructions for {skill_id}")


def make_tools(results, log_path, skills=None, threshold=2.0):
    return SkillsTools(
        FakeRegistry(results, skills),
        object(),
        {
            "search_ambiguity_threshold": threshold,
            "correction_log_path": str(log_path),
        },
    )


def test_search_and_contextual_get_skill_annotations_reflect_side_effects(tmp_path):
    tools = make_tools([], tmp_path / "corrections.jsonl")
    annotations = {tool.name: tool.annotations for tool in tools.get_tools()}

    assert annotations["search_skills"].idempotent_hint is False
    assert annotations["get_skill"].read_only_hint is False
    assert annotations["get_skill"].idempotent_hint is False


def search_payload(tools, query="test"):
    response = asyncio.run(tools._search_skills({"query": query}))
    return json.loads(response[0].text)


@pytest.mark.parametrize(
    ("scores", "threshold", "ambiguous", "margin"),
    [
        ([10.0, 10.0], 2.0, True, 0.0),
        ([10.0, 8.1], 2.0, True, 1.9),
        ([10.0, 8.0], 2.0, True, 2.0),
        ([0.4, 0.1], 0.3, True, 0.3),
        ([10.0, 7.996], 2.0, False, 2.0),
        ([10.0, 7.99], 2.0, False, 2.01),
    ],
)
def test_search_flags_score_margin_boundaries(tmp_path, scores, threshold, ambiguous, margin):
    tools = make_tools(
        [result("first", scores[0]), result("second", scores[1])],
        tmp_path / "corrections.jsonl",
        threshold=threshold,
    )

    payload = search_payload(tools)

    assert payload["ambiguous"] is ambiguous
    assert payload["score_margin"] == margin
    assert [candidate["skill_id"] for candidate in payload["top_candidates"]] == ["first", "second"]
    assert [candidate["skill_id"] for candidate in payload["results"]] == ["first", "second"]


@pytest.mark.parametrize(
    "results",
    [
        [result("only", 4.0)],
        [],
        [result("first", None), result("second", 4.0)],
        [result("first", math.nan), result("second", 4.0)],
        [result("first", "invalid"), result("second", 4.0)],
        [result("first", 10 ** 5000), result("second", 4.0)],
    ],
)
def test_search_does_not_flag_missing_or_invalid_scores(tmp_path, results):
    tools = make_tools(results, tmp_path / "corrections.jsonl")

    payload = search_payload(tools)

    assert payload["ambiguous"] is False
    assert payload["score_margin"] is None
    assert payload["top_candidates"] == [
        {"skill_id": candidate.skill_id, "name": candidate.name,
         "score": tools._valid_score(candidate.score)}
        for candidate in results[:2]
    ]


def test_correction_log_records_mismatch_once_and_redacts_secrets(tmp_path):
    log_path = tmp_path / "nested" / "corrections.jsonl"
    skills = {"first": skill("first"), "selected": skill("selected")}
    tools = make_tools(
        [result("first", 9.0, "First Skill"), result("selected", 7.5, "Selected Skill")],
        log_path,
        skills,
    )
    query = "help with auth_token=private123 client_secret=client-secret and Bearer bearer-secret token=url-secret"
    payload = search_payload(tools, query)
    context_id = payload["search_context_id"]

    response = asyncio.run(tools._get_skill({"skill_id": "selected", "search_context_id": context_id}))
    asyncio.run(tools._get_skill({"skill_id": "selected", "search_context_id": context_id}))

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    skill_payload = json.loads(response[0].text)
    assert skill_payload["search_diagnostics"]["ambiguous"] is True
    assert skill_payload["search_diagnostics"]["score_margin"] == 1.5
    event = json.loads(lines[0])
    assert event["event"] == "skill_selection_correction"
    assert event["timestamp"].endswith("Z")
    assert event["query"] == "help with auth_token=[REDACTED] client_secret=[REDACTED] and Bearer [REDACTED] token=[REDACTED]"
    assert event["top_pick"] == {"skill_id": "first", "name": "First Skill", "score": 9.0}
    assert event["actual_pick"] == {"skill_id": "selected", "name": "selected", "score": 7.5}
    assert event["score_margin"] == 1.5
    assert event["search_context_id"] == context_id
    assert all(secret not in lines[0] for secret in ("private123", "client-secret", "bearer-secret", "url-secret"))


def test_no_correction_for_top_skill_or_without_search_context(tmp_path):
    log_path = tmp_path / "corrections.jsonl"
    tools = make_tools(
        [result("first", 5.0), result("second", 4.0)],
        log_path,
        {"first": skill("first"), "second": skill("second")},
    )
    context_id = search_payload(tools)["search_context_id"]

    asyncio.run(tools._get_skill({"skill_id": "first", "search_context_id": context_id}))
    asyncio.run(tools._get_skill({"skill_id": "second"}))

    assert not log_path.exists()


def test_paginated_search_context_keeps_global_top_candidate(tmp_path):
    log_path = tmp_path / "corrections.jsonl"
    tools = make_tools(
        [result("first", 9.0), result("second", 8.0), result("third", 7.0)],
        log_path,
        {"second": skill("second")},
    )
    response = asyncio.run(tools._search_skills({"query": "test", "limit": 1, "offset": 1}))
    search_result = json.loads(response[0].text)

    asyncio.run(tools._get_skill({
        "skill_id": "second",
        "search_context_id": search_result["search_context_id"],
    }))

    event = json.loads(log_path.read_text(encoding="utf-8"))
    assert event["top_pick"]["skill_id"] == "first"
    assert event["actual_pick"]["skill_id"] == "second"


def test_ambiguity_uses_global_top_two_when_result_limit_is_one(tmp_path):
    tools = make_tools(
        [result("first", 9.0), result("second", 8.0), result("third", 1.0)],
        tmp_path / "corrections.jsonl",
    )

    response = asyncio.run(tools._search_skills({"query": "test", "limit": 1}))
    payload = json.loads(response[0].text)

    assert [item["skill_id"] for item in payload["results"]] == ["first"]
    assert [item["skill_id"] for item in payload["top_candidates"]] == ["first", "second"]
    assert payload["ambiguous"] is True
    assert payload["score_margin"] == 1.0


def test_correction_log_handles_missing_scores_and_empty_search(tmp_path):
    log_path = tmp_path / "corrections.jsonl"
    skills = {"second": skill("second")}
    tools = make_tools([result("first", None), result("second", math.nan)], log_path, skills)
    context_id = search_payload(tools)["search_context_id"]

    asyncio.run(tools._get_skill({"skill_id": "second", "search_context_id": context_id}))

    event = json.loads(log_path.read_text(encoding="utf-8"))
    assert event["top_pick"]["score"] is None
    assert event["actual_pick"]["score"] is None
    assert event["score_margin"] is None

    empty_tools = make_tools([], tmp_path / "empty.jsonl", skills)
    empty_context = search_payload(empty_tools)["search_context_id"]
    assert empty_context is None
    asyncio.run(empty_tools._get_skill({"skill_id": "second", "search_context_id": empty_context}))
    assert not (tmp_path / "empty.jsonl").exists()


def test_correction_write_failure_does_not_fail_get_skill(tmp_path, caplog):
    tools = make_tools(
        [result("first", 8.0), result("second", 6.0)],
        tmp_path / "corrections.jsonl",
        {"second": skill("second")},
    )
    context_id = search_payload(tools)["search_context_id"]

    def fail_write(_event):
        raise OSError("sensitive path must not be logged")

    tools._append_correction_event = fail_write
    response = asyncio.run(tools._get_skill({"skill_id": "second", "search_context_id": context_id}))

    assert "Instructions for second" in response[0].text
    assert "Failed to write skill selection correction event" in caplog.text
    assert "sensitive path" not in caplog.text


def test_concurrent_jsonl_appends_are_complete_records(tmp_path):
    log_path = tmp_path / "corrections.jsonl"
    tools = make_tools([], log_path)
    events = [
        {"event": "test", "index": index, "padding": "x" * 500}
        for index in range(100)
    ]

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(tools._append_correction_event, events))

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert sorted(record["index"] for record in records) == list(range(100))

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from jobs_auto_apply.answers.config_answers import total_experience_answer
from jobs_auto_apply.answers.memory_store import resolve_fill_answer
from jobs_auto_apply.config import _compensation_config, _profile_config, _wellfound_filters
from jobs_auto_apply.naukri.questions import _coerce_blob_answer
from jobs_auto_apply.question_groups import classify_question
from jobs_auto_apply.role_filter import (
    filter_skipped_roles,
    should_skip_no_experience_role,
    should_skip_role,
)
from jobs_auto_apply.salary import (
    is_salary_eligible,
    parse_salary_ranges,
    wellfound_salary_floor,
)
from jobs_auto_apply.utils import JobListing


class SalaryFloorTests(unittest.TestCase):
    def test_range_uses_lower_bound(self) -> None:
        ranges = parse_salary_ranges("₹6L – ₹12L")
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].min_inr_lpa, 6.0)

        ok, reason = is_salary_eligible("₹6L – ₹12L", min_inr_lpa=8)
        self.assertFalse(ok)
        self.assertIn("6L", reason)

    def test_range_that_clears_floor_passes(self) -> None:
        ok, _ = is_salary_eligible("₹8L – ₹12L", min_inr_lpa=8)
        self.assertTrue(ok)

    def test_no_salary_allowed_by_default_but_not_when_required(self) -> None:
        self.assertTrue(is_salary_eligible("", min_inr_lpa=8)[0])
        self.assertFalse(is_salary_eligible("", min_inr_lpa=8, require_listed_salary=True)[0])

    def test_naukri_card_salary_is_gated(self) -> None:
        from jobs_auto_apply.salary import is_job_salary_eligible

        self.assertFalse(
            is_job_salary_eligible(meta={"salary": "₹3-6 Lacs PA"}, min_inr_lpa=8)
        )
        self.assertTrue(
            is_job_salary_eligible(meta={"salary": "₹8-12 Lacs PA"}, min_inr_lpa=8)
        )

    def test_wellfound_floor_uses_config_and_never_undercuts_app_floor(self) -> None:
        config = SimpleNamespace(
            application=SimpleNamespace(min_inr_salary_lpa=8),
            wellfound=SimpleNamespace(
                filters=SimpleNamespace(salary_min=800000, salary_currency="INR", include_no_salary=False)
            ),
        )
        self.assertEqual(wellfound_salary_floor(config), (8.0, True))

        config.wellfound.filters.salary_min = 600000
        self.assertEqual(wellfound_salary_floor(config)[0], 8.0)

    def test_hirist_lpa_range_without_currency_symbol(self) -> None:
        ranges = parse_salary_ranges("15-25 LPA")
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].min_inr_lpa, 15.0)
        self.assertEqual(ranges[0].max_inr_lpa, 25.0)

    def test_hirist_lpa_range_below_floor_is_rejected(self) -> None:
        self.assertFalse(is_salary_eligible("6-12 LPA", min_inr_lpa=8)[0])
        self.assertTrue(is_salary_eligible("8-12 LPA", min_inr_lpa=8)[0])

    def test_hirist_single_lpa_value(self) -> None:
        ranges = parse_salary_ranges("12 LPA")
        self.assertEqual([r.min_inr_lpa for r in ranges], [12.0])

    def test_hidden_salary_is_not_parsed_as_a_range(self) -> None:
        self.assertEqual(parse_salary_ranges("Not disclosed"), [])
        self.assertTrue(is_salary_eligible("Not disclosed", min_inr_lpa=8)[0])


class CompanyGateTests(unittest.TestCase):
    def _config(self, path) -> SimpleNamespace:
        return SimpleNamespace(
            application=SimpleNamespace(one_job_per_company=True),
            applied_jobs_path=path,
        )

    def test_one_job_per_company_keeps_first_and_drops_duplicates(self) -> None:
        from jobs_auto_apply.apply_filters import filter_one_per_company

        jobs = [
            JobListing(job_id="1", title="Backend Developer", company="Acme", url="u1", source="hirist"),
            JobListing(job_id="2", title="Frontend Developer", company="acme ", url="u2", source="hirist"),
            JobListing(job_id="3", title="Backend Developer", company="Other", url="u3", source="hirist"),
        ]
        kept = filter_one_per_company(jobs, self._config(Path("missing.json")))
        self.assertEqual([job.job_id for job in kept], ["1", "3"])

    def test_companies_already_applied_to_are_skipped(self) -> None:
        import json
        import tempfile

        from jobs_auto_apply.apply_filters import filter_one_per_company

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "applied_jobs.json"
            path.write_text(
                json.dumps({"applied": [], "history": [{"company": "Acme Corp"}]}),
                encoding="utf-8",
            )
            jobs = [
                JobListing(job_id="1", title="Backend Developer", company="Acme Corp", url="u1", source="hirist"),
                JobListing(job_id="2", title="Backend Developer", company="Other", url="u2", source="hirist"),
            ]
            kept = filter_one_per_company(jobs, self._config(path))
            self.assertEqual([job.job_id for job in kept], ["2"])

    def test_unknown_companies_are_not_collapsed(self) -> None:
        from jobs_auto_apply.apply_filters import filter_one_per_company

        jobs = [
            JobListing(job_id="1", title="Backend Developer", company="", url="u1", source="hirist"),
            JobListing(job_id="2", title="Backend Developer", company="", url="u2", source="hirist"),
        ]
        kept = filter_one_per_company(jobs, self._config(Path("missing.json")))
        self.assertEqual([job.job_id for job in kept], ["1", "2"])


class PendingAnswerCoercionTests(unittest.TestCase):
    def _field(self, label: str) -> dict:
        return {"kind": "short_text", "label": label, "input_type": "short_text"}

    def test_prose_answer_is_not_collapsed_to_a_number(self) -> None:
        from jobs_auto_apply.pending_questions import _coerce_pending_user_answer

        label = "Please describe your experience with Python and Django."
        prose = "1 year building REST APIs with Django/DRF and FastAPI, PostgreSQL and Docker"
        self.assertEqual(
            _coerce_pending_user_answer(label, prose, self._field(label), None),
            prose,
        )

    def test_bare_years_answer_is_still_normalized(self) -> None:
        from jobs_auto_apply.pending_questions import _coerce_pending_user_answer

        label = "How many years of experience do you have?"
        self.assertEqual(
            _coerce_pending_user_answer(label, "2 years", self._field(label), None),
            "2",
        )


class CompensationFallbackTests(unittest.TestCase):
    def test_fallback_defaults_to_off(self) -> None:
        self.assertEqual(_compensation_config({}).current_ctc_fallback_lpa, 0.0)

    def test_fallback_is_read_from_config(self) -> None:
        comp = _compensation_config({"current_ctc_lpa": 0, "current_ctc_fallback_lpa": 9})
        self.assertEqual(comp.current_ctc_lpa, 0.0)
        self.assertEqual(comp.current_ctc_fallback_lpa, 9.0)

    def test_zero_answer_is_detected(self) -> None:
        from jobs_auto_apply.naukri.questions import _answer_is_zero

        for value in ("0", "0.0", "0 L", " 0 "):
            self.assertTrue(_answer_is_zero(value), value)
        for value in ("9", "0.5"):
            self.assertFalse(_answer_is_zero(value), value)


class NaukriFilterParsingTests(unittest.TestCase):
    def test_extra_search_urls_are_parsed(self) -> None:
        from jobs_auto_apply.config import _naukri_filters

        filters = _naukri_filters(
            {
                "keywords": "full stack",
                "search_urls": ["https://www.naukri.com/backend-developer-jobs?experience=2"],
            }
        )
        self.assertEqual(
            filters.search_urls,
            ["https://www.naukri.com/backend-developer-jobs?experience=2"],
        )

    def test_missing_search_urls_is_empty(self) -> None:
        from jobs_auto_apply.config import _naukri_filters

        self.assertEqual(_naukri_filters({}).search_urls, [])

    def test_detail_page_salary_respects_floor(self) -> None:
        # Naukri SRP cards show no salary at all, so the floor is checked against
        # the detail-page snippet instead ("3-4 Lacs P.A." on the job header).
        self.assertFalse(is_salary_eligible("3-4 Lacs P.A.", min_inr_lpa=8)[0])
        self.assertTrue(is_salary_eligible("8-12 Lacs P.A.", min_inr_lpa=8)[0])


class RoleGateTests(unittest.TestCase):
    def test_target_role_passes(self) -> None:
        skip, _ = should_skip_role(
            "Full Stack Developer",
            keywords=["intern", "senior"],
            require_keywords=["Full Stack", "Backend"],
        )
        self.assertFalse(skip)

    def test_non_target_role_is_skipped(self) -> None:
        skip, reason = should_skip_role("SDET", require_keywords=["Full Stack", "Backend"])
        self.assertTrue(skip)
        self.assertIn("not a target role", reason)

    def test_intern_is_skipped_even_when_target_role_matches(self) -> None:
        skip, _ = should_skip_role(
            "Full Stack Developer Intern",
            keywords=["intern"],
            require_keywords=["Full Stack"],
        )
        self.assertTrue(skip)

    def test_senior_target_role_is_skipped(self) -> None:
        skip, _ = should_skip_role(
            "Senior Full Stack Engineer",
            keywords=["senior"],
            require_keywords=["Full Stack"],
        )
        self.assertTrue(skip)

    def test_filter_skipped_roles_applies_positive_gate(self) -> None:
        jobs = [
            JobListing(job_id="1", title="Full Stack Developer", company="A", url="u1", source="naukri"),
            JobListing(job_id="2", title="SDET", company="B", url="u2", source="naukri"),
        ]
        kept = filter_skipped_roles(jobs, require_keywords=["Full Stack", "Backend"])
        self.assertEqual([job.job_id for job in kept], ["1"])

    def test_profile_config_reads_require_role_keywords(self) -> None:
        profile = _profile_config({"require_role_keywords": ["Backend", "Platform"]})
        self.assertEqual(profile.require_role_keywords, ["Backend", "Platform"])


class RoleGateVariantTests(unittest.TestCase):
    """One keyword entry must match every separator spelling portals invent."""

    def test_frontend_spellings_match_one_entry(self) -> None:
        for title in (
            "Frontend Developer",
            "Front-End Developer",
            "Front End Developer",
            "FrontEnd Developer",
            "Associate Front-End Engineer",
        ):
            skip, _ = should_skip_role(title, require_keywords=["Front End"])
            self.assertFalse(skip, title)

    def test_full_stack_spellings_match_one_entry(self) -> None:
        for title in ("Full Stack Developer", "Full-Stack Developer", "FullStack Web Developer"):
            skip, _ = should_skip_role(title, require_keywords=["Full Stack"])
            self.assertFalse(skip, title)

    def test_node_spellings_match_one_entry(self) -> None:
        for title in ("Node.js Developer", "Node Js Developer", "Nodejs Developer", "Node JS Developer"):
            skip, _ = should_skip_role(title, require_keywords=["Node.js Developer"])
            self.assertFalse(skip, title)

    def test_mern_and_sde_families_pass(self) -> None:
        for title in ("MERN Stack Developer", "Mern Developer", "MERN Stack Engineer", "SDE-1"):
            skip, _ = should_skip_role(title, require_keywords=["MERN", "SDE"])
            self.assertFalse(skip, title)

    def test_ai_family_titles_pass(self) -> None:
        require = [
            "AI Engineer",
            "AI Developer",
            "AI/ML",
            "Machine Learning Engineer",
            "GenAI Engineer",
            "MLOps Engineer",
            "Prompt Engineer",
            "Agentic AI",
        ]
        for title in (
            "GenAI Engineer - Agentic Systems",
            "AI Developer - LLM/RAG",
            "AI/ML Implementation Engineer",
            "Machine Learning Engineer - Python",
            "MLOps Engineer - Python",
            "Prompt Engineer - Conversational AI",
        ):
            skip, _ = should_skip_role(title, require_keywords=require)
            self.assertFalse(skip, title)

    def test_short_keyword_does_not_match_inside_a_word(self) -> None:
        skip, _ = should_skip_role("SDET Engineer", require_keywords=["SDE"])
        self.assertTrue(skip)

    def test_off_target_roles_still_skipped(self) -> None:
        for title in (
            "Software Developer - C++",
            "Data Engineer",
            "QA Engineer",
            "Business Analyst",
            "Product Manager",
        ):
            skip, _ = should_skip_role(
                title,
                require_keywords=["Full Stack", "SDE", "AI Engineer"],
            )
            self.assertTrue(skip, title)

    def test_javascript_is_not_java(self) -> None:
        skip, _ = should_skip_no_experience_role(
            "JavaScript Developer",
            no_exp_skills=["java"],
            known_skills=[],
        )
        self.assertFalse(skip)
        skip, _ = should_skip_no_experience_role(
            "Java Full Stack Developer",
            no_exp_skills=["java"],
            known_skills=[],
        )
        self.assertTrue(skip)


class QuestionTests(unittest.TestCase):
    def test_total_experience_question_is_classified_and_answered(self) -> None:
        question = "How many years of experience do you have in total?"
        self.assertEqual(classify_question(question), "total_experience")
        config = SimpleNamespace(profile=SimpleNamespace(years_experience=1))
        self.assertEqual(total_experience_answer(config, question), "1")

    def test_skill_specific_experience_is_not_total_experience(self) -> None:
        self.assertEqual(
            classify_question("How many years of experience do you have in Java?"),
            "skill:java",
        )

    def test_relocation_blob_maps_to_yes(self) -> None:
        field = {"label": "Are you willing to relocate?", "kind": "radio", "options": ["Yes", "No"]}
        self.assertEqual(resolve_fill_answer("Can Relocate All Over India", field), "Yes")
        self.assertEqual(_coerce_blob_answer(field["label"], "Can Relocate All Over India", ["Yes", "No"]), "Yes")


if __name__ == "__main__":
    unittest.main()

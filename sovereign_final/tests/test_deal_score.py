"""Tests for engine/financial.compute_deal_score — the P2 composite grade that
blends financial + location + energy + risk so ranking isn't purely financial."""


from engine.financial import compute_deal_score


def test_no_financial_data_is_unscored():
    score, grade = compute_deal_score({})
    assert (score, grade) == (0, "—")


def test_strong_deal_grades_high():
    score, grade = compute_deal_score({
        "cap_rate": 0.07, "ratio_sro": 1.25, "location_score": 90,
        "energy_class": "A", "lv_status": "PASS",
        "construction_risk": 0, "noise_flag": 0,
    })
    assert score >= 80 and grade == "A"


def test_weak_deal_grades_low():
    score, grade = compute_deal_score({
        "cap_rate": 0.02, "ratio_sro": 0.85, "location_score": 20,
        "energy_class": "F", "lv_status": "PASS",
        "construction_risk": 1, "noise_flag": 1,
    })
    assert score < 50 and grade == "D"


def test_location_optional_rescales():
    """A deal with no location data shouldn't be unfairly sunk — the score is
    rescaled over the components that DO have data."""
    base = {"cap_rate": 0.06, "ratio_sro": 1.15, "energy_class": "B",
            "lv_status": "PASS", "construction_risk": 0, "noise_flag": 0}
    no_loc, _ = compute_deal_score(base)
    with_good_loc, _ = compute_deal_score({**base, "location_score": 85})
    # Both should be respectable; missing location must not force it below C.
    assert no_loc >= 50
    # A strong location should not LOWER the score vs omitting it.
    assert with_good_loc >= no_loc - 5


def test_risk_flags_reduce_score():
    clean = {"cap_rate": 0.05, "ratio_sro": 1.10, "location_score": 70,
             "energy_class": "B", "lv_status": "PASS",
             "construction_risk": 0, "noise_flag": 0}
    risky = {**clean, "construction_risk": 1, "noise_flag": 1}
    assert compute_deal_score(risky)[0] < compute_deal_score(clean)[0]


def test_grade_thresholds_monotonic():
    """Higher composite inputs never produce a lower score."""
    low  = compute_deal_score({"cap_rate": 0.03, "ratio_sro": 0.9,
                               "location_score": 40})[0]
    mid  = compute_deal_score({"cap_rate": 0.05, "ratio_sro": 1.05,
                               "location_score": 60})[0]
    high = compute_deal_score({"cap_rate": 0.07, "ratio_sro": 1.20,
                               "location_score": 85})[0]
    assert low <= mid <= high


class TestConditionComponent:
    """The renovation state parsed from the description (engine wiring of the
    `condition` field) should reward turnkey flats and penalise originals,
    without affecting listings whose condition is unknown."""

    BASE = {"cap_rate": 0.05, "ratio_sro": 1.10, "location_score": 70,
            "energy_class": "B", "lv_status": "PASS",
            "construction_risk": 0, "noise_flag": 0}

    def test_unknown_condition_is_neutral(self):
        # No condition, "unknown", and a garbage value all skip the component,
        # so the score matches the no-condition baseline exactly.
        base_score = compute_deal_score(self.BASE)[0]
        for val in (None, "", "unknown", "n/a"):
            assert compute_deal_score({**self.BASE, "condition": val})[0] == base_score

    def test_new_beats_original(self):
        new = compute_deal_score({**self.BASE, "condition": "new"})[0]
        orig = compute_deal_score({**self.BASE, "condition": "original"})[0]
        assert new > orig

    def test_new_lifts_above_baseline_and_poor_drags_below(self):
        base = compute_deal_score(self.BASE)[0]
        new = compute_deal_score({**self.BASE, "condition": "new"})[0]
        poor = compute_deal_score({**self.BASE, "condition": "poor"})[0]
        assert new >= base >= poor

    def test_condition_is_case_insensitive(self):
        a = compute_deal_score({**self.BASE, "condition": "Renovated"})[0]
        b = compute_deal_score({**self.BASE, "condition": "renovated"})[0]
        assert a == b

    def test_condition_still_bounded(self):
        for val in ("new", "renovated", "good", "original", "poor"):
            score, grade = compute_deal_score({**self.BASE, "condition": val})
            assert 0 <= score <= 100 and grade in {"A", "B", "C", "D"}


def test_score_capped_at_100():
    # Absurdly good inputs still clamp to 0–100 / grade A.
    score, grade = compute_deal_score({
        "cap_rate": 0.50, "ratio_sro": 3.0, "location_score": 100,
        "energy_class": "A0", "lv_status": "PASS",
    })
    assert 0 <= score <= 100 and grade == "A"

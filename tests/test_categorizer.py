"""Auto-categorisation rules."""

from __future__ import annotations

import pytest

from app.services.categorizer import Categorizer


@pytest.fixture
def categorizer() -> Categorizer:
    return Categorizer()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BigBasket order 2450", "Groceries"),
        ("SWIGGY dinner", "Dining"),
        ("Uber to airport", "Transport"),
        ("Netflix subscription", "Entertainment"),
        ("Apollo Pharmacy", "Health"),
        ("Amazon order", "Shopping"),
        ("Jio Fiber broadband bill", "Utilities"),
        ("Monthly rent payment", "Rent"),
        ("Salary credit from Acme", "Salary"),
    ],
)
def test_keywords_map_to_categories(categorizer: Categorizer, text: str, expected: str) -> None:
    assert categorizer.suggest(text) == expected


def test_matching_is_case_insensitive_and_checks_all_inputs(categorizer: Categorizer) -> None:
    assert categorizer.suggest("Payment", "ZOMATO") == "Dining"
    assert categorizer.suggest(None, "uber eats") == "Transport"
    assert categorizer.suggest(None, None) is None
    assert categorizer.suggest("", "") is None


def test_keyword_must_be_a_whole_word(categorizer: Categorizer) -> None:
    """'gaming' must not match the 'game' rule by substring accident."""
    assert categorizer.suggest("gaming console") is None
    assert categorizer.suggest("game night") == "Entertainment"
    assert categorizer.suggest("random merchant xyz") is None


def test_confidence_is_bounded(categorizer: Categorizer) -> None:
    assert categorizer.confidence("Swiggy dinner") > 0
    assert categorizer.confidence("nothing matching here") == 0.0
    assert 0 < categorizer.confidence("Netflix") <= 0.95

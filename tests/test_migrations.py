"""Data migrations from the switch to English (category name and placeholders)."""

import importlib
from decimal import Decimal as D

from django.apps import apps

from finance.models import FeeProfile
from sales.models import ListingTemplate

category_migration = importlib.import_module("finance.migrations.0003_rename_default_category")
placeholder_migration = importlib.import_module("sales.migrations.0004_english_placeholders")


def test_dutch_category_is_renamed_and_back(user):
    profile = FeeProfile.objects.create(user=user, category="Sportkaarten", commission_percentage=D("13"))
    category_migration.forwards(apps, None)
    profile.refresh_from_db()
    assert profile.category == "Sports cards"
    category_migration.backwards(apps, None)
    profile.refresh_from_db()
    assert profile.category == "Sportkaarten"


def test_dutch_placeholders_are_rewritten(user):
    tpl = ListingTemplate.objects.create(
        user=user,
        name="Old",
        title_pattern="{jaar} {set} {speler} #{nummer} {conditie}",
        description_pattern="{opmerkingen}\n{defecten}\n{onbekend}",
    )
    placeholder_migration.forwards(apps, None)
    tpl.refresh_from_db()
    assert tpl.title_pattern == "{year} {set} {player} #{number} {condition}"
    # Unknown placeholders are left alone, so nothing is silently lost.
    assert tpl.description_pattern == "{notes}\n{defects}\n{onbekend}"
    placeholder_migration.backwards(apps, None)
    tpl.refresh_from_db()
    assert tpl.title_pattern == "{jaar} {set} {speler} #{nummer} {conditie}"

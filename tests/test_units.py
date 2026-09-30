"""Unit conversion tests: every supported conversion, both directions where defined."""

from decimal import Decimal

import pytest

from qs_engine.core.errors import IncompatibleUnitsError, UnknownUnitError
from qs_engine.core.units import convert, dimension_of


def test_mm_to_m():
    assert convert(Decimal("1500"), "mm", "m") == Decimal("1.5")


def test_cm_to_m():
    assert convert(Decimal("250"), "cm", "m") == Decimal("2.5")


def test_m_to_mm():
    assert convert(Decimal("2.5"), "m", "mm") == Decimal("2500")


def test_m_to_cm():
    assert convert(Decimal("2.5"), "m", "cm") == Decimal("250")


def test_mm2_to_m2():
    assert convert(Decimal("2000000"), "mm\u00b2", "m\u00b2") == Decimal("2")


def test_m2_to_mm2():
    assert convert(Decimal("2"), "m\u00b2", "mm\u00b2") == Decimal("2000000")


def test_mm3_to_m3():
    assert convert(Decimal("1000000000"), "mm\u00b3", "m\u00b3") == Decimal("1")


def test_m3_to_mm3():
    assert convert(Decimal("1"), "m\u00b3", "mm\u00b3") == Decimal("1000000000")


def test_litre_to_m3():
    assert convert(Decimal("500"), "L", "m\u00b3") == Decimal("0.5")


def test_m3_to_litre():
    assert convert(Decimal("0.5"), "m\u00b3", "L") == Decimal("500")


def test_kg_to_tonne():
    assert convert(Decimal("2500"), "kg", "tonne") == Decimal("2.5")


def test_tonne_to_kg():
    assert convert(Decimal("2.5"), "tonne", "kg") == Decimal("2500")


def test_identity_conversion():
    assert convert(Decimal("3.25"), "m", "m") == Decimal("3.25")
    assert convert(Decimal("7"), "bag", "bag") == Decimal("7")


def test_int_and_str_inputs_accepted():
    assert convert(1000, "mm", "m") == Decimal("1")
    assert convert("100", "cm", "m") == Decimal("1")


def test_float_input_rejected():
    with pytest.raises(TypeError):
        convert(1.5, "m", "mm")


def test_unknown_from_unit():
    with pytest.raises(UnknownUnitError):
        convert(Decimal("1"), "furlong", "m")


def test_unknown_to_unit():
    with pytest.raises(UnknownUnitError):
        convert(Decimal("1"), "m", "furlong")


def test_cross_dimension_rejected():
    with pytest.raises(IncompatibleUnitsError):
        convert(Decimal("1"), "m", "kg")
    with pytest.raises(IncompatibleUnitsError):
        convert(Decimal("1"), "m\u00b2", "m\u00b3")
    with pytest.raises(IncompatibleUnitsError):
        convert(Decimal("1"), "bag", "kg")


def test_undefined_same_dimension_pair_rejected():
    # mm -> cm has no direct entry and must fail closed, not guess.
    with pytest.raises(IncompatibleUnitsError):
        convert(Decimal("10"), "mm", "cm")


def test_dimension_of():
    assert dimension_of("mm") == "length"
    assert dimension_of("m\u00b2") == "area"
    assert dimension_of("L") == "volume"
    assert dimension_of("tonne") == "mass"
    assert dimension_of("bag") == "count"
    assert dimension_of("day") == "time"
    with pytest.raises(UnknownUnitError):
        dimension_of("parsec")

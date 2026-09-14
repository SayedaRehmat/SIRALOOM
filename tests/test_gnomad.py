from pathlib import Path

from backend.app.adapters.population.gnomad import LocalGnomADTabixProvider, _parse_info, _array_value, _array_float
from backend.app.domain.schemas import CanonicalVariant


def test_gnomad_info_array_parsing():
    info = _parse_info("AC=2,5;AF=0.1,0.2;AC_mid=1,3;AN_mid=100;nhomalt_mid=0,1")
    assert _array_value(info["AC"], 1) == 5
    assert _array_float(info["AF"], 1) == 0.2
    assert _array_value(info["AC_mid"], 0) == 1
    assert _array_value(info["nhomalt_mid"], 1) == 1

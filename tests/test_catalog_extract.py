from __future__ import annotations

import zipfile

import pytest

from inegi_defunciones.catalog import Catalog
from inegi_defunciones.extract import _year_from_main, extract_archive
from tests.test_dbf import _make_dbf

DEFUN = [("ENT", "C", 2, 0), ("EDAD", "N", 4, 0)]


def test_catalog_year_resolution():
    cat = Catalog()
    assert cat.available_years[0] == 1990
    assert cat.available_years[-1] == 2024

    picked = cat.archives_for_years([2018, 2019, 2023])
    keys = {a.key for a in picked}
    assert keys == {"2015_2019", "2023"}


def test_catalog_missing_year_raises():
    with pytest.raises(KeyError):
        Catalog().archives_for_years([2019, 2099])


@pytest.mark.parametrize(
    "name,year",
    [("DEFUN23.dbf", 2023), ("DEFUN15.DBF", 2015), ("DEFUN2005.dbf", 2005),
     ("defun94.dbf", 1994), ("CATMINDE.dbf", None), ("CATEMLDE23.dbf", None)],
)
def test_year_from_main(name, year):
    assert _year_from_main(name) == year


def test_extract_flat_archive(tmp_path):
    zpath = tmp_path / "defunciones_base_datos_2023_dbf.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("DEFUN23.dbf", _make_dbf(DEFUN, [("01", 1)]))
        zf.writestr("PAISES.dbf", _make_dbf([("CVE", "C", 3, 0)], [("001",)]))
        zf.writestr("Descripcion.pdf", b"%PDF-1.4 fake")
    arc = extract_archive(zpath, tmp_path / "interim")
    assert arc.years == [2023]
    u = arc.unit(2023)
    assert u.main_dbf.name == "DEFUN23.dbf"
    assert "PAISES" in u.catalogs
    assert [e.name for e in u.extras] == ["Descripcion.pdf"]


def test_extract_bundle_with_year_subdirs(tmp_path):
    zpath = tmp_path / "defunciones_generales_base_datos_2015_2016_dbf.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for yy in ("15", "16"):
            base = f"defunciones_base_datos_20{yy}"
            zf.writestr(f"{base}/DEFUN{yy}.DBF", _make_dbf(DEFUN, [("01", 1)]))
            zf.writestr(f"{base}/CATMINDE.DBF", _make_dbf([("CVE", "C", 4, 0)], [("A000",)]))
    arc = extract_archive(zpath, tmp_path / "interim")
    assert arc.years == [2015, 2016]
    assert arc.unit(2015).main_dbf.name == "DEFUN15.DBF"
    assert "CATMINDE" in arc.unit(2016).catalogs


def test_extract_rejects_path_traversal(tmp_path):
    zpath = tmp_path / "evil_dbf.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../../escape.dbf", b"nope")
    with pytest.raises(RuntimeError):
        extract_archive(zpath, tmp_path / "interim")

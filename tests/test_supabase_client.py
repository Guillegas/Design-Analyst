"""Tests de la capa de I/O: qué se lee como candidata y qué se escribe en
`match_results`. El cliente de Supabase se falsea; no se toca la red."""
import pytest

from app import supabase_client as sb
from app.pipeline.matching import Candidate


class _FakeQuery:
    """Encadena select/in_/eq/insert como el builder de supabase-py y guarda lo
    que se pidió, para poder afirmarlo en el test."""

    def __init__(self, table: str, log: list, rows_by_table: dict):
        self._table = table
        self._log = log
        self._rows_by_table = rows_by_table
        self._filters: list[tuple[str, str, object]] = []

    def select(self, cols):
        self._log.append(("select", self._table, cols))
        return self

    def in_(self, column, values):
        self._filters.append(("in_", column, list(values)))
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def insert(self, rows):
        self._log.append(("insert", self._table, rows))
        return self

    def execute(self):
        for f in self._filters:
            self._log.append((f[0], self._table, f[1], f[2]))
        return _FakeResult(self._rows_by_table.get(self._table, []))


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self, rows_by_table=None):
        self.log: list = []
        self._rows_by_table = rows_by_table or {}

    def table(self, name):
        return _FakeQuery(name, self.log, self._rows_by_table)


def _inks_rows(*ids):
    return [{"id": i, "lab_reference": {"l": 50, "a": 0, "b": 0}} for i in ids]


def _mix_rows(*ids):
    return [{"id": i, "result_lab": {"l": 40, "a": 10, "b": 5}} for i in ids]


def test_my_inks_mixes_join_the_candidates():
    client = _FakeClient({
        "inks": _inks_rows("ink-1"),
        "user_ink_mixes": _mix_rows("mix-1"),
    })
    job = {
        "analysis_source": "my_inks",
        "selected_ink_ids": ["ink-1"],
        "selected_mix_ids": ["mix-1"],
    }

    cands = sb.fetch_eligible_inks(client, job)

    assert {c.id for c in cands} == {"ink-1", "mix-1"}
    mix = next(c for c in cands if c.id == "mix-1")
    assert mix.is_user_mix is True
    assert mix.lab == (40, 10, 5)  # result_lab tal cual, sin recalcular


def test_my_inks_without_mixes_still_works():
    client = _FakeClient({"inks": _inks_rows("ink-1")})
    job = {
        "analysis_source": "my_inks",
        "selected_ink_ids": ["ink-1"],
        "selected_mix_ids": None,
    }

    cands = sb.fetch_eligible_inks(client, job)

    assert [c.id for c in cands] == ["ink-1"]
    assert not any(e[1] == "user_ink_mixes" for e in client.log)


def test_my_inks_with_only_mixes_works():
    client = _FakeClient({"user_ink_mixes": _mix_rows("mix-1")})
    job = {
        "analysis_source": "my_inks",
        "selected_ink_ids": [],
        "selected_mix_ids": ["mix-1"],
    }

    cands = sb.fetch_eligible_inks(client, job)

    assert [c.id for c in cands] == ["mix-1"]


def test_my_inks_with_nothing_selected_is_empty():
    client = _FakeClient()
    job = {"analysis_source": "my_inks", "selected_ink_ids": [], "selected_mix_ids": []}

    assert sb.fetch_eligible_inks(client, job) == []


def test_brands_mode_never_reads_mixes():
    """Las mezclas propias son solo de `my_inks`: en modo marcas no aplican."""
    client = _FakeClient({"inks": _inks_rows("ink-1")})
    job = {
        "analysis_source": "brands",
        "selected_brand_ids": ["b-1"],
        "selected_mix_ids": ["mix-1"],
    }

    cands = sb.fetch_eligible_inks(client, job)

    assert [c.id for c in cands] == ["ink-1"]
    assert not any(e[1] == "user_ink_mixes" for e in client.log)


def test_unknown_source_raises():
    with pytest.raises(ValueError):
        sb.fetch_eligible_inks(_FakeClient(), {"analysis_source": "otra_cosa"})


def test_a_mix_is_written_as_user_mix():
    client = _FakeClient()

    sb.insert_match_candidates(client, "job-1", "ec-1", [
        Candidate(ink_id="mix-1", delta_e=1.5, rank=1, is_user_mix=True),
        Candidate(ink_id="ink-1", delta_e=3.0, rank=2),
    ])

    rows = next(e[2] for e in client.log if e[0] == "insert")
    mix_row, ink_row = rows
    # El CHECK de coherencia exige exactamente una columna rellena por tipo.
    assert mix_row["match_type"] == "user_mix"
    assert mix_row["user_ink_mix_id"] == "mix-1"
    assert mix_row["ink_id"] is None
    assert mix_row["ink_mix_id"] is None
    assert ink_row["match_type"] == "direct_ink"
    assert ink_row["ink_id"] == "ink-1"
    assert ink_row["user_ink_mix_id"] is None

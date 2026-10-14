import pandas as pd

from app.validators.join_validator import JoinValidator
from app.validators.schema_validator import SchemaValidator


def test_schema_validator_passes_when_columns_exist_and_values_are_coercible():
    df = pd.DataFrame(
        {
            "amount": ["10", "20", "30"],
            "posted_at": ["2026-04-01", "2026-04-02", "2026-04-03"],
        }
    )
    config = {
        "schema_def": [
            {"name": "amount", "dtype": "int"},
            {"name": "posted_at", "dtype": "datetime"},
        ]
    }

    result = SchemaValidator().run(df, config)

    assert result.check_name == "schema"
    assert result.status == "pass"


def test_schema_validator_fails_on_missing_required_columns():
    df = pd.DataFrame({"amount": ["10", "20"]})
    config = {
        "schema_def": [
            {"name": "amount", "dtype": "int"},
            {"name": "posted_at", "dtype": "datetime"},
        ]
    }

    result = SchemaValidator().run(df, config)

    assert result.status == "fail"
    assert result.details["missing_columns"] == ["posted_at"]


def test_join_validator_skips_non_reconcile_datasets():
    df = pd.DataFrame({"Org Name": ["Org A", "Org B"]})

    result = JoinValidator().run(df, {"process_type": "FR"})

    assert result.status == "skipped"


def test_join_validator_fails_on_duplicate_join_key():
    df = pd.DataFrame({"Org Name": ["Org A", "Org A", "Org B"]})

    result = JoinValidator().run(df, {"validation_cfg": {"join_key": "Org Name"}})

    assert result.status == "fail"
    assert result.details["duplicate_count"] == 1


def test_join_validator_fails_when_join_key_missing_from_dataset():
    df = pd.DataFrame({"Amount": [100, 200]})

    result = JoinValidator().run(df, {"validation_cfg": {"join_key": "Org Name"}})

    assert result.status == "fail"
    assert "Org Name" in result.message


def test_join_validator_passes_when_key_unique_and_non_null():
    df = pd.DataFrame({"Org Name": ["Org A", "Org B", "Org C"]})

    result = JoinValidator().run(df, {"validation_cfg": {"join_key": "Org Name"}})

    assert result.status == "pass"
    assert result.details["row_count"] == 3

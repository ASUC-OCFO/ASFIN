from app.admin.datasets import bootstrap_datasets


def test_bootstrap_datasets_creates_ficomm_and_absa(db):
    datasets = bootstrap_datasets(db)

    assert [(dataset.name, dataset.process_type) for dataset in datasets] == [
        ("FICOMM", "FICOMM"),
        ("ABSA", "ABSA"),
    ]


def test_bootstrap_datasets_is_idempotent(db):
    first = bootstrap_datasets(db)
    second = bootstrap_datasets(db)

    assert [dataset.id for dataset in second] == [dataset.id for dataset in first]

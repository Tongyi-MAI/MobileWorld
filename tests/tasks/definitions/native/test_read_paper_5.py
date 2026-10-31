from types import SimpleNamespace

import pytest

from mobile_world.tasks.definitions.native.read_paper_5 import ReadQwen3PaperTask5


def _score(answer):
    task = ReadQwen3PaperTask5()
    task.initialized = True
    return task.is_successful(SimpleNamespace(interaction_cache=answer))[0]


@pytest.mark.parametrize(
    "answer",
    [
        "vie Latn,khm Khmr",
        "vie Latn, khm Khmr",
        "  vie Latn , khm Khmr  ",
        "khm Khmr, vie Latn",
        "Vie Latn, Khm Khmr",
        "vie_Latn, khm_Khmr",
    ],
)
def test_read_paper_5_accepts_equivalent_answers(answer):
    assert _score(answer) == 1.0


@pytest.mark.parametrize(
    "answer",
    ["vie Latn", "vie Latn, khm Khmr, tha Thai", "vie Latn khm Khmr", ""],
)
def test_read_paper_5_rejects_wrong_answers(answer):
    assert _score(answer) == 0.0

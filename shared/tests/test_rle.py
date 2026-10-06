import numpy as np

from shared.rle import decode, encode


def test_rle_roundtrip_random():
    rng = np.random.default_rng(0)
    for _ in range(20):
        m = rng.random((37, 53)) > 0.7
        assert np.array_equal(decode(encode(m), 37, 53), m)


def test_rle_edge_cases():
    assert encode(np.zeros((2, 2), bool)) == [4]
    assert encode(np.ones((2, 2), bool)) == [0, 4]
    assert decode([0, 4], 2, 2).all()
    assert not decode([4], 2, 2).any()

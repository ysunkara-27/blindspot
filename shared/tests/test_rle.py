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


def test_read_zones_gz_fallback(tmp_path):
    import gzip
    import json

    import numpy as np

    from shared.rle import read_zones, write_zones

    z = {"lungs": np.ones((4, 4), bool), "right_apex": np.zeros((4, 4), bool)}
    p = tmp_path / "zones" / "c1.json"
    write_zones(p, "c1", z, approximate=False, midline_x=2.0)
    raw = p.read_bytes()
    with gzip.open(p.with_name("c1.json.gz"), "wb") as fh:
        fh.write(raw)
    p.unlink()
    masks, meta = read_zones(p)  # plain path missing → .gz sibling
    assert masks["lungs"].all() and meta["midline_x"] == 2.0
    assert json.loads(raw)["case_id"] == "c1"

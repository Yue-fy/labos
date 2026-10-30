from fastapi.testclient import TestClient

from labos.central import create_app


def test_immutable_versions_hide_superseded_and_unreviewed_documents(tmp_path):
    from labos.evidence import EvidenceDocument, EvidenceStore
    library = EvidenceStore(tmp_path)
    first = EvidenceDocument(title="Optical test", source="file:///lab/test.py", category="code",
                             content="set_exposure(100); acquire_spectrum()", reviewed=True)
    a = library.add(first)
    assert library.add(first)["id"] == a["id"]
    assert library.search("set_exposure")[0]["sha256"] == a["sha256"]
    second = library.add(first.model_copy(update={"content": "set_exposure(10)", "reviewed": False}))
    assert second["version"] == 2
    assert library.search("set_exposure") == []
    assert library.search("set_exposure", reviewed_only=False)[0]["id"] == second["id"]


def test_retrieval_supports_chinese_and_returns_bounded_cited_excerpts(tmp_path):
    from labos.evidence import EvidenceDocument, EvidenceStore
    library = EvidenceStore(tmp_path)
    library.add(EvidenceDocument(title="偏振光谱", source="lab:polarization", category="protocol",
                                 content="准备暗场，偏振光谱测量应检查曝光和饱和。" * 300,
                                 tags=["光谱"], reviewed=True))
    hits = library.search("光谱曝光")
    assert len(hits) == 1
    assert len(hits[0]["excerpt"]) <= 1200
    assert len(hits[0]["sha256"]) == 64
    assert hits[0]["source"] == "lab:polarization"
    assert "content" not in hits[0]


def test_evidence_is_operator_only_and_never_executes_code(central_config, tmp_path):
    target = tmp_path / "should-not-exist"
    doc = {"title": "Prior test", "source": "test:untrusted", "category": "code",
           "content": f"open({str(target)!r}, 'w').write('unsafe')", "reviewed": True}
    with TestClient(create_app(central_config)) as client:
        agent_auth = {"Authorization": "Bearer " + "A" * 40}
        operator_auth = {"Authorization": "Bearer " + "O" * 40}
        assert client.post("/api/evidence", json=doc, headers=agent_auth).status_code == 403
        assert client.post("/api/evidence", json=doc, headers=operator_auth).status_code == 200
        assert client.get("/api/evidence?q=unsafe", headers=agent_auth).status_code == 403
        hits = client.get("/api/evidence?q=unsafe", headers=operator_auth).json()
        assert hits[0]["category"] == "code"
        assert not target.exists()
        assert client.get("/api/status", headers=operator_auth).json()["runs"] == []

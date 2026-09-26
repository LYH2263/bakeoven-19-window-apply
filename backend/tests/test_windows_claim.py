"""可开工建议带入创建的验收测试：

- 建议本身不单独占炉（只读）
- 提交时按当时库里的占炉重新计算
- 仍空着：创建成功，甘特两段端点与建议的发酵止/烘烤止一致，批次列表对得上新批次号
- 已被占上：409 不创建，甘特不新增，响应写明对手批次与重叠阶段
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import Oven, Product


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_local()
    db.add_all(
        [
            Product(name="测试欧包", ferment_min=40, bake_min=20),
            Oven(label="1号炉", capacity_note=""),
            Oven(label="2号炉", capacity_note=""),
        ]
    )
    db.commit()
    product_id = db.query(Product).first().id
    db.close()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_db():
        s = session_local()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        c.product_id = product_id
        yield c


def _windows(client):
    r = client.get(f"/api/windows?product_id={client.product_id}")
    assert r.status_code == 200
    return r.json()


def test_suggestion_does_not_occupy_oven(client):
    wins = _windows(client)
    assert len(wins) == 2  # 两台炉各一条建议
    for w in wins:
        assert w["ferment_end"] == w["start_min"] + 40
        assert w["bake_end"] == w["ferment_end"] + 20
        assert w["bake_end"] == w["end_min"]
    # 建议只是试算：不落批次、不占炉、甘特无色块
    assert client.get("/api/batches").json() == []
    assert client.get("/api/gantt").json() == []


def test_claim_free_window_creates_batch_matching_suggestion(client):
    w = _windows(client)[0]
    r = client.post(
        "/api/batches",
        json={"product_id": client.product_id, "oven_id": w["oven_id"], "start_min": w["start_min"]},
    )
    assert r.status_code == 200
    code = r.json()["code"]

    # 甘特两段端点 == 建议里的发酵止、烘烤止
    blocks = [b for b in client.get("/api/gantt").json() if b["code"] == code]
    assert len(blocks) == 2
    ferment = next(b for b in blocks if b["phase"] == "ferment")
    bake = next(b for b in blocks if b["phase"] == "bake")
    assert (ferment["start_min"], ferment["end_min"]) == (w["start_min"], w["ferment_end"])
    assert (bake["start_min"], bake["end_min"]) == (w["ferment_end"], w["bake_end"])

    # 批次列表能对上新批次号
    codes = [b["code"] for b in client.get("/api/batches").json()]
    assert code in codes


def test_claim_after_slot_taken_conflicts_without_creating(client):
    # 打开可开工页：两炉各看到一条建议
    wins = {w["oven_id"]: w for w in _windows(client)}
    assert len(wins) == 2
    oven_taken, oven_free = sorted(wins)

    # 另一人先把 oven_taken 的那段占上（同产品同开工分钟）
    rival = client.post(
        "/api/batches",
        json={
            "product_id": client.product_id,
            "oven_id": oven_taken,
            "start_min": wins[oven_taken]["start_min"],
            "code": "BO-RIVAL",
        },
    )
    assert rival.status_code == 200

    # 按打开页面时看到的空档提交 → 按当时库里的占炉重算，409 不创建
    r = client.post(
        "/api/batches",
        json={
            "product_id": client.product_id,
            "oven_id": oven_taken,
            "start_min": wins[oven_taken]["start_min"],
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["opponent_code"] == "BO-RIVAL"
    assert detail["phase"] in ("ferment", "bake")
    assert detail["phase_label"] in ("发酵", "烘烤")
    assert "BO-RIVAL" in detail["message"]

    # 甘特不新增色块、批次不新增
    assert len(client.get("/api/batches").json()) == 1
    assert len(client.get("/api/gantt").json()) == 2

    # 仍空着的另一条建议照常创建成功
    w = wins[oven_free]
    ok = client.post(
        "/api/batches",
        json={"product_id": client.product_id, "oven_id": oven_free, "start_min": w["start_min"]},
    )
    assert ok.status_code == 200
    blocks = [b for b in client.get("/api/gantt").json() if b["code"] == ok.json()["code"]]
    assert {b["phase"] for b in blocks} == {"ferment", "bake"}

"""可开工建议 → 带入创建 的全流程测试。

覆盖需求：
- 建议本身不单独占炉（查 /windows 不产生任何批次或占炉）。
- 提交时按当时库里的占炉重算，不沿用页面打开时看到的空档。
- 空档仍在：创建成功，甘特两段端点与建议的发酵止/烘烤止一致，批次列表能查到新批次号。
- 空档已被占：不创建、甘特不新增色块，409 明细写明对手批次号与重叠阶段。
"""

import os
import tempfile

_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models.models import Batch, ConflictLog, Oven, Product


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_occupancy(client):
    """每个用例前清掉批次与冲突日志，只留配方/炉位种子数据。"""
    db = SessionLocal()
    try:
        db.execute(delete(ConflictLog))
        db.execute(delete(Batch))
        db.commit()
    finally:
        db.close()
    yield


def _ids(client):
    products = client.get("/api/products").json()
    ovens = client.get("/api/ovens").json()
    return products, ovens


def test_suggestion_itself_does_not_occupy(client):
    products, _ = _ids(client)
    pid = products[0]["id"]
    before_batches = client.get("/api/batches").json()
    before_gantt = client.get("/api/gantt").json()

    suggestions = client.get(f"/api/windows?product_id={pid}").json()
    assert suggestions, "空库应当给出建议"

    after_batches = client.get("/api/batches").json()
    after_gantt = client.get("/api/gantt").json()
    assert after_batches == before_batches
    assert after_gantt == before_gantt


def test_create_from_free_suggestion_matches_gantt(client):
    products, ovens = _ids(client)
    product = products[0]  # 乡村欧包：发酵 40 + 烘烤 35
    pid = product["id"]

    suggestions = client.get(f"/api/windows?product_id={pid}").json()
    sug = suggestions[0]
    assert sug["ferment_end"] == sug["start_min"] + product["ferment_min"]
    assert sug["bake_end"] == sug["ferment_end"] + product["bake_min"]

    created = client.post(
        "/api/batches",
        json={
            "product_id": pid,
            "oven_id": sug["oven_id"],
            "start_min": sug["start_min"],
        },
    )
    assert created.status_code == 200, created.text
    batch = created.json()
    assert batch["code"]

    # 甘特两段端点 == 建议里的发酵止、烘烤止
    blocks = [
        b for b in client.get("/api/gantt").json() if b["batch_id"] == batch["id"]
    ]
    assert len(blocks) == 2
    by_phase = {b["phase"]: b for b in blocks}
    assert by_phase["ferment"]["start_min"] == sug["start_min"]
    assert by_phase["ferment"]["end_min"] == sug["ferment_end"]
    assert by_phase["bake"]["start_min"] == sug["ferment_end"]
    assert by_phase["bake"]["end_min"] == sug["bake_end"]

    # 批次列表能按批次号对上新批次
    codes = [b["code"] for b in client.get("/api/batches").json()]
    assert batch["code"] in codes

    # 建议按当时库里占炉重算：同一炉的下一条建议应让开新批次
    refreshed = client.get(f"/api/windows?product_id={pid}").json()
    same_oven = [w for w in refreshed if w["oven_id"] == sug["oven_id"]]
    assert same_oven and same_oven[0]["start_min"] >= sug["bake_end"]


def test_create_from_stale_suggestion_conflict(client):
    products, ovens = _ids(client)
    bread = products[0]  # 40 + 35
    croissant = products[1]  # 25 + 20

    suggestions = client.get(f"/api/windows?product_id={bread['id']}").json()
    sug = suggestions[0]

    # 另一批次抢先占上这段（模拟页面打开后库里的占炉变化）
    rival = client.post(
        "/api/batches",
        json={
            "product_id": croissant["id"],
            "oven_id": sug["oven_id"],
            "start_min": sug["start_min"],
        },
    )
    assert rival.status_code == 200, rival.text
    rival_code = rival.json()["code"]

    gantt_before = client.get("/api/gantt").json()
    batches_before = client.get("/api/batches").json()

    # 按打开页面时的旧建议提交：必须按现在库里的占炉重算并拒绝
    stale = client.post(
        "/api/batches",
        json={
            "product_id": bread["id"],
            "oven_id": sug["oven_id"],
            "start_min": sug["start_min"],
        },
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert rival_code in detail
    assert "发酵段" in detail or "烘烤段" in detail

    # 不创建、甘特不新增色块
    assert client.get("/api/gantt").json() == gantt_before
    assert client.get("/api/batches").json() == batches_before

    # 冲突台账记下对手批次与重叠阶段
    logs = client.get("/api/conflicts").json()
    assert logs and rival_code in logs[0]["detail"]


def test_duplicate_explicit_code_rejected(client):
    products, ovens = _ids(client)
    payload = {
        "product_id": products[0]["id"],
        "oven_id": ovens[0]["id"],
        "start_min": 8 * 60,
        "code": "BO-固定号",
    }
    assert client.post("/api/batches", json=payload).status_code == 200
    again = client.post("/api/batches", json=payload)
    assert again.status_code == 409
    assert "BO-固定号" in again.json()["detail"]

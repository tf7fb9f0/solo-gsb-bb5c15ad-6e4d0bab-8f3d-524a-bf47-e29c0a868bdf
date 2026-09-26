"""API 集成测试（需要安装 fastapi / httpx，使用临时数据库文件）。

运行方式：python3 -m pytest tests/test_api.py
"""

import os
import tempfile

# 须在导入 app 之前设置数据库路径，避免污染本地数据
_tmpdir = tempfile.mkdtemp(prefix="phase-api-test-")
os.environ["DATABASE_PATH"] = os.path.join(_tmpdir, "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

# 显式建表，兼容未通过 with 上下文触发 lifespan 的 TestClient 用法
db.init_db()
client = TestClient(app)

VALID_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A", "B", "C"]},
        {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"]},
        {"id": "D3", "power": 30, "allowed_phases": ["A", "B", "C"]},
    ],
}


def test_create_calculation_feasible():
    resp = client.post("/api/v1/calculations", json=VALID_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["feasible"] is True
    assert body["imbalance"] == 20
    assert body["loads"] == {"A": 10, "B": 20, "C": 30}
    assert body["assignments"] == [
        {"device_id": "D1", "phase": "A"},
        {"device_id": "D2", "phase": "B"},
        {"device_id": "D3", "phase": "C"},
    ]
    assert body["id"] >= 1


def test_create_calculation_infeasible():
    payload = {
        "capacities": {"A": 5, "B": 0, "C": 0},
        "devices": [{"id": "BIG", "power": 50, "allowed_phases": ["A", "B", "C"]}],
    }
    resp = client.post("/api/v1/calculations", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["feasible"] is False
    assert body["imbalance"] is None
    assert body["loads"] is None
    assert body["assignments"] == []
    assert "无可行" in body["message"]


def test_list_and_get_detail():
    created = client.post("/api/v1/calculations", json=VALID_PAYLOAD).json()
    calc_id = created["id"]

    listing = client.get("/api/v1/calculations").json()
    assert any(item["id"] == calc_id for item in listing)

    detail = client.get(f"/api/v1/calculations/{calc_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["feasible"] is True
    assert body["loads"] == {"A": 10, "B": 20, "C": 30}
    assert {d["device_id"] for d in body["devices"]} == {"D1", "D2", "D3"}
    for device in body["devices"]:
        assert device["assigned_phase"] in ("A", "B", "C")


def test_get_not_found():
    resp = client.get("/api/v1/calculations/999999")
    assert resp.status_code == 404


def test_validation_duplicate_ids():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "power": 5, "allowed_phases": ["A"]},
            {"id": "D1", "power": 5, "allowed_phases": ["B"]},
        ],
    }
    assert client.post("/api/v1/calculations", json=payload).status_code == 422


def test_validation_too_many_devices():
    payload = {
        "capacities": {"A": 1000, "B": 1000, "C": 1000},
        "devices": [
            {"id": f"D{i}", "power": 1, "allowed_phases": ["A"]} for i in range(13)
        ],
    }
    assert client.post("/api/v1/calculations", json=payload).status_code == 422


def test_validation_empty_allowed_phases():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [{"id": "D1", "power": 5, "allowed_phases": []}],
    }
    assert client.post("/api/v1/calculations", json=payload).status_code == 422


def test_validation_non_positive_power():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [{"id": "D1", "power": 0, "allowed_phases": ["A"]}],
    }
    assert client.post("/api/v1/calculations", json=payload).status_code == 422


def test_validation_invalid_phase():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [{"id": "D1", "power": 5, "allowed_phases": ["D"]}],
    }
    assert client.post("/api/v1/calculations", json=payload).status_code == 422


def test_allowed_phases_deduplicated():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [{"id": "D1", "power": 5, "allowed_phases": ["C", "A", "C"]}],
    }
    resp = client.post("/api/v1/calculations", json=payload)
    assert resp.status_code == 201
    detail = client.get(f"/api/v1/calculations/{resp.json()['id']}").json()
    assert detail["devices"][0]["allowed_phases"] == ["A", "C"]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


INFEASIBLE_UPGRADE_PAYLOAD = {
    "capacities": {"A": 5, "B": 0, "C": 0},
    "devices": [
        {"id": "BIG", "power": 50, "allowed_phases": ["A", "B", "C"]},
        {"id": "FIX", "power": 7, "allowed_phases": ["A"]},
    ],
}


def _create(payload):
    return client.post("/api/v1/calculations", json=payload).json()


def test_capacity_upgrade_success():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is False

    resp = client.post(f"/api/v1/calculations/{calc_id}/capacity-upgrade")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["original_capacities"] == {"A": 5, "B": 0, "C": 0}
    # FIX 只能接 A：A 相负载至少 7；BIG(50) 若也放 A 则扩容 52，
    # 总量最小为 BIG 放 B：扩 B 50，A 不扩（FIX=7 > 原容量 5 -> 还需扩 A 2）
    assert body["capacity_upgrades"] == {"A": 2, "B": 50, "C": 0}
    assert body["total_upgrade"] == 52
    assert body["max_upgrade"] == 50
    assert body["suggested_capacities"] == {"A": 7, "B": 50, "C": 0}
    assert body["loads"] == {"A": 7, "B": 50, "C": 0}
    assignments = {a["device_id"]: a["phase"] for a in body["assignments"]}
    assert assignments == {"BIG": "B", "FIX": "A"}
    # 分配按设备编号排序
    assert [a["device_id"] for a in body["assignments"]] == ["BIG", "FIX"]
    assert "扩容" in body["message"]


def test_capacity_upgrade_404():
    resp = client.post("/api/v1/calculations/999999/capacity-upgrade")
    assert resp.status_code == 404


def test_capacity_upgrade_409_when_feasible():
    created = _create(VALID_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True
    resp = client.post(f"/api/v1/calculations/{calc_id}/capacity-upgrade")
    assert resp.status_code == 409


def test_capacity_upgrade_does_not_modify_record():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    calc_id = created["id"]
    client.post(f"/api/v1/calculations/{calc_id}/capacity-upgrade")

    detail = client.get(f"/api/v1/calculations/{calc_id}").json()
    # 原记录仍为无可行分配，容量/负载/分配均不变
    assert detail["feasible"] is False
    assert detail["capacities"] == {"A": 5, "B": 0, "C": 0}
    assert detail["loads"] is None
    assert detail["imbalance"] is None
    assert detail["assignments"] == []
    for device in detail["devices"]:
        assert device["assigned_phase"] is None

    # 再调一次结果确定且相同（幂等读操作）
    again = client.post(f"/api/v1/calculations/{calc_id}/capacity-upgrade").json()
    assert again["capacity_upgrades"] == {"A": 2, "B": 50, "C": 0}


def test_capacity_upgrade_single_forced_phase():
    payload = {
        "capacities": {"A": 100, "B": 0, "C": 0},
        "devices": [
            {"id": "X1", "power": 50, "allowed_phases": ["A"]},
            {"id": "X2", "power": 60, "allowed_phases": ["A"]},
        ],
    }
    created = _create(payload)
    assert created["feasible"] is False
    body = client.post(
        f"/api/v1/calculations/{created['id']}/capacity-upgrade"
    ).json()
    assert body["capacity_upgrades"] == {"A": 10, "B": 0, "C": 0}
    assert body["suggested_capacities"] == {"A": 110, "B": 0, "C": 0}
    assert body["loads"] == {"A": 110, "B": 0, "C": 0}
    assert body["total_upgrade"] == 10
    assert body["max_upgrade"] == 10


ROBUST_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "min_power": 5, "max_power": 10, "allowed_phases": ["A", "B", "C"]},
        {"id": "D2", "min_power": 15, "max_power": 20, "allowed_phases": ["A", "B", "C"]},
        {"id": "D3", "min_power": 25, "max_power": 30, "allowed_phases": ["B", "C"]},
    ],
}


def test_robust_rehearsal_feasible():
    resp = client.post("/api/v1/robust-rehearsals", json=ROBUST_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert body["capacities"] == {"A": 100, "B": 100, "C": 100}
    # 字典序最小最优分配：D1->A, D2->B, D3->C
    assert body["assignments"] == [
        {"device_id": "D1", "phase": "A"},
        {"device_id": "D2", "phase": "B"},
        {"device_id": "D3", "phase": "C"},
    ]
    assert body["load_lower_bounds"] == {"A": 5, "B": 15, "C": 25}
    assert body["load_upper_bounds"] == {"A": 10, "B": 20, "C": 30}
    # 最坏负载差 = 上界最大值 30 - 下界最小值 5 = 25
    assert body["worst_imbalance"] == 25
    assert "预演" in body["message"]


def test_robust_rehearsal_infeasible():
    payload = {
        "capacities": {"A": 40, "B": 40, "C": 40},
        "devices": [
            {"id": "BIG", "min_power": 1, "max_power": 50, "allowed_phases": ["A", "B", "C"]},
        ],
    }
    resp = client.post("/api/v1/robust-rehearsals", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["worst_imbalance"] is None
    assert body["load_lower_bounds"] is None
    assert body["load_upper_bounds"] is None
    assert body["assignments"] == []
    assert "无稳健可行" in body["message"]


def test_robust_rehearsal_does_not_persist():
    before = len(client.get("/api/v1/calculations").json())
    resp = client.post("/api/v1/robust-rehearsals", json=ROBUST_PAYLOAD)
    assert resp.status_code == 200
    after = len(client.get("/api/v1/calculations").json())
    # 预演接口不写入任何历史计算记录
    assert after == before
    assert "id" not in resp.json()


def test_robust_rehearsal_capacity_checked_on_upper_bound():
    # 下界 3 不超 A 相容量 8，但上界 10 超过，故 D1 只能接 B
    payload = {
        "capacities": {"A": 8, "B": 10, "C": 0},
        "devices": [
            {"id": "D1", "min_power": 3, "max_power": 10, "allowed_phases": ["A", "B"]},
        ],
    }
    body = client.post("/api/v1/robust-rehearsals", json=payload).json()
    assert body["feasible"] is True
    assert body["assignments"] == [{"device_id": "D1", "phase": "B"}]
    assert body["load_upper_bounds"] == {"A": 0, "B": 10, "C": 0}


def test_robust_rehearsal_validation_min_above_max():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "min_power": 9, "max_power": 5, "allowed_phases": ["A"]},
        ],
    }
    assert client.post("/api/v1/robust-rehearsals", json=payload).status_code == 422


def test_robust_rehearsal_validation_non_positive_bounds():
    for field in ("min_power", "max_power"):
        payload = {
            "capacities": {"A": 10, "B": 10, "C": 10},
            "devices": [
                {"id": "D1", "min_power": 1, "max_power": 5, "allowed_phases": ["A"]},
            ],
        }
        payload["devices"][0][field] = 0
        assert (
            client.post("/api/v1/robust-rehearsals", json=payload).status_code == 422
        )


def test_robust_rehearsal_validation_duplicate_ids():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "min_power": 1, "max_power": 5, "allowed_phases": ["A"]},
            {"id": "D1", "min_power": 1, "max_power": 5, "allowed_phases": ["B"]},
        ],
    }
    assert client.post("/api/v1/robust-rehearsals", json=payload).status_code == 422


def test_robust_rehearsal_validation_too_many_devices():
    payload = {
        "capacities": {"A": 1000, "B": 1000, "C": 1000},
        "devices": [
            {"id": f"D{i}", "min_power": 1, "max_power": 1, "allowed_phases": ["A"]}
            for i in range(13)
        ],
    }
    assert client.post("/api/v1/robust-rehearsals", json=payload).status_code == 422


def test_robust_rehearsal_validation_empty_allowed_phases():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "min_power": 1, "max_power": 5, "allowed_phases": []},
        ],
    }
    assert client.post("/api/v1/robust-rehearsals", json=payload).status_code == 422


def test_robust_rehearsal_allowed_phases_deduplicated():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "min_power": 1, "max_power": 5, "allowed_phases": ["C", "A", "C"]},
        ],
    }
    resp = client.post("/api/v1/robust-rehearsals", json=payload)
    assert resp.status_code == 200
    assert resp.json()["feasible"] is True


STARTUP_PLAN_PAYLOAD = {
    "capacities": {"A": 10, "B": 10, "C": 10},
    "devices": [
        {"id": "D1", "power": 6, "allowed_phases": ["A"]},
        {"id": "D2", "power": 4, "allowed_phases": ["B"]},
        {"id": "D3", "power": 5, "allowed_phases": ["C"]},
    ],
}


def _startup_body(mapping):
    return {
        "startup_powers": [
            {"device_id": device_id, "startup_power": power}
            for device_id, power in mapping.items()
        ]
    }


def test_startup_plan_success():
    created = _create(STARTUP_PLAN_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/startup-plan",
        json=_startup_body({"D1": 8, "D2": 6, "D3": 9}),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["capacities"] == {"A": 10, "B": 10, "C": 10}
    assert body["feasible"] is True
    # (D1,D2,D3) 与 (D2,D1,D3) 峰值同为 8，取编号序列字典序最小者
    assert body["startup_order"] == ["D1", "D2", "D3"]
    assert body["peak_imbalance"] == 8
    assert len(body["steps"]) == 3
    assert body["steps"][0] == {
        "device_id": "D1",
        "phase": "A",
        "rated_power": 6,
        "startup_power": 8,
        "transient_loads": {"A": 8, "B": 0, "C": 0},
        "transient_imbalance": 8,
        "steady_loads": {"A": 6, "B": 0, "C": 0},
        "steady_imbalance": 6,
    }
    assert body["steps"][1] == {
        "device_id": "D2",
        "phase": "B",
        "rated_power": 4,
        "startup_power": 6,
        "transient_loads": {"A": 6, "B": 6, "C": 0},
        "transient_imbalance": 6,
        "steady_loads": {"A": 6, "B": 4, "C": 0},
        "steady_imbalance": 6,
    }
    assert body["steps"][2] == {
        "device_id": "D3",
        "phase": "C",
        "rated_power": 5,
        "startup_power": 9,
        "transient_loads": {"A": 6, "B": 4, "C": 9},
        "transient_imbalance": 5,
        "steady_loads": {"A": 6, "B": 4, "C": 5},
        "steady_imbalance": 2,
    }
    assert "预演" in body["message"]


def test_startup_plan_uses_record_fixed_phases():
    # 沿用记录中的固定相位：VALID_PAYLOAD 的分配为 D1->A, D2->B, D3->C
    created = _create(VALID_PAYLOAD)
    calc_id = created["id"]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/startup-plan",
        json=_startup_body({"D1": 15, "D2": 25, "D3": 35}),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    phases = {step["device_id"]: step["phase"] for step in body["steps"]}
    assert phases == {"D1": "A", "D2": "B", "D3": "C"}
    # 末步稳定负载即原记录各相负载
    assert body["steps"][-1]["steady_loads"] == created["loads"]
    assert body["startup_order"] == ["D1", "D2", "D3"]
    assert body["peak_imbalance"] == 25


def test_startup_plan_404():
    resp = client.post(
        "/api/v1/calculations/999999/startup-plan",
        json=_startup_body({"D1": 1}),
    )
    assert resp.status_code == 404


def test_startup_plan_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    assert created["feasible"] is False
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json=_startup_body({"BIG": 60, "FIX": 7}),
    )
    assert resp.status_code == 409


def test_startup_plan_no_safe_order():
    # 记录可行（D1 额定 10 接 A，容量 10），但启动功率 11 超容量：无安全顺序
    created = _create({
        "capacities": {"A": 10, "B": 0, "C": 0},
        "devices": [{"id": "D1", "power": 10, "allowed_phases": ["A"]}],
    })
    assert created["feasible"] is True
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json=_startup_body({"D1": 11}),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["peak_imbalance"] is None
    assert body["startup_order"] == []
    assert body["steps"] == []
    assert "无安全启动顺序" in body["message"]


def test_startup_plan_validation_below_rated():
    created = _create(VALID_PAYLOAD)
    # D1 额定功率 10，启动功率 9 低于额定
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json=_startup_body({"D1": 9, "D2": 20, "D3": 30}),
    )
    assert resp.status_code == 422
    assert "额定功率" in resp.json()["detail"]


def test_startup_plan_validation_missing_and_extra_ids():
    created = _create(VALID_PAYLOAD)
    # 缺少 D3、多出 D9：编号须与记录完全一致
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json=_startup_body({"D1": 10, "D2": 20, "D9": 30}),
    )
    assert resp.status_code == 422


def test_startup_plan_validation_duplicate_ids():
    created = _create(VALID_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json={"startup_powers": [
            {"device_id": "D1", "startup_power": 10},
            {"device_id": "D1", "startup_power": 12},
            {"device_id": "D2", "startup_power": 20},
            {"device_id": "D3", "startup_power": 30},
        ]},
    )
    assert resp.status_code == 422


def test_startup_plan_validation_non_positive_power():
    created = _create(VALID_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json=_startup_body({"D1": 0, "D2": 20, "D3": 30}),
    )
    assert resp.status_code == 422


def test_startup_plan_validation_empty_body():
    created = _create(VALID_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/startup-plan",
        json={"startup_powers": []},
    )
    assert resp.status_code == 422


def test_startup_plan_does_not_modify_record():
    created = _create(VALID_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/startup-plan",
        json=_startup_body({"D1": 15, "D2": 25, "D3": 35}),
    )
    assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/startup-plan",
        json=_startup_body({"D1": 15, "D2": 25, "D3": 35}),
    ).json()
    assert again["startup_order"] == resp.json()["startup_order"]
    assert again["peak_imbalance"] == resp.json()["peak_imbalance"]


# ---------------------------------------------------------------------------
# 单相故障保供预演
# ---------------------------------------------------------------------------

FAULT_PAYLOAD = {
    "capacities": {"A": 20, "B": 12, "C": 12},
    "devices": [
        # H1 固定 B（健康相设备，故障后保持原分配）
        {"id": "H1", "power": 7, "allowed_phases": ["B"]},
        # F1/F2 原最优分配均在 A；二者都只允许 A/B
        {"id": "F1", "power": 5, "allowed_phases": ["A", "B"]},
        {"id": "F2", "power": 5, "allowed_phases": ["A", "B"]},
    ],
}


def test_phase_fault_rehearsal_success():
    created = _create(FAULT_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True
    # 原记录分配（C 无设备，imbalance 最小化下两台均在 A）：A=10，B=7，C=0
    assert created["loads"] == {"A": 10, "B": 7, "C": 0}

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["fault_phase"] == "A"
    assert body["capacities"] == {"A": 20, "B": 12, "C": 12}
    assert body["original_loads"] == {"A": 10, "B": 7, "C": 0}
    # A 故障后 B 仅剩 5 空闲：两台 5 功率设备只能迁一台（均不允许 C），
    # 同功率同数量下序列字典序最小 -> F1 迁 B、F2 断开
    assert body["loads"] == {"A": 0, "B": 12, "C": 0}
    assert body["migrations"] == [
        {"device_id": "F1", "power": 5, "from_phase": "A", "to_phase": "B"}
    ]
    assert body["disconnected"] == [
        {"device_id": "F2", "power": 5, "phase": "A"}
    ]
    assert body["retained_power"] == 12
    assert body["retained_count"] == 2
    assert body["disconnected_power"] == 5
    assert body["disconnected_count"] == 1
    assert "预演" in body["message"]
    # 健康相负载不超容量，故障相负载为零
    assert body["loads"]["A"] == 0
    assert body["loads"]["B"] <= body["capacities"]["B"]
    assert body["loads"]["C"] <= body["capacities"]["C"]


def test_phase_fault_rehearsal_disconnect_when_no_capacity():
    payload = {
        "capacities": {"A": 20, "B": 10, "C": 10},
        "devices": [
            {"id": "H1", "power": 10, "allowed_phases": ["B"]},
            {"id": "H2", "power": 10, "allowed_phases": ["C"]},
            # A 相设备只能在故障相 A，无健康相可迁，必须断开
            {"id": "F1", "power": 8, "allowed_phases": ["A"]},
            # A 相设备可迁 B/C，但两相均被占满，亦须断开
            {"id": "F2", "power": 3, "allowed_phases": ["A", "B", "C"]},
        ],
    }
    created = _create(payload)
    assert created["feasible"] is True
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["loads"] == {"A": 0, "B": 10, "C": 10}
    assert body["migrations"] == []
    assert {d["device_id"] for d in body["disconnected"]} == {"F1", "F2"}
    # 断开列表按设备编号排序，携带功率与原相位
    assert [d["device_id"] for d in body["disconnected"]] == ["F1", "F2"]
    assert body["disconnected"][0] == {
        "device_id": "F1",
        "power": 8,
        "phase": "A",
    }
    assert body["disconnected_power"] == 11
    assert body["disconnected_count"] == 2
    assert body["retained_power"] == 20
    assert body["retained_count"] == 2


def test_phase_fault_rehearsal_other_fault_phases():
    created = _create(FAULT_PAYLOAD)
    calc_id = created["id"]
    # 原记录：F1/F2 在 A（各 5），H1 在 B（7），C 无设备
    # B 相故障：H1 仅允许 B，无健康相可迁，须断开；F1/F2 作为健康相设备
    # 保持原分配不动（尽管 A 尚有空闲，亦不迁移）
    resp_b = client.post(
        f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
        params={"fault_phase": "B"},
    )
    assert resp_b.status_code == 200
    body_b = resp_b.json()
    assert body_b["fault_phase"] == "B"
    assert body_b["loads"] == {"A": 10, "B": 0, "C": 0}
    assert body_b["migrations"] == []
    assert body_b["disconnected"] == [
        {"device_id": "H1", "power": 7, "phase": "B"}
    ]
    assert body_b["retained_power"] == 10
    assert body_b["retained_count"] == 2
    assert body_b["disconnected_power"] == 7

    # C 相故障：C 相本就无设备，负载与原记录一致（C 为 0）
    resp_c = client.post(
        f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
        params={"fault_phase": "C"},
    )
    assert resp_c.status_code == 200
    body_c = resp_c.json()
    assert body_c["loads"] == {"A": 10, "B": 7, "C": 0}
    assert body_c["migrations"] == []
    assert body_c["disconnected"] == []
    assert body_c["retained_power"] == 17
    assert body_c["retained_count"] == 3


def test_phase_fault_rehearsal_404():
    resp = client.post(
        "/api/v1/calculations/999999/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    )
    assert resp.status_code == 404


def test_phase_fault_rehearsal_409_when_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    assert created["feasible"] is False
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    )
    assert resp.status_code == 409


def test_phase_fault_rehearsal_invalid_phase():
    created = _create(FAULT_PAYLOAD)
    # 故障相取值不在 A/B/C：查询参数校验返回 422
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/phase-fault-rehearsal",
        params={"fault_phase": "X"},
    )
    assert resp.status_code == 422


def test_phase_fault_rehearsal_missing_phase_param():
    created = _create(FAULT_PAYLOAD)
    # 缺少必填的 fault_phase 查询参数：422
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/phase-fault-rehearsal"
    )
    assert resp.status_code == 422


def test_phase_fault_rehearsal_does_not_modify_record():
    created = _create(FAULT_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    for phase in ("A", "B", "C"):
        resp = client.post(
            f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
            params={"fault_phase": phase},
        )
        assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 同一故障相重复预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    ).json()
    first = client.post(
        f"/api/v1/calculations/{calc_id}/phase-fault-rehearsal",
        params={"fault_phase": "A"},
    ).json()
    assert again == first


# ---------------------------------------------------------------------------
# 新增设备接入预演
# ---------------------------------------------------------------------------

# 原记录：D1(6, A/B) 与 D2(4, B/C)，容量各 10。
# 最优分配为 D1->A、D2->B（负载 6/4/0，差值 6 且字典序最小）。
ADDITION_BASE_PAYLOAD = {
    "capacities": {"A": 10, "B": 10, "C": 10},
    "devices": [
        {"id": "D1", "power": 6, "allowed_phases": ["A", "B"]},
        {"id": "D2", "power": 4, "allowed_phases": ["B", "C"]},
    ],
}


def _addition_body(devices):
    return {"devices": devices}


def test_device_addition_plan_no_migration():
    created = _create(ADDITION_BASE_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True
    assert created["loads"] == {"A": 6, "B": 4, "C": 0}

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 4, "allowed_phases": ["C"]}]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["capacities"] == {"A": 10, "B": 10, "C": 10}
    assert body["feasible"] is True
    # N1 只能接 C：不改相即得负载 6/4/4
    assert body["migrated_count"] == 0
    assert body["migrations"] == []
    assert body["loads"] == {"A": 6, "B": 4, "C": 4}
    assert body["imbalance"] == 2
    assert body["existing_assignments"] == [
        {"device_id": "D1", "phase": "A"},
        {"device_id": "D2", "phase": "B"},
    ]
    assert body["new_assignments"] == [{"device_id": "N1", "phase": "C"}]
    assert "预演" in body["message"]


def test_device_addition_plan_min_migrations_before_imbalance():
    # 不改相时唯一可行方案负载差为 10（N1 只能接 B：6/10/0）；
    # 改相 1 台可达负载差 2（D2 迁 C、N1 接 B：6/6/4）。
    # 改相台数优先，应取不改相方案。
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 6, "allowed_phases": ["A", "B"]}]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert body["migrated_count"] == 0
    assert body["migrations"] == []
    assert body["loads"] == {"A": 6, "B": 10, "C": 0}
    assert body["imbalance"] == 10
    assert body["new_assignments"] == [{"device_id": "N1", "phase": "B"}]


def test_device_addition_plan_migration_forced():
    # 容量收紧为 8：N1(5, A/B) 在原分配下无处可放，
    # 必须改相一台：D2 迁 C、N1 接 B -> 负载 6/5/4
    payload = {
        "capacities": {"A": 8, "B": 8, "C": 8},
        "devices": [
            {"id": "D1", "power": 6, "allowed_phases": ["A", "B"]},
            {"id": "D2", "power": 4, "allowed_phases": ["B", "C"]},
        ],
    }
    created = _create(payload)
    assert created["feasible"] is True
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 5, "allowed_phases": ["A", "B"]}]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert body["migrated_count"] == 1
    assert body["migrations"] == [
        {"device_id": "D2", "power": 4, "from_phase": "B", "to_phase": "C"}
    ]
    assert body["existing_assignments"] == [
        {"device_id": "D1", "phase": "A"},
        {"device_id": "D2", "phase": "C"},
    ]
    assert body["new_assignments"] == [{"device_id": "N1", "phase": "B"}]
    assert body["loads"] == {"A": 6, "B": 5, "C": 4}
    assert body["imbalance"] == 2


def test_device_addition_plan_infeasible():
    # 新设备功率 100，任何相位都放不下：保持原容量时无解
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [{"id": "BIG", "power": 100, "allowed_phases": ["A", "B", "C"]}]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["imbalance"] is None
    assert body["loads"] is None
    assert body["migrated_count"] is None
    assert body["existing_assignments"] == []
    assert body["new_assignments"] == []
    assert body["migrations"] == []
    assert "无可行" in body["message"]


def test_device_addition_plan_404():
    resp = client.post(
        "/api/v1/calculations/999999/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 1, "allowed_phases": ["A"]}]
        ),
    )
    assert resp.status_code == 404


def test_device_addition_plan_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    assert created["feasible"] is False
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 1, "allowed_phases": ["A", "B", "C"]}]
        ),
    )
    assert resp.status_code == 409


def test_device_addition_plan_422_duplicate_with_record():
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [{"id": "D1", "power": 1, "allowed_phases": ["A"]}]
        ),
    )
    assert resp.status_code == 422
    assert "重复" in resp.json()["detail"]


def test_device_addition_plan_422_total_exceeds_twelve():
    created = _create(ADDITION_BASE_PAYLOAD)
    # 记录已有 2 台，再提交 11 台 -> 总数 13 超过 12
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [
                {"id": f"N{i}", "power": 1, "allowed_phases": ["A"]}
                for i in range(11)
            ]
        ),
    )
    assert resp.status_code == 422
    assert "12" in resp.json()["detail"]


def test_device_addition_plan_total_exactly_twelve():
    # 记录 2 台 + 新增 10 台 = 12 台：允许，且全部接入
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [
                {"id": f"N{i}", "power": 1, "allowed_phases": ["A", "B", "C"]}
                for i in range(10)
            ]
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert len(body["existing_assignments"]) == 2
    assert len(body["new_assignments"]) == 10
    total = sum(body["loads"][p] for p in ("A", "B", "C"))
    assert total == 6 + 4 + 10
    for p in ("A", "B", "C"):
        assert body["loads"][p] <= 10


def test_device_addition_plan_validation_duplicate_new_ids():
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json=_addition_body(
            [
                {"id": "N1", "power": 1, "allowed_phases": ["A"]},
                {"id": "N1", "power": 2, "allowed_phases": ["B"]},
            ]
        ),
    )
    assert resp.status_code == 422


def test_device_addition_plan_validation_empty_devices():
    created = _create(ADDITION_BASE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/device-addition-plan",
        json={"devices": []},
    )
    assert resp.status_code == 422


def test_device_addition_plan_validation_bad_device_fields():
    created = _create(ADDITION_BASE_PAYLOAD)
    calc_id = created["id"]
    # 功率非正整数
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body([{"id": "N1", "power": 0, "allowed_phases": ["A"]}]),
    )
    assert resp.status_code == 422
    # 允许相位为空
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body([{"id": "N1", "power": 1, "allowed_phases": []}]),
    )
    assert resp.status_code == 422
    # 非法相位取值
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body([{"id": "N1", "power": 1, "allowed_phases": ["X"]}]),
    )
    assert resp.status_code == 422


def test_device_addition_plan_does_not_modify_record():
    created = _create(ADDITION_BASE_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 6, "allowed_phases": ["A", "B", "C"]}]
        ),
    )
    assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/device-addition-plan",
        json=_addition_body(
            [{"id": "N1", "power": 6, "allowed_phases": ["A", "B", "C"]}]
        ),
    ).json()
    assert again == resp.json()


# ---------------------------------------------------------------------------
# 双时段错峰接入规划
# ---------------------------------------------------------------------------

# D3 只能晚、D4 只能早；目标 1 最优 32 要求 D1 晚、D2 早；
# 早时段 D2(20)/D4(12) 必分两相（差 20），晚时段差 15
SHIFT_PLAN_PAYLOAD = {
    "capacities": {"A": 30, "B": 30, "C": 30},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A", "B"],
         "allowed_slots": ["morning", "evening"]},
        {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"],
         "allowed_slots": ["morning", "evening"]},
        {"id": "D3", "power": 15, "allowed_phases": ["B", "C"],
         "allowed_slots": ["evening"]},
        {"id": "D4", "power": 12, "allowed_phases": ["A", "C"],
         "allowed_slots": ["morning"]},
    ],
}


def test_shift_plan_feasible():
    resp = client.post("/api/v1/shift-plans", json=SHIFT_PLAN_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is True
    assert body["capacities"] == {"A": 30, "B": 30, "C": 30}
    assert body["peak_total_load"] == 32
    assert body["peak_imbalance"] == 20
    assert body["slots"] == {
        "morning": {
            "loads": {"A": 20, "B": 0, "C": 12},
            "total_load": 32,
            "imbalance": 20,
        },
        "evening": {
            "loads": {"A": 10, "B": 15, "C": 0},
            "total_load": 25,
            "imbalance": 15,
        },
    }
    # 按设备编号排序的 (时段, 相位) 安排
    assert body["assignments"] == [
        {"device_id": "D1", "slot": "evening", "phase": "A"},
        {"device_id": "D2", "slot": "morning", "phase": "A"},
        {"device_id": "D3", "slot": "evening", "phase": "B"},
        {"device_id": "D4", "slot": "morning", "phase": "C"},
    ]
    assert "预演" in body["message"]


def test_shift_plan_infeasible():
    payload = {
        "capacities": {"A": 5, "B": 0, "C": 0},
        "devices": [
            {"id": "BIG", "power": 10, "allowed_phases": ["A", "B", "C"],
             "allowed_slots": ["morning", "evening"]},
        ],
    }
    resp = client.post("/api/v1/shift-plans", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["peak_total_load"] is None
    assert body["peak_imbalance"] is None
    assert body["slots"] is None
    assert body["assignments"] == []
    assert "无可行" in body["message"]


def test_shift_plan_shared_capacity_across_slots():
    # 两时段共用容量：两台只能接 A 的设备功率各 6、A 相容量 6，
    # 分处两时段即各时段 A 相负载均不超容量
    payload = {
        "capacities": {"A": 6, "B": 0, "C": 0},
        "devices": [
            {"id": "E1", "power": 6, "allowed_phases": ["A"],
             "allowed_slots": ["morning", "evening"]},
            {"id": "E2", "power": 6, "allowed_phases": ["A"],
             "allowed_slots": ["morning", "evening"]},
        ],
    }
    body = client.post("/api/v1/shift-plans", json=payload).json()
    assert body["feasible"] is True
    assert body["peak_total_load"] == 6
    assert body["slots"]["morning"]["loads"]["A"] == 6
    assert body["slots"]["evening"]["loads"]["A"] == 6
    # 字典序最小：E1 早、E2 晚
    assert body["assignments"] == [
        {"device_id": "E1", "slot": "morning", "phase": "A"},
        {"device_id": "E2", "slot": "evening", "phase": "A"},
    ]


def test_shift_plan_does_not_persist():
    before = len(client.get("/api/v1/calculations").json())
    resp = client.post("/api/v1/shift-plans", json=SHIFT_PLAN_PAYLOAD)
    assert resp.status_code == 200
    after = len(client.get("/api/v1/calculations").json())
    # 预演接口不写入任何历史计算记录
    assert after == before
    assert "id" not in resp.json()

    # 重复预演结果确定且相同（幂等读操作）
    again = client.post("/api/v1/shift-plans", json=SHIFT_PLAN_PAYLOAD).json()
    assert again == resp.json()


def test_shift_plan_validation_duplicate_ids():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "power": 5, "allowed_phases": ["A"],
             "allowed_slots": ["morning"]},
            {"id": "D1", "power": 5, "allowed_phases": ["B"],
             "allowed_slots": ["evening"]},
        ],
    }
    assert client.post("/api/v1/shift-plans", json=payload).status_code == 422


def test_shift_plan_validation_device_count():
    # 0 台与 9 台均越界（允许 1~8 台）
    base = {"capacities": {"A": 100, "B": 100, "C": 100}}
    assert client.post(
        "/api/v1/shift-plans", json={**base, "devices": []}
    ).status_code == 422
    too_many = {
        **base,
        "devices": [
            {"id": f"D{i}", "power": 1, "allowed_phases": ["A"],
             "allowed_slots": ["morning"]}
            for i in range(9)
        ],
    }
    assert client.post("/api/v1/shift-plans", json=too_many).status_code == 422
    # 8 台为上限，允许
    exactly_eight = {
        **base,
        "devices": [
            {"id": f"D{i}", "power": 1, "allowed_phases": ["A"],
             "allowed_slots": ["morning"]}
            for i in range(8)
        ],
    }
    resp = client.post("/api/v1/shift-plans", json=exactly_eight)
    assert resp.status_code == 200
    assert resp.json()["feasible"] is True


def test_shift_plan_validation_bad_device_fields():
    base_device = {
        "id": "D1",
        "power": 5,
        "allowed_phases": ["A"],
        "allowed_slots": ["morning"],
    }
    caps = {"A": 10, "B": 10, "C": 10}

    def post(device):
        return client.post(
            "/api/v1/shift-plans",
            json={"capacities": caps, "devices": [device]},
        )

    # 功率非正整数
    assert post({**base_device, "power": 0}).status_code == 422
    # 允许相位为空 / 非法相位
    assert post({**base_device, "allowed_phases": []}).status_code == 422
    assert post({**base_device, "allowed_phases": ["X"]}).status_code == 422
    # 允许时段为空 / 非法时段
    assert post({**base_device, "allowed_slots": []}).status_code == 422
    assert post({**base_device, "allowed_slots": ["noon"]}).status_code == 422
    # 容量为负
    resp = client.post(
        "/api/v1/shift-plans",
        json={"capacities": {"A": -1, "B": 10, "C": 10},
              "devices": [base_device]},
    )
    assert resp.status_code == 422


def test_shift_plan_allowed_values_deduplicated():
    payload = {
        "capacities": {"A": 10, "B": 10, "C": 10},
        "devices": [
            {"id": "D1", "power": 5, "allowed_phases": ["C", "A", "C"],
             "allowed_slots": ["evening", "morning", "evening"]},
        ],
    }
    resp = client.post("/api/v1/shift-plans", json=payload)
    assert resp.status_code == 200
    assert resp.json()["feasible"] is True


# ---------------------------------------------------------------------------
# 运行功率日志复盘
# ---------------------------------------------------------------------------

# 三台设备分别固定接 A/B/C（各 10，容量各 25），便于直接构造各相负载
REPLAY_BASE_PAYLOAD = {
    "capacities": {"A": 25, "B": 25, "C": 25},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A"]},
        {"id": "D2", "power": 10, "allowed_phases": ["B"]},
        {"id": "D3", "power": 10, "allowed_phases": ["C"]},
    ],
}


def _replay_body(events, window_start=1000, window_end=2000):
    return {
        "window_start": window_start,
        "window_end": window_end,
        "events": events,
    }


def _create_replay_record():
    created = _create(REPLAY_BASE_PAYLOAD)
    assert created["feasible"] is True
    return created["id"]


def test_power_log_replay_alerts_and_peaks():
    calc_id = _create_replay_record()
    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 20},
        {"device_id": "D1", "timestamp": 1200, "power": 30},
        {"device_id": "D2", "timestamp": 1300, "power": 30},
        {"device_id": "D1", "timestamp": 1400, "power": 0},
        {"device_id": "D2", "timestamp": 1500, "power": 10},
        {"device_id": "D3", "timestamp": 1600, "power": 40},
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["capacities"] == {"A": 25, "B": 25, "C": 25}
    assert body["window_start"] == 1000
    assert body["window_end"] == 2000
    assert body["peak_loads"] == {"A": 30, "B": 30, "C": 40}
    # [1200,1500) 三段连续超容合并；[1600,2000) 超容延伸至窗口终点
    assert body["alerts"] == [
        {"start": 1200, "end": 1500,
         "max_overload": {"A": 5, "B": 5, "C": 0}},
        {"start": 1600, "end": 2000,
         "max_overload": {"A": 0, "B": 0, "C": 15}},
    ]
    assert "复盘" in body["message"]


def test_power_log_replay_same_timestamp_batch():
    # 同一时刻多台设备的事件批量生效
    calc_id = _create_replay_record()
    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 30},
        {"device_id": "D2", "timestamp": 1100, "power": 30},
    ]
    body = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    ).json()
    assert body["peak_loads"] == {"A": 30, "B": 30, "C": 0}
    assert body["alerts"] == [
        {"start": 1100, "end": 2000,
         "max_overload": {"A": 5, "B": 5, "C": 0}},
    ]


def test_power_log_replay_uses_record_phases_and_capacities():
    # 沿用记录中的相位与容量：VALID_PAYLOAD 分配为 D1->A, D2->B, D3->C，
    # 容量各 100；D3 事件功率 130 使 C 相超额 30
    created = _create(VALID_PAYLOAD)
    calc_id = created["id"]
    events = [
        {"device_id": "D3", "timestamp": 500, "power": 130},
        {"device_id": "D1", "timestamp": 600, "power": 90},
    ]
    body = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events, window_start=400, window_end=700),
    ).json()
    assert body["capacities"] == {"A": 100, "B": 100, "C": 100}
    assert body["peak_loads"] == {"A": 90, "B": 0, "C": 130}
    assert body["alerts"] == [
        {"start": 500, "end": 700,
         "max_overload": {"A": 0, "B": 0, "C": 30}},
    ]


def test_power_log_replay_no_events():
    calc_id = _create_replay_record()
    body = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body([]),
    ).json()
    assert body["alerts"] == []
    assert body["peak_loads"] == {"A": 0, "B": 0, "C": 0}
    assert "未超过" in body["message"]


def test_power_log_replay_event_at_window_start():
    # 事件时刻等于窗口起点（左闭）：自起点即生效
    calc_id = _create_replay_record()
    events = [{"device_id": "D1", "timestamp": 1000, "power": 30}]
    body = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    ).json()
    assert body["alerts"] == [
        {"start": 1000, "end": 2000,
         "max_overload": {"A": 5, "B": 0, "C": 0}},
    ]


def test_power_log_replay_404():
    resp = client.post(
        "/api/v1/calculations/999999/power-log-replay",
        json=_replay_body([]),
    )
    assert resp.status_code == 404


def test_power_log_replay_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    assert created["feasible"] is False
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/power-log-replay",
        json=_replay_body([]),
    )
    assert resp.status_code == 409


def test_power_log_replay_422_unknown_device():
    calc_id = _create_replay_record()
    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 5},
        {"device_id": "GHOST", "timestamp": 1200, "power": 5},
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 422
    assert "未知设备" in resp.json()["detail"]


def test_power_log_replay_422_window_not_ordered():
    calc_id = _create_replay_record()
    # 起点等于终点、起点晚于终点均不允许
    for start, end in ((1000, 1000), (2000, 1000)):
        resp = client.post(
            f"/api/v1/calculations/{calc_id}/power-log-replay",
            json=_replay_body([], window_start=start, window_end=end),
        )
        assert resp.status_code == 422


def test_power_log_replay_422_event_outside_window():
    calc_id = _create_replay_record()
    # 时刻等于窗口终点（右开）与早于窗口起点均不允许
    for timestamp in (2000, 3000, 999):
        events = [{"device_id": "D1", "timestamp": timestamp, "power": 5}]
        resp = client.post(
            f"/api/v1/calculations/{calc_id}/power-log-replay",
            json=_replay_body(events),
        )
        assert resp.status_code == 422


def test_power_log_replay_422_duplicate_device_timestamp():
    calc_id = _create_replay_record()
    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 5},
        {"device_id": "D1", "timestamp": 1100, "power": 8},
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 422
    # 不同设备同一时刻允许
    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 5},
        {"device_id": "D2", "timestamp": 1100, "power": 8},
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 200


def test_power_log_replay_422_negative_power():
    calc_id = _create_replay_record()
    events = [{"device_id": "D1", "timestamp": 1100, "power": -1}]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 422


def test_power_log_replay_event_count_limit():
    calc_id = _create_replay_record()
    # 200 条为上限，允许
    events = [
        {"device_id": "D1", "timestamp": 1000 + i, "power": 1}
        for i in range(200)
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events, window_start=1000, window_end=1201),
    )
    assert resp.status_code == 200
    # 201 条超出上限
    events = [
        {"device_id": "D1", "timestamp": 1000 + i, "power": 1}
        for i in range(201)
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events, window_start=1000, window_end=1201),
    )
    assert resp.status_code == 422


def test_power_log_replay_does_not_modify_record():
    calc_id = _create_replay_record()
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    events = [
        {"device_id": "D1", "timestamp": 1100, "power": 30},
        {"device_id": "D2", "timestamp": 1200, "power": 30},
    ]
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    )
    assert resp.status_code == 200

    # 复盘不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次复盘结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/power-log-replay",
        json=_replay_body(events),
    ).json()
    assert again == resp.json()


# ---------------------------------------------------------------------------
# 电缆盘裁切预演
# ---------------------------------------------------------------------------

CABLE_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A", "B", "C"]},
        {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"]},
        {"id": "D3", "power": 20, "allowed_phases": ["A", "B", "C"]},
    ],
}


def _cable_body(segments, reels, cut_loss=0):
    return {
        "segments": [
            {"device_id": device_id, "length": length}
            for device_id, length in segments
        ],
        "reels": [{"id": rid, "length": length} for rid, length in reels],
        "cut_loss": cut_loss,
    }


def test_cable_cutting_success():
    created = _create(CABLE_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/cable-cutting-plan",
        json=_cable_body(
            [("D1", 10), ("D2", 20), ("D3", 20)],
            [("R1", 100), ("R2", 50)],
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["cut_loss"] == 0
    assert body["feasible"] is True
    # 单盘即可装下全部 50：启用 1 盘并取最短可容纳盘 R2(50)
    assert body["reel_count"] == 1
    assert body["reel_total_length"] == 50
    assert body["reel_sequence"] == ["R2", "R2", "R2"]
    assert len(body["reel_plans"]) == 1
    plan = body["reel_plans"][0]
    assert plan == {
        "reel_id": "R2",
        "reel_length": 50,
        "cuts": [
            {"device_id": "D1", "length": 10},
            {"device_id": "D2", "length": 20},
            {"device_id": "D3", "length": 20},
        ],
        "occupied": 50,
        "remaining": 0,
    }
    assert "预演" in body["message"]


def test_cable_cutting_cut_loss():
    created = _create(CABLE_PAYLOAD)
    # 两段 10、损耗 1：同盘占用 21
    body_ok = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body([("D1", 10), ("D2", 10), ("D3", 1)], [("R1", 21)], 1),
    ).json()
    assert body_ok["feasible"] is True
    assert body_ok["reel_plans"][0]["occupied"] == 21
    assert body_ok["reel_plans"][0]["remaining"] == 0

    # 盘长 20 放不下占用 21：无解
    body_no = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body([("D1", 10), ("D2", 10), ("D3", 1)], [("R1", 20)], 1),
    ).json()
    assert body_no["feasible"] is False
    assert body_no["reel_count"] is None
    assert body_no["reel_total_length"] is None
    assert body_no["reel_sequence"] == []
    assert body_no["reel_plans"] == []
    assert "无可裁" in body_no["message"]


def test_cable_cutting_multi_reel_and_sequence():
    created = _create(CABLE_PAYLOAD)
    # D1=7/D2=7 不能同盘（盘均 < 14），D3=1 也需安排；盘 R1/R2=10、R3=12
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body(
            [("D1", 7), ("D2", 7), ("D3", 1)],
            [("R1", 10), ("R2", 10), ("R3", 12)],
        ),
    )
    body = resp.json()
    assert body["feasible"] is True
    # 最优 2 盘（D3 与一台 7 同盘）；启用 R1/R2 总长 20 最短
    assert body["reel_count"] == 2
    assert body["reel_total_length"] == 20
    assignment = {}
    for plan in body["reel_plans"]:
        for cut in plan["cuts"]:
            assignment[cut["device_id"]] = plan["reel_id"]
    assert set(body["reel_sequence"]) == {"R1", "R2"}
    # 裁切清单按盘编号排序，每盘占用不超盘长
    assert [p["reel_id"] for p in body["reel_plans"]] == ["R1", "R2"]
    for plan in body["reel_plans"]:
        assert plan["occupied"] <= plan["reel_length"]
        assert plan["remaining"] == plan["reel_length"] - plan["occupied"]


def test_cable_cutting_404():
    resp = client.post(
        "/api/v1/calculations/999999/cable-cutting-plan",
        json=_cable_body([("D1", 1)], [("R1", 1)]),
    )
    assert resp.status_code == 404


def test_cable_cutting_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    assert created["feasible"] is False
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body([("BIG", 1), ("FIX", 1)], [("R1", 10)]),
    )
    assert resp.status_code == 409


def test_cable_cutting_409_when_more_than_eight_devices():
    payload = {
        "capacities": {"A": 1000, "B": 1000, "C": 1000},
        "devices": [
            {"id": f"D{i}", "power": 1, "allowed_phases": ["A", "B", "C"]}
            for i in range(9)
        ],
    }
    created = _create(payload)
    assert created["feasible"] is True
    segments = [(f"D{i}", 1) for i in range(9)]
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body(segments, [("R1", 100)]),
    )
    assert resp.status_code == 409
    assert "8" in resp.json()["detail"]


def test_cable_cutting_422_segment_ids_mismatch():
    created = _create(CABLE_PAYLOAD)
    # 缺少 D3、多出 D9
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body(
            [("D1", 1), ("D2", 1), ("D9", 1)], [("R1", 10)]
        ),
    )
    assert resp.status_code == 422


def test_cable_cutting_validation():
    created = _create(CABLE_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/cable-cutting-plan"

    # 段长非正整数
    resp = client.post(
        url, json=_cable_body([("D1", 0), ("D2", 1), ("D3", 1)], [("R1", 10)])
    )
    assert resp.status_code == 422

    # 段设备编号重复
    resp = client.post(
        url,
        json={
            "segments": [
                {"device_id": "D1", "length": 1},
                {"device_id": "D1", "length": 1},
                {"device_id": "D2", "length": 1},
                {"device_id": "D3", "length": 1},
            ],
            "reels": [{"id": "R1", "length": 10}],
            "cut_loss": 0,
        },
    )
    assert resp.status_code == 422

    # 盘编号重复
    resp = client.post(
        url,
        json={
            "segments": [
                {"device_id": "D1", "length": 1},
                {"device_id": "D2", "length": 1},
                {"device_id": "D3", "length": 1},
            ],
            "reels": [
                {"id": "R1", "length": 10},
                {"id": "R1", "length": 5},
            ],
            "cut_loss": 0,
        },
    )
    assert resp.status_code == 422

    # 盘长非正整数
    resp = client.post(
        url,
        json={
            "segments": [
                {"device_id": "D1", "length": 1},
                {"device_id": "D2", "length": 1},
                {"device_id": "D3", "length": 1},
            ],
            "reels": [{"id": "R1", "length": 0}],
            "cut_loss": 0,
        },
    )
    assert resp.status_code == 422

    # 切割损耗为负
    resp = client.post(
        url,
        json={
            "segments": [
                {"device_id": "D1", "length": 1},
                {"device_id": "D2", "length": 1},
                {"device_id": "D3", "length": 1},
            ],
            "reels": [{"id": "R1", "length": 10}],
            "cut_loss": -1,
        },
    )
    assert resp.status_code == 422

    # 盘数超过 8
    resp = client.post(
        url,
        json={
            "segments": [
                {"device_id": "D1", "length": 1},
                {"device_id": "D2", "length": 1},
                {"device_id": "D3", "length": 1},
            ],
            "reels": [{"id": f"R{i}", "length": 10} for i in range(9)],
            "cut_loss": 0,
        },
    )
    assert resp.status_code == 422

    # 段数超过 8（即便记录只有 3 台，请求体上限也为 8）
    resp = client.post(
        url,
        json={
            "segments": [{"device_id": f"X{i}", "length": 1} for i in range(9)],
            "reels": [{"id": "R1", "length": 10}],
            "cut_loss": 0,
        },
    )
    assert resp.status_code == 422


def test_cable_cutting_no_reels_infeasible():
    created = _create(CABLE_PAYLOAD)
    body = client.post(
        f"/api/v1/calculations/{created['id']}/cable-cutting-plan",
        json=_cable_body([("D1", 1), ("D2", 1), ("D3", 1)], []),
    ).json()
    assert body["feasible"] is False


def test_cable_cutting_does_not_modify_record():
    created = _create(CABLE_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/cable-cutting-plan",
        json=_cable_body(
            [("D1", 10), ("D2", 20), ("D3", 20)], [("R1", 100), ("R2", 50)]
        ),
    )
    assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/cable-cutting-plan",
        json=_cable_body(
            [("D1", 10), ("D2", 20), ("D3", 20)], [("R1", 100), ("R2", 50)]
        ),
    ).json()
    assert again == resp.json()


# ---------------------------------------------------------------------------
# 电缆路由预演
# ---------------------------------------------------------------------------

CABLE_ROUTE_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A"]},
        {"id": "D2", "power": 20, "allowed_phases": ["B"]},
        {"id": "D3", "power": 30, "allowed_phases": ["C"]},
    ],
}


def _route_body(endpoints, edges=None, node_count=4, starts=None):
    return {
        "node_count": node_count,
        "edges": edges
        if edges is not None
        else [
            {"u": 0, "v": 1, "length": 1, "capacity": 4},
            {"u": 1, "v": 2, "length": 2, "capacity": 4},
            {"u": 2, "v": 3, "length": 3, "capacity": 4},
        ],
        "phase_starts": starts
        if starts is not None
        else {"A": 0, "B": 1, "C": 2},
        "device_endpoints": [
            {"device_id": device_id, "endpoint": endpoint}
            for device_id, endpoint in endpoints
        ],
    }


def test_cable_routes_success():
    created = _create(CABLE_ROUTE_PAYLOAD)
    calc_id = created["id"]

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/cable-routes",
        json=_route_body([("D1", 1), ("D2", 2), ("D3", 3)]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == calc_id
    assert body["node_count"] == 4
    assert body["feasible"] is True
    assert body["total_length"] == 6  # D1:0->1(1) + D2:1->2(2) + D3:2->3(3)
    assert body["paths"] == [
        {"device_id": "D1", "phase": "A", "endpoint": 1, "nodes": [0, 1], "length": 1},
        {"device_id": "D2", "phase": "B", "endpoint": 2, "nodes": [1, 2], "length": 2},
        {"device_id": "D3", "phase": "C", "endpoint": 3, "nodes": [2, 3], "length": 3},
    ]
    # 各边按端点编号排序返回，占用 = 经过该边的电缆数
    assert body["edge_usage"] == [
        {"u": 0, "v": 1, "length": 1, "capacity": 4, "occupied": 1},
        {"u": 1, "v": 2, "length": 2, "capacity": 4, "occupied": 1},
        {"u": 2, "v": 3, "length": 3, "capacity": 4, "occupied": 1},
    ]
    assert "预演" in body["message"]


def test_cable_routes_zero_edge_path():
    created = _create(CABLE_ROUTE_PAYLOAD)
    # 每台设备终点即所属相起点：零边路径，总长度 0
    body = client.post(
        f"/api/v1/calculations/{created['id']}/cable-routes",
        json=_route_body([("D1", 0), ("D2", 1), ("D3", 2)]),
    ).json()
    assert body["feasible"] is True
    assert body["total_length"] == 0
    assert [p["nodes"] for p in body["paths"]] == [[0], [1], [2]]
    assert all(u["occupied"] == 0 for u in body["edge_usage"])


def test_cable_routes_capacity_detour_and_lex_order():
    created = _create(CABLE_ROUTE_PAYLOAD)
    edges = [
        {"u": 0, "v": 3, "length": 1, "capacity": 1},
        {"u": 0, "v": 1, "length": 1, "capacity": 4},
        {"u": 1, "v": 2, "length": 1, "capacity": 4},
        {"u": 2, "v": 3, "length": 1, "capacity": 4},
    ]
    # D1/D2 均归 A 相的记录：单独构造 A/A 两台
    payload = {
        "capacities": {"A": 100, "B": 100, "C": 100},
        "devices": [
            {"id": "D1", "power": 10, "allowed_phases": ["A"]},
            {"id": "D2", "power": 20, "allowed_phases": ["A"]},
        ],
    }
    rec = _create(payload)
    body = client.post(
        f"/api/v1/calculations/{rec['id']}/cable-routes",
        json=_route_body(
            [("D1", 3), ("D2", 3)], edges=edges, starts={"A": 0, "B": 0, "C": 0}
        ),
    ).json()
    assert body["feasible"] is True
    # 直连容量 1：一台走 (0,3) 长度 1，另一台绕行 (0,1,2,3) 长度 3，总长 4；
    # 等长搭配中字典序最小者让 D1 走字典序更小的 (0,1,2,3)
    assert body["total_length"] == 4
    assert body["paths"][0]["nodes"] == [0, 1, 2, 3]
    assert body["paths"][1]["nodes"] == [0, 3]
    for usage in body["edge_usage"]:
        assert usage["occupied"] <= usage["capacity"]


def test_cable_routes_infeasible_capacity():
    created = _create(CABLE_ROUTE_PAYLOAD)
    # D1(0->1) 与 D2(1->0) 都必经唯一边 0-1，容量 1：无解
    edges = [
        {"u": 0, "v": 1, "length": 1, "capacity": 1},
        {"u": 1, "v": 2, "length": 1, "capacity": 4},
        {"u": 2, "v": 3, "length": 1, "capacity": 4},
    ]
    body = client.post(
        f"/api/v1/calculations/{created['id']}/cable-routes",
        json=_route_body([("D1", 1), ("D2", 0), ("D3", 3)], edges=edges),
    ).json()
    assert body["feasible"] is False
    assert body["total_length"] is None
    assert body["paths"] == []
    # 无解时仍列出全部边（规范化并按端点排序），占用均为 0
    assert body["edge_usage"] == [
        {"u": 0, "v": 1, "length": 1, "capacity": 1, "occupied": 0},
        {"u": 1, "v": 2, "length": 1, "capacity": 4, "occupied": 0},
        {"u": 2, "v": 3, "length": 1, "capacity": 4, "occupied": 0},
    ]
    assert "无可布路由" in body["message"]


def test_cable_routes_infeasible_unreachable():
    created = _create(CABLE_ROUTE_PAYLOAD)
    edges = [
        {"u": 0, "v": 1, "length": 1, "capacity": 4},
        # 节点 3 为孤立节点，D3 自 C 相起点 2 无法到达
    ]
    body = client.post(
        f"/api/v1/calculations/{created['id']}/cable-routes",
        json=_route_body(
            [("D1", 1), ("D2", 1), ("D3", 3)], edges=edges
        ),
    ).json()
    assert body["feasible"] is False


def test_cable_routes_404():
    resp = client.post(
        "/api/v1/calculations/999999/cable-routes",
        json=_route_body([("D1", 0)]),
    )
    assert resp.status_code == 404


def test_cable_routes_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-routes",
        json=_route_body([("BIG", 0), ("FIX", 0)]),
    )
    assert resp.status_code == 409


def test_cable_routes_422_when_more_than_four_devices():
    payload = {
        "capacities": {"A": 1000, "B": 1000, "C": 1000},
        "devices": [
            {"id": f"D{i}", "power": 1, "allowed_phases": ["A", "B", "C"]}
            for i in range(5)
        ],
    }
    created = _create(payload)
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/cable-routes",
        json=_route_body(
            [(f"D{i}", 0) for i in range(4)],
            edges=[],
            node_count=1,
            starts={"A": 0, "B": 0, "C": 0},
        ),
    )
    assert resp.status_code == 422
    assert "4" in resp.json()["detail"]


def test_cable_routes_422_endpoint_mapping_mismatch():
    created = _create(CABLE_ROUTE_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/cable-routes"

    # 缺少 D3、多出 D9
    resp = client.post(url, json=_route_body([("D1", 0), ("D2", 0), ("D9", 0)]))
    assert resp.status_code == 422

    # 设备编号重复
    body = _route_body([("D1", 0), ("D2", 0), ("D3", 0)])
    body["device_endpoints"].append({"device_id": "D1", "endpoint": 0})
    resp = client.post(url, json=body)
    assert resp.status_code == 422


def test_cable_routes_validation():
    created = _create(CABLE_ROUTE_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/cable-routes"
    base = _route_body([("D1", 3), ("D2", 3), ("D3", 3)])

    # 自环边
    body = {**base, "edges": [{"u": 1, "v": 1, "length": 1, "capacity": 1}]}
    assert client.post(url, json=body).status_code == 422

    # 重复无向边（含反向重复）
    body = {
        **base,
        "edges": [
            {"u": 0, "v": 1, "length": 1, "capacity": 1},
            {"u": 1, "v": 0, "length": 2, "capacity": 1},
        ],
    }
    assert client.post(url, json=body).status_code == 422

    # 边长度非正整数
    body = {**base, "edges": [{"u": 0, "v": 1, "length": 0, "capacity": 1}]}
    assert client.post(url, json=body).status_code == 422

    # 容量超范围
    body = {**base, "edges": [{"u": 0, "v": 1, "length": 1, "capacity": 5}]}
    assert client.post(url, json=body).status_code == 422
    body = {**base, "edges": [{"u": 0, "v": 1, "length": 1, "capacity": -1}]}
    assert client.post(url, json=body).status_code == 422

    # 节点引用越界
    body = {**base, "edges": [{"u": 0, "v": 4, "length": 1, "capacity": 1}]}
    assert client.post(url, json=body).status_code == 422
    body = {**base, "phase_starts": {"A": 9, "B": 0, "C": 0}}
    assert client.post(url, json=body).status_code == 422
    body = {
        **base,
        "device_endpoints": [
            {"device_id": "D1", "endpoint": 3},
            {"device_id": "D2", "endpoint": 3},
            {"device_id": "D3", "endpoint": 9},
        ],
    }
    assert client.post(url, json=body).status_code == 422


def test_cable_routes_scale_limits():
    created = _create(CABLE_ROUTE_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/cable-routes"
    base = _route_body([("D1", 0), ("D2", 0), ("D3", 0)])

    # 节点数超过 6
    body = {**base, "node_count": 7}
    assert client.post(url, json=body).status_code == 422

    # 节点数为 0
    body = {**base, "node_count": 0}
    assert client.post(url, json=body).status_code == 422

    # 边数超过 8
    body = {
        **base,
        "node_count": 5,
        "edges": [
            {"u": i, "v": 4, "length": 1, "capacity": 1} for i in range(9)
        ],
    }
    assert client.post(url, json=body).status_code == 422


def test_cable_routes_does_not_modify_record():
    created = _create(CABLE_ROUTE_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    resp = client.post(
        f"/api/v1/calculations/{calc_id}/cable-routes",
        json=_route_body([("D1", 1), ("D2", 2), ("D3", 3)]),
    )
    assert resp.status_code == 200

    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    again = client.post(
        f"/api/v1/calculations/{calc_id}/cable-routes",
        json=_route_body([("D1", 1), ("D2", 2), ("D3", 3)]),
    ).json()
    assert again == resp.json()


# ---------------------------------------------------------------------------
# 检修停机排程预演
# ---------------------------------------------------------------------------

# D1->A(10)、D2->B(20)、D3->C(30)，各相独占，下限全 0 时检修不互相制约
MAINTENANCE_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A"]},
        {"id": "D2", "power": 20, "allowed_phases": ["B"]},
        {"id": "D3", "power": 30, "allowed_phases": ["C"]},
    ],
}


def _maintenance_body(devices, total_slots=6, limit=1, bounds=None):
    return {
        "devices": devices,
        "total_slots": total_slots,
        "simultaneous_limit": limit,
        "lower_bounds": bounds or {"A": 0, "B": 0, "C": 0},
    }


def test_maintenance_schedule_success():
    created = _create(MAINTENANCE_PAYLOAD)
    calc_id = created["id"]
    assert created["feasible"] is True

    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 2, "earliest_start": 0,
             "latest_start": 2},
            {"device_id": "D2", "duration": 1, "earliest_start": 0,
             "latest_start": 3},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/maintenance-schedule", json=body
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["id"] == calc_id
    assert result["total_slots"] == 6
    assert result["simultaneous_limit"] == 1
    assert result["lower_bounds"] == {"A": 0, "B": 0, "C": 0}
    assert result["feasible"] is True
    # D1 占时隙 0、1，D2 最早可放时隙 2：完工时隙 max(2, 3) = 3
    assert result["completion_slot"] == 3
    assert result["schedule"] == [
        {"device_id": "D1", "phase": "A", "power": 10,
         "start": 0, "duration": 2, "finish": 2},
        {"device_id": "D2", "phase": "B", "power": 20,
         "start": 2, "duration": 1, "finish": 3},
    ]
    # 逐时隙各相在线负载（未选设备 D3 始终在线）
    assert result["slot_loads"] == [
        {"slot": 0, "loads": {"A": 0, "B": 20, "C": 30}},
        {"slot": 1, "loads": {"A": 0, "B": 20, "C": 30}},
        {"slot": 2, "loads": {"A": 10, "B": 0, "C": 30}},
        {"slot": 3, "loads": {"A": 10, "B": 20, "C": 30}},
        {"slot": 4, "loads": {"A": 10, "B": 20, "C": 30}},
        {"slot": 5, "loads": {"A": 10, "B": 20, "C": 30}},
    ]
    assert "预演" in result["message"]


def test_maintenance_schedule_lex_tie_break():
    # 两台 A 相设备时长均 1、窗口 [0,1]，上限 1：完工恒为 2，
    # 字典序最小开始序列 D1=0、D2=1
    payload = {
        "capacities": {"A": 100, "B": 100, "C": 100},
        "devices": [
            {"id": "D1", "power": 10, "allowed_phases": ["A"]},
            {"id": "D2", "power": 20, "allowed_phases": ["A"]},
        ],
    }
    created = _create(payload)
    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
            {"device_id": "D2", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
        ],
        total_slots=2,
        limit=1,
    )
    result = client.post(
        f"/api/v1/calculations/{created['id']}/maintenance-schedule", json=body
    ).json()
    assert result["feasible"] is True
    assert result["completion_slot"] == 2
    assert [item["start"] for item in result["schedule"]] == [0, 1]
    assert result["slot_loads"][0]["loads"]["A"] == 20  # D1 停机
    assert result["slot_loads"][1]["loads"]["A"] == 10  # D2 停机


def test_maintenance_schedule_infeasible_lower_bound():
    created = _create(MAINTENANCE_PAYLOAD)
    # A 相全部在线负载为 10，下限取 10：D1 任何时隙停机都会使 A 相负载降为
    # 0 < 10 -> 无解（基础负载 10 本身不低于下限，故由单设备功率判定给出说明）
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 3}],
        bounds={"A": 10, "B": 0, "C": 0},
    )
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/maintenance-schedule", json=body
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["feasible"] is False
    assert result["completion_slot"] is None
    assert result["schedule"] == []
    assert result["slot_loads"] == []
    assert "无可行排程" in result["message"]
    assert "D1" in result["message"]


def test_maintenance_schedule_infeasible_capacity():
    created = _create(MAINTENANCE_PAYLOAD)
    # 三台均只能在时隙 0 开始，上限 2：无解
    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 1, "earliest_start": 0,
             "latest_start": 0},
            {"device_id": "D2", "duration": 1, "earliest_start": 0,
             "latest_start": 0},
            {"device_id": "D3", "duration": 1, "earliest_start": 0,
             "latest_start": 0},
        ],
        total_slots=3,
        limit=2,
    )
    result = client.post(
        f"/api/v1/calculations/{created['id']}/maintenance-schedule", json=body
    ).json()
    assert result["feasible"] is False
    assert "无可行排程" in result["message"]


def test_maintenance_schedule_404():
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 1}]
    )
    resp = client.post(
        "/api/v1/calculations/999999/maintenance-schedule", json=body
    )
    assert resp.status_code == 404


def test_maintenance_schedule_409_when_record_infeasible():
    created = _create(INFEASIBLE_UPGRADE_PAYLOAD)
    body = _maintenance_body(
        [{"device_id": "BIG", "duration": 1, "earliest_start": 0,
          "latest_start": 1}]
    )
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/maintenance-schedule", json=body
    )
    assert resp.status_code == 409


def test_maintenance_schedule_422_unknown_device():
    created = _create(MAINTENANCE_PAYLOAD)
    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
            {"device_id": "GHOST", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/maintenance-schedule", json=body
    )
    assert resp.status_code == 422
    assert "GHOST" in resp.json()["detail"]


def test_maintenance_schedule_422_validation():
    created = _create(MAINTENANCE_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/maintenance-schedule"

    # 设备编号重复
    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
            {"device_id": "D1", "duration": 1, "earliest_start": 0,
             "latest_start": 1},
        ]
    )
    assert client.post(url, json=body).status_code == 422

    # 最早开始晚于最晚开始
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 3,
          "latest_start": 2}]
    )
    assert client.post(url, json=body).status_code == 422

    # 停机区间超出总时隙窗口（最晚开始 5 + 时长 2 > 6）
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 2, "earliest_start": 0,
          "latest_start": 5}]
    )
    resp = client.post(url, json=body)
    assert resp.status_code == 422
    assert "总时隙窗口" in str(resp.json()["detail"])

    # 时长超出 1~3
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 4, "earliest_start": 0,
          "latest_start": 1}]
    )
    assert client.post(url, json=body).status_code == 422

    # 开始时隙超出 0~11
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 12}]
    )
    assert client.post(url, json=body).status_code == 422

    # 总时隙数超出 1~12
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 1}],
        total_slots=13,
    )
    assert client.post(url, json=body).status_code == 422

    # 同时检修上限超出 1~3
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 1}],
        limit=4,
    )
    assert client.post(url, json=body).status_code == 422

    # 最低在线负载为负
    body = _maintenance_body(
        [{"device_id": "D1", "duration": 1, "earliest_start": 0,
          "latest_start": 1}],
        bounds={"A": -1, "B": 0, "C": 0},
    )
    assert client.post(url, json=body).status_code == 422

    # 设备数为 0 / 超过 6
    assert client.post(url, json=_maintenance_body([])).status_code == 422
    body = _maintenance_body(
        [
            {"device_id": f"D{i}", "duration": 1, "earliest_start": 0,
             "latest_start": 1}
            for i in range(7)
        ]
    )
    assert client.post(url, json=body).status_code == 422


def test_maintenance_schedule_does_not_modify_record():
    created = _create(MAINTENANCE_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    body = _maintenance_body(
        [
            {"device_id": "D1", "duration": 2, "earliest_start": 0,
             "latest_start": 2},
            {"device_id": "D2", "duration": 1, "earliest_start": 0,
             "latest_start": 3},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/maintenance-schedule", json=body
    )
    assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/maintenance-schedule", json=body
    ).json()
    assert again == resp.json()


METER_PAYLOAD = {
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
        {"id": "D1", "power": 10, "allowed_phases": ["A"]},
        {"id": "D2", "power": 20, "allowed_phases": ["B"]},
        {"id": "D3", "power": 30, "allowed_phases": ["C"]},
    ],
}


def _meter_body(snapshots):
    return {"snapshots": snapshots}


def test_meter_calibration_success():
    created = _create(METER_PAYLOAD)
    calc_id = created["id"]
    body = _meter_body(
        [
            {"online_device_ids": ["D1", "D2", "D3"], "readings": [13, 18, 32]},
            {"online_device_ids": ["D1", "D2"], "readings": [12, 22, 0]},
            {"online_device_ids": ["D3"], "readings": [0, 0, 30]},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/meter-calibration", json=body
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["id"] == calc_id
    assert result["channel_mapping"] == {"A": 1, "B": 2, "C": 3}
    assert result["base_loads"] == {"A": 2, "B": 0, "C": 0}
    assert result["max_error"] == 2
    assert result["total_error"] == 9
    assert result["snapshots"] == [
        {
            "online_device_ids": ["D1", "D2", "D3"],
            "readings": [13, 18, 32],
            "predicted": [12, 20, 30],
            "errors": [1, 2, 2],
        },
        {
            "online_device_ids": ["D1", "D2"],
            "readings": [12, 22, 0],
            "predicted": [12, 20, 0],
            "errors": [0, 2, 0],
        },
        {
            "online_device_ids": ["D3"],
            "readings": [0, 0, 30],
            "predicted": [2, 0, 30],
            "errors": [2, 0, 0],
        },
    ]
    assert "预演" in result["message"]


def test_meter_calibration_permuted_mapping():
    payload = {
        "capacities": {"A": 100, "B": 100, "C": 100},
        "devices": [
            {"id": "D1", "power": 5, "allowed_phases": ["A"]},
            {"id": "D2", "power": 7, "allowed_phases": ["B"]},
        ],
    }
    created = _create(payload)
    # A 相在通道 3、B 相在通道 2、C 相在通道 1；底载全 0，误差为 0
    body = _meter_body(
        [
            {"online_device_ids": ["D1", "D2"], "readings": [0, 7, 5]},
            {"online_device_ids": ["D1"], "readings": [0, 0, 5]},
            {"online_device_ids": ["D2"], "readings": [0, 7, 0]},
            {"online_device_ids": [], "readings": [0, 0, 0]},
        ]
    )
    result = client.post(
        f"/api/v1/calculations/{created['id']}/meter-calibration", json=body
    ).json()
    assert result["channel_mapping"] == {"A": 3, "B": 2, "C": 1}
    assert result["base_loads"] == {"A": 0, "B": 0, "C": 0}
    assert result["max_error"] == 0
    assert result["total_error"] == 0
    assert result["snapshots"][-1]["predicted"] == [0, 0, 0]


def test_meter_calibration_404():
    body = _meter_body(
        [
            {"online_device_ids": [], "readings": [0, 0, 0]},
            {"online_device_ids": [], "readings": [0, 0, 0]},
            {"online_device_ids": [], "readings": [0, 0, 0]},
        ]
    )
    resp = client.post(
        "/api/v1/calculations/999999/meter-calibration", json=body
    )
    assert resp.status_code == 404


def test_meter_calibration_409_when_record_infeasible():
    payload = {
        "capacities": {"A": 0, "B": 0, "C": 0},
        "devices": [{"id": "BIG", "power": 50, "allowed_phases": ["A"]}],
    }
    created = _create(payload)
    assert created["feasible"] is False
    body = _meter_body(
        [
            {"online_device_ids": [], "readings": [0, 0, 0]},
            {"online_device_ids": [], "readings": [0, 0, 0]},
            {"online_device_ids": [], "readings": [0, 0, 0]},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/meter-calibration", json=body
    )
    assert resp.status_code == 409


def test_meter_calibration_422_unknown_device():
    created = _create(METER_PAYLOAD)
    body = _meter_body(
        [
            {"online_device_ids": ["D1", "UNKNOWN"], "readings": [1, 2, 3]},
            {"online_device_ids": ["D2"], "readings": [1, 2, 3]},
            {"online_device_ids": ["D3"], "readings": [1, 2, 3]},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{created['id']}/meter-calibration", json=body
    )
    assert resp.status_code == 422
    assert "未知设备编号" in resp.json()["detail"]


def test_meter_calibration_422_validation():
    created = _create(METER_PAYLOAD)
    url = f"/api/v1/calculations/{created['id']}/meter-calibration"

    # 快照少于 3 组
    resp = client.post(
        url,
        json=_meter_body(
            [
                {"online_device_ids": [], "readings": [0, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
            ]
        ),
    )
    assert resp.status_code == 422

    # 快照超过 8 组
    resp = client.post(
        url,
        json=_meter_body(
            [{"online_device_ids": [], "readings": [0, 0, 0]} for _ in range(9)]
        ),
    )
    assert resp.status_code == 422

    # 读数不是恰好 3 个
    resp = client.post(
        url,
        json=_meter_body(
            [
                {"online_device_ids": [], "readings": [0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
            ]
        ),
    )
    assert resp.status_code == 422
    resp = client.post(
        url,
        json=_meter_body(
            [
                {"online_device_ids": [], "readings": [0, 0, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
            ]
        ),
    )
    assert resp.status_code == 422

    # 读数为负
    resp = client.post(
        url,
        json=_meter_body(
            [
                {"online_device_ids": [], "readings": [-1, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
                {"online_device_ids": [], "readings": [0, 0, 0]},
            ]
        ),
    )
    assert resp.status_code == 422

    # 同一快照内在线设备编号重复
    resp = client.post(
        url,
        json=_meter_body(
            [
                {"online_device_ids": ["D1", "D1"], "readings": [0, 0, 0]},
                {"online_device_ids": ["D2"], "readings": [0, 0, 0]},
                {"online_device_ids": ["D3"], "readings": [0, 0, 0]},
            ]
        ),
    )
    assert resp.status_code == 422
    assert "唯一" in resp.text


def test_meter_calibration_does_not_modify_record():
    created = _create(METER_PAYLOAD)
    calc_id = created["id"]
    before = client.get(f"/api/v1/calculations/{calc_id}").json()
    count_before = len(client.get("/api/v1/calculations").json())

    body = _meter_body(
        [
            {"online_device_ids": ["D1", "D2", "D3"], "readings": [13, 18, 32]},
            {"online_device_ids": ["D1", "D2"], "readings": [12, 22, 0]},
            {"online_device_ids": ["D3"], "readings": [0, 0, 30]},
        ]
    )
    resp = client.post(
        f"/api/v1/calculations/{calc_id}/meter-calibration", json=body
    )
    assert resp.status_code == 200

    # 预演不改历史：原记录内容与记录总数均不变
    after = client.get(f"/api/v1/calculations/{calc_id}").json()
    assert after == before
    assert len(client.get("/api/v1/calculations").json()) == count_before

    # 再次预演结果确定且相同（幂等读操作）
    again = client.post(
        f"/api/v1/calculations/{calc_id}/meter-calibration", json=body
    ).json()
    assert again == resp.json()

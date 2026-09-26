"""FastAPI 应用入口：临时展位三相配电排布 API。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, status

from . import db
from .schemas import (
    AdditionMigrationItem,
    AssignmentItem,
    CalculationDetail,
    CalculationRequest,
    CalculationResult,
    CalculationSummary,
    CapacityUpgradeResult,
    CableCutItem,
    CableCuttingRequest,
    CableCuttingResultResponse,
    CableReelPlanItem,
    CableRouteEdgeUsageItem,
    CableRoutePathItem,
    CableRoutesRequest,
    CableRoutesResultResponse,
    DeviceAdditionPlanResult,
    DeviceAdditionRequest,
    FaultDisconnectedItem,
    FaultMigrationItem,
    Loads,
    MaintenanceScheduleItemOut,
    MaintenanceScheduleRequest,
    MaintenanceScheduleResultResponse,
    MaintenanceSlotLoad,
    MeterCalibrationRequest,
    MeterCalibrationResultResponse,
    MeterCalibrationSnapshotOut,
    MeterChannelMapping,
    Phase,
    PhaseFaultRehearsalResult,
    PowerLogAlertItem,
    PowerLogReplayRequest,
    PowerLogReplayResult,
    RobustRehearsalRequest,
    RobustRehearsalResult,
    ShiftAssignmentItem,
    ShiftPlanRequest,
    ShiftPlanResult,
    ShiftSlotPlan,
    ShiftSlots,
    StartupPlanRequest,
    StartupPlanResult,
    StartupStep,
)
from .solver import (
    AdditionExistingDevice,
    CableReel,
    CableRouteDevice,
    CableRouteEdge,
    CableSegment,
    Device,
    FaultRehearsalDevice,
    MaintenanceDevice,
    MaintenanceWindow,
    MeterCalibrationDevice,
    MeterSnapshot,
    PowerLogDevice,
    PowerLogEvent,
    RobustDevice,
    ShiftDevice,
    StartupDevice,
    solve,
    solve_cable_cutting,
    solve_cable_routes,
    solve_capacity_upgrade,
    solve_device_addition,
    solve_maintenance_schedule,
    solve_meter_calibration,
    solve_phase_fault_rehearsal,
    solve_power_log_replay,
    solve_robust,
    solve_shift_plan,
    solve_startup_plan,
)

_MESSAGE_FEASIBLE = "计算成功：已找到三相负载最大值与最小值之差最小的分配方案"
_MESSAGE_INFEASIBLE = "无可行分配：不存在所有设备均接入且各相不超容量的方案"
_MESSAGE_UPGRADE = (
    "扩容建议：已在最小化三相扩容总量、再最小化单相最大扩容量的目标下，"
    "找到使所有设备均接入的容量与分配方案"
)
_MESSAGE_ROBUST_FEASIBLE = (
    "预演成功：已找到任意功率组合下各相均不超容量、"
    "且最坏负载差最小的稳健分配方案"
)
_MESSAGE_ROBUST_INFEASIBLE = (
    "无稳健可行分配：不存在任意功率组合下各相均不超容量的接入方案"
)
_MESSAGE_STARTUP_FEASIBLE = (
    "预演成功：已找到全过程三相负载最大值与最小值之差峰值最小的安全启动顺序"
)
_MESSAGE_STARTUP_INFEASIBLE = (
    "无安全启动顺序：不存在每个启动瞬间及稳定状态各相均不超容量的启动顺序"
)
_MESSAGE_FAULT = (
    "预演成功：健康相设备保持原分配，故障相设备在允许健康相不超容量的前提下，"
    "已找到保留总功率最大、再保留设备数最多，且相位选择序列字典序最小的保供方案"
)
_MESSAGE_ADDITION_FEASIBLE = (
    "预演成功：保持原容量不变，已在原设备改相台数最少、三相负载最大值与最小值"
    "之差最小、相位序列字典序最小的目标下，找到新旧设备全部接入的分配方案"
)
_MESSAGE_ADDITION_INFEASIBLE = (
    "无可行分配：保持原容量不变时，不存在新旧设备全部接入且各相不超容量的方案"
)
_MESSAGE_SHIFT_FEASIBLE = (
    "预演成功：已在两时段总负载较大值最小、两时段三相负载差较大值最小的目标下，"
    "找到各时段各相均不超容量的错峰接入方案"
)
_MESSAGE_SHIFT_INFEASIBLE = (
    "无可行方案：不存在每台设备恰选一个允许时段与允许相位、"
    "且各时段各相负载均不超容量的错峰接入方案"
)
_MESSAGE_REPLAY_CLEAN = "复盘完成：窗口内各相负载均未超过容量"
_MESSAGE_REPLAY_ALERT = (
    "复盘完成：窗口内存在超容区间，已将连续超容段合并为告警"
)
_MESSAGE_CABLE_FEASIBLE = (
    "预演成功：已在最小化启用盘数、再最小化启用盘总长度、"
    "并最小化电缆盘编号序列字典序的目标下，找到全部电缆段均可裁出的方案"
)
_MESSAGE_CABLE_INFEASIBLE = (
    "无可裁方案：不存在每段电缆整体裁出、不拼接且各盘占用不超过盘长的方案"
)
_MESSAGE_CABLE_ROUTES_FEASIBLE = (
    "预演成功：已在最小化各路径总长度、同值时按设备编号排序比较路径节点序列"
    "字典序的目标下，找到每台设备自所属相起点到终点、各边占用均不超容量的电缆路由方案"
)
_MESSAGE_CABLE_ROUTES_INFEASIBLE = (
    "无可布路由方案：不存在每台设备均以无重复节点路径到达终点、"
    "且每条边经过电缆数不超过容量的方案"
)
_MESSAGE_MAINTENANCE_FEASIBLE = (
    "预演成功：已在最小化最后完工时隙、同值时取按设备编号排序的开始时隙序列"
    "字典序最小的目标下，找到每台选中设备各检修一次、每时隙同时检修数不超上限、"
    "各相在线负载不低于下限的排程"
)
_MESSAGE_METER_CALIBRATION = (
    "预演成功：已联合选择三通道与 A/B/C 相的对应关系及各相跨快照不变的非负整数"
    "底载，先最小化全部读数绝对误差的最大值、再最小化绝对误差总和，"
    "同值按 A/B/C 对应的通道序列、底载序列字典序裁决"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 应用启动时自动完成数据库初始化（建目录、建表）
    db.init_db()
    yield


app = FastAPI(
    title="临时展位三相配电排布 API",
    description=(
        "提交最多 12 台设备（唯一编号、正整数功率、非空可接入相位集合）"
        "及 A/B/C 各相容量，求解使三相负载最大值与最小值之差最小的分配方案；"
        "差值相同时取按设备编号排序后相位序列字典序最小的方案。"
        "每次计算的输入、分配结果与各相负载均持久化，可随时查询。"
        "另提供稳健分相预演：设备功率为正整数区间，求解任意功率组合下"
        "各相均不超容量、且最坏负载差最小的分配（仅预演，不持久化）。"
        "对已有可行分配的计算记录，还可做启动顺序预演：逐台给定启动瞬时功率，"
        "在固定相位与容量下求解全过程三相负载差峰值最小的一台接一台启动顺序"
        "（仅预演，不修改历史记录）。"
        "对已有可行分配的计算记录，亦可做单相故障保供预演：指定故障相后，"
        "健康相设备保持原分配，故障相设备迁至允许的健康相或断开，"
        "先最大化保留总功率、再最大化保留设备数（仅预演，不修改历史记录）。"
        "对已有可行分配的计算记录，还可做新增设备接入预演：提交一批新设备"
        "（沿用编号、功率与允许相位规则，新旧合计不超过 12 台且编号不重复），"
        "保持原容量不变，求解全部设备接入且各相不超容量、原设备改相台数最少、"
        "负载差最小、相位序列字典序最小的方案（仅预演，不修改历史记录）。"
        "另提供双时段错峰接入规划：提交 1~8 台设备（唯一编号、正整数功率、"
        "允许相位与允许运行时段）及两时段共用的 A/B/C 相容量，每台设备恰选"
        "一个允许时段（早/晚）与一个允许相位，各时段各相负载均不超容量，"
        "先最小化两时段总负载的较大值，再最小化两时段三相负载差的较大值"
        "（仅预演，不持久化）。"
        "对已有可行分配的计算记录，还可做运行功率日志复盘：提交起止 Unix 秒"
        "窗口与设备实际功率变更事件（最多 200 条），沿用记录的设备相位与各相"
        "容量，窗口起点所有设备功率为 0，按时刻批量生效同秒事件并计算事件间"
        "至窗口终点的三相负载，将连续存在任一相超容的区间合并为告警，返回"
        "各段告警起止时刻、各相最大超额量与全窗口各相峰值"
        "（仅复盘，不修改历史记录）。"
        "对设备不超过 8 台且已有可行分配的计算记录，还可做电缆盘裁切预演："
        "按设备编号逐台给出正整数电缆段长度（不可拼接），并提供至多 8 个"
        "编号唯一、长度为正整数的库存电缆盘及非负整数切割损耗；同盘裁出多段"
        "时占用长度为段长之和加相邻切口数乘切割损耗。依次最小化启用盘数、"
        "启用盘总长度，再取按设备编号排序的电缆盘编号序列字典序最小的方案，"
        "返回各盘裁切清单与剩余长度，无可行裁切方案时明确返回"
        "（仅预演，不修改历史记录）。"
        "对设备不超过 4 台且已有可行分配的计算记录，还可做电缆路由预演："
        "在 1~6 个节点、至多 8 条无向边（正整数长度、容量 0~4）构成的图上，"
        "给出各相起点与每台设备终点，每台设备自所属相起点走一条无重复节点"
        "路径至终点（同点用零边路径），各边经过电缆数不得超过容量；在所有"
        "方案中最小化各路径总长度，同值时按设备编号排序比较路径节点序列取"
        "字典序最小者，返回各设备路径、总长度与各边占用，无可行方案时明确"
        "返回（仅预演，不修改历史记录）。"
        "对已有可行分配的计算记录，还可做检修停机排程预演：选择记录内 1~6 台"
        "设备，逐台给出 1~3 个时隙的连续停机时长与 0~11 范围内的最早、最晚"
        "开始时隙，并给出总时隙数（1~12）、每时隙同时检修上限（1~3）及 A/B/C "
        "各相非负最低在线负载；未选设备始终在线，选中设备在半开停机区间内不计"
        "入所属相负载，先最小化最后完工时隙，同值时取按设备编号排序的开始时隙"
        "序列字典序最小者，返回检修安排与逐时隙各相在线负载，无可行排程时明确"
        "返回（仅预演，不修改历史记录）。"
        "对已有可行分配的计算记录，还可做仪表校准预演：提交 3~8 组仪表快照，"
        "每组列出当时在线的记录内设备编号与仪表三个通道的非负整数读数；设备"
        "沿用记录功率与固定相位，假设三通道与 A/B/C 相一一对应且每相存在跨"
        "快照不变的非负整数底载，联合选择通道对应与底载，先最小化所有读数与"
        "「该相在线设备功率之和 + 底载」的最大绝对误差，再最小化绝对误差"
        "总和，同值按 A/B/C 对应的通道序列、底载序列字典序裁决，返回对应"
        "关系、底载与各快照预测读数及误差（仅预演，不修改历史记录）。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """健康检查。"""
    return {"status": "ok"}


@app.post(
    "/api/v1/calculations",
    response_model=CalculationResult,
    status_code=status.HTTP_201_CREATED,
    tags=["calculations"],
)
def create_calculation(payload: CalculationRequest) -> CalculationResult:
    """创建一次排布计算：求解最优分配并保存输入、分配与各相负载。

    无可行分配时同样保存记录，返回 ``feasible=false`` 及说明信息。
    """
    devices = [
        Device(code=d.id, power=d.power, allowed=tuple(d.allowed_phases))
        for d in payload.devices
    ]
    capacities = {
        "A": payload.capacities.A,
        "B": payload.capacities.B,
        "C": payload.capacities.C,
    }
    result = solve(devices, capacities)
    calculation_id = db.insert_calculation(payload, result)
    record = db.get_calculation(calculation_id)

    assignments = (
        [
            AssignmentItem(device_id=d["device_id"], phase=d["assigned_phase"])
            for d in record["devices"]
        ]
        if result.feasible
        else []
    )
    return CalculationResult(
        id=record["id"],
        created_at=record["created_at"],
        capacities=Loads(**record["capacities"]),
        feasible=result.feasible,
        imbalance=result.imbalance,
        loads=Loads(**record["loads"]) if result.feasible else None,
        message=_MESSAGE_FEASIBLE if result.feasible else _MESSAGE_INFEASIBLE,
        assignments=assignments,
    )


@app.get(
    "/api/v1/calculations",
    response_model=list[CalculationSummary],
    tags=["calculations"],
)
def list_calculations(
    limit: int = Query(default=100, ge=1, le=500, description="返回条数上限"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> list[CalculationSummary]:
    """查询历史计算记录摘要（按创建时间倒序）。"""
    return [CalculationSummary(**item) for item in db.list_calculations(limit, offset)]


@app.get(
    "/api/v1/calculations/{calculation_id}",
    response_model=CalculationDetail,
    tags=["calculations"],
)
def get_calculation(calculation_id: int) -> CalculationDetail:
    """查询单条计算记录详情：输入设备、分配结果与各相负载。"""
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    assignments = (
        [
            AssignmentItem(device_id=d["device_id"], phase=d["assigned_phase"])
            for d in record["devices"]
        ]
        if record["feasible"]
        else []
    )
    return CalculationDetail(
        id=record["id"],
        created_at=record["created_at"],
        capacities=Loads(**record["capacities"]),
        feasible=record["feasible"],
        imbalance=record["imbalance"],
        loads=Loads(**record["loads"]) if record["feasible"] else None,
        message=_MESSAGE_FEASIBLE if record["feasible"] else _MESSAGE_INFEASIBLE,
        assignments=assignments,
        devices=record["devices"],
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/capacity-upgrade",
    response_model=CapacityUpgradeResult,
    tags=["calculations"],
)
def capacity_upgrade(calculation_id: int) -> CapacityUpgradeResult:
    """针对无可行分配的计算记录，给出最小扩容建议。

    保持设备功率与允许相位不变，计算各相需要增加的非负整数容量及对应分配，
    使所有设备接入；依次最小化三相扩容总量与单相最大扩容量，仍相同时取
    按设备编号排序的相位序列字典序最小的方案。仅返回建议，原计算记录不变。

    记录不存在返回 404；原记录已有可行分配返回 409。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录已有可行分配，无需扩容：id={calculation_id}",
        )

    devices = [
        Device(
            code=d["device_id"],
            power=d["power"],
            allowed=tuple(d["allowed_phases"]),
        )
        for d in record["devices"]
    ]
    capacities = {
        "A": record["capacities"]["A"],
        "B": record["capacities"]["B"],
        "C": record["capacities"]["C"],
    }
    upgrade = solve_capacity_upgrade(devices, capacities)

    assignments = [
        AssignmentItem(device_id=code, phase=upgrade.assignment[code])
        for code in sorted(upgrade.assignment)
    ]
    return CapacityUpgradeResult(
        id=record["id"],
        created_at=record["created_at"],
        original_capacities=Loads(**upgrade.original_capacities),
        capacity_upgrades=Loads(**upgrade.upgrades),
        suggested_capacities=Loads(**upgrade.suggested_capacities),
        total_upgrade=upgrade.total_upgrade,
        max_upgrade=upgrade.max_upgrade,
        assignments=assignments,
        loads=Loads(**upgrade.loads),
        message=_MESSAGE_UPGRADE,
    )


@app.post(
    "/api/v1/robust-rehearsals",
    response_model=RobustRehearsalResult,
    tags=["rehearsals"],
)
def robust_rehearsal(payload: RobustRehearsalRequest) -> RobustRehearsalResult:
    """稳健分相预演：设备功率为正整数区间，求解稳健最优分配。

    每台设备功率可在 [min_power, max_power] 内独立变化。寻找每台设备接入
    一个允许相位、且任意功率组合下各相均不超容量的分配；在稳健可行方案中
    最小化任意功率组合可能产生的三相最大负载与最小负载之差，同值时取
    按设备编号排序的相位序列字典序最小者。

    仅做预演，不写入历史计算记录；无稳健可行方案时返回 ``feasible=false``。
    """
    devices = [
        RobustDevice(
            code=d.id,
            min_power=d.min_power,
            max_power=d.max_power,
            allowed=tuple(d.allowed_phases),
        )
        for d in payload.devices
    ]
    capacities = {
        "A": payload.capacities.A,
        "B": payload.capacities.B,
        "C": payload.capacities.C,
    }
    result = solve_robust(devices, capacities)

    assignments = (
        [
            AssignmentItem(device_id=code, phase=result.assignment[code])
            for code in sorted(result.assignment)
        ]
        if result.feasible
        else []
    )
    return RobustRehearsalResult(
        capacities=Loads(**capacities),
        feasible=result.feasible,
        worst_imbalance=result.worst_imbalance,
        load_lower_bounds=Loads(**result.load_lower) if result.feasible else None,
        load_upper_bounds=Loads(**result.load_upper) if result.feasible else None,
        assignments=assignments,
        message=(
            _MESSAGE_ROBUST_FEASIBLE if result.feasible else _MESSAGE_ROBUST_INFEASIBLE
        ),
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/startup-plan",
    response_model=StartupPlanResult,
    tags=["calculations"],
)
def startup_plan(calculation_id: int, payload: StartupPlanRequest) -> StartupPlanResult:
    """启动顺序预演：为已有可行分配的计算记录规划一台接一台的安全启动顺序。

    沿用记录中的固定相位与容量，请求逐台给出启动瞬时功率（须为不低于额定
    功率的正整数，且设备编号与记录完全一致）。设备一次启动一台：启动瞬间
    该设备按启动功率计，完成后按额定功率持续运行；每个启动瞬间及稳定状态
    各相均不得超容量。在所有安全启动顺序中，最小化全过程三相负载最大值与
    最小值之差的峰值；同峰值时取设备编号序列字典序最小者。返回启动顺序、
    逐步瞬时与稳定负载及峰值；无安全顺序时返回 ``feasible=false``。
    仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；启动功率低于额定功率
    或设备编号与记录不一致返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法规划启动顺序：id={calculation_id}",
        )

    record_devices = {d["device_id"]: d for d in record["devices"]}
    request_powers = {
        item.device_id: item.startup_power for item in payload.startup_powers
    }
    if set(request_powers) != set(record_devices):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="设备编号须与计算记录完全一致（不多不少）",
        )
    for device_id, startup_power in request_powers.items():
        rated = record_devices[device_id]["power"]
        if startup_power < rated:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"启动瞬时功率不得低于额定功率："
                    f"设备 {device_id} 额定功率为 {rated}"
                ),
            )

    devices = [
        StartupDevice(
            code=d["device_id"],
            phase=d["assigned_phase"],
            rated_power=d["power"],
            startup_power=request_powers[d["device_id"]],
        )
        for d in record["devices"]
    ]
    result = solve_startup_plan(devices, record["capacities"])

    steps = (
        [
            StartupStep(
                device_id=step.code,
                phase=step.phase,
                rated_power=step.rated_power,
                startup_power=step.startup_power,
                transient_loads=Loads(**step.transient_loads),
                transient_imbalance=step.transient_imbalance,
                steady_loads=Loads(**step.steady_loads),
                steady_imbalance=step.steady_imbalance,
            )
            for step in result.steps
        ]
        if result.feasible
        else []
    )
    return StartupPlanResult(
        id=record["id"],
        created_at=record["created_at"],
        capacities=Loads(**record["capacities"]),
        feasible=result.feasible,
        peak_imbalance=result.peak_imbalance,
        startup_order=list(result.order) if result.feasible else [],
        steps=steps,
        message=(
            _MESSAGE_STARTUP_FEASIBLE if result.feasible else _MESSAGE_STARTUP_INFEASIBLE
        ),
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/phase-fault-rehearsal",
    response_model=PhaseFaultRehearsalResult,
    tags=["calculations"],
)
def phase_fault_rehearsal(
    calculation_id: int, fault_phase: Phase = Query(..., description="故障相（A/B/C）")
) -> PhaseFaultRehearsalResult:
    """单相故障保供预演：指定故障相，规划故障相设备的迁移 / 断开方案。

    健康相设备保持原分配不动；故障相设备只能迁至其允许的健康相（迁入后该相
    不得超容量）或断开，故障相最终负载为零。在所有方案中先最大化保留设备的
    总功率，再最大化保留设备数；仍同值时，按故障相设备编号排序，取相位选择
    序列字典序最小者（A＜B＜C＜断开）。返回最终各相负载、迁移分配、断开
    设备及保留功率。仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；故障相取值非法返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法进行故障保供预演：id={calculation_id}",
        )

    devices = [
        FaultRehearsalDevice(
            code=d["device_id"],
            power=d["power"],
            allowed=tuple(d["allowed_phases"]),
            original_phase=d["assigned_phase"],
        )
        for d in record["devices"]
    ]
    result = solve_phase_fault_rehearsal(
        devices, record["capacities"], fault_phase=fault_phase
    )

    migrations = [
        FaultMigrationItem(
            device_id=item.code,
            power=item.power,
            from_phase=item.from_phase,
            to_phase=item.to_phase,
        )
        for item in result.migrations
    ]
    disconnected = [
        FaultDisconnectedItem(
            device_id=item.code, power=item.power, phase=item.phase
        )
        for item in result.disconnected
    ]
    return PhaseFaultRehearsalResult(
        id=record["id"],
        created_at=record["created_at"],
        fault_phase=result.fault_phase,
        capacities=Loads(**result.capacities),
        original_loads=Loads(**result.original_loads),
        loads=Loads(**result.loads),
        migrations=migrations,
        disconnected=disconnected,
        retained_power=result.retained_power,
        retained_count=result.retained_count,
        disconnected_power=result.disconnected_power,
        disconnected_count=result.disconnected_count,
        message=_MESSAGE_FAULT,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/device-addition-plan",
    response_model=DeviceAdditionPlanResult,
    tags=["calculations"],
)
def device_addition_plan(
    calculation_id: int, payload: DeviceAdditionRequest
) -> DeviceAdditionPlanResult:
    """新增设备接入预演：为已有可行分配的记录规划一批新设备的接入方案。

    沿用记录中的原容量与各设备的编号、功率、允许相位；新设备遵循同样的
    编号 / 功率 / 允许相位规则，编号不得与记录中已有设备重复，且新旧设备
    总数不得超过 12 台。保持原容量不变，所有设备（新 + 旧）均须接入且各相
    不超容量；原设备可改相（迁移），也可保持原相位。目标依次为：原设备
    改相台数最少 → 三相负载最大值与最小值之差最小 → 按全部设备编号排序的
    相位序列字典序最小。返回新旧设备分配、原设备迁移清单与各相负载；
    无可行方案时返回 ``feasible=false``。仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；新设备编号与记录重复
    或新旧设备总数超过 12 台返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法规划新增设备接入：id={calculation_id}",
        )

    record_ids = {d["device_id"] for d in record["devices"]}
    new_ids = {d.id for d in payload.devices}
    overlap = sorted(record_ids & new_ids)
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"新设备编号不得与记录中已有设备重复：{', '.join(overlap)}",
        )
    if len(record_ids) + len(new_ids) > 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"新旧设备总数不得超过 12 台："
                f"记录已有 {len(record_ids)} 台，新增 {len(new_ids)} 台"
            ),
        )

    existing = [
        AdditionExistingDevice(
            code=d["device_id"],
            power=d["power"],
            allowed=tuple(d["allowed_phases"]),
            original_phase=d["assigned_phase"],
        )
        for d in record["devices"]
    ]
    new_devices = [
        Device(code=d.id, power=d.power, allowed=tuple(d.allowed_phases))
        for d in payload.devices
    ]
    result = solve_device_addition(existing, new_devices, record["capacities"])

    existing_assignments = (
        [
            AssignmentItem(
                device_id=d["device_id"], phase=result.assignment[d["device_id"]]
            )
            for d in record["devices"]
        ]
        if result.feasible
        else []
    )
    new_assignments = (
        [
            AssignmentItem(device_id=code, phase=result.assignment[code])
            for code in sorted(new_ids)
        ]
        if result.feasible
        else []
    )
    migrations = (
        [
            AdditionMigrationItem(
                device_id=item.code,
                power=item.power,
                from_phase=item.from_phase,
                to_phase=item.to_phase,
            )
            for item in result.migrations
        ]
        if result.feasible
        else []
    )
    return DeviceAdditionPlanResult(
        id=record["id"],
        created_at=record["created_at"],
        capacities=Loads(**record["capacities"]),
        feasible=result.feasible,
        imbalance=result.imbalance,
        loads=Loads(**result.loads) if result.feasible else None,
        migrated_count=result.migrated_count,
        existing_assignments=existing_assignments,
        new_assignments=new_assignments,
        migrations=migrations,
        message=(
            _MESSAGE_ADDITION_FEASIBLE
            if result.feasible
            else _MESSAGE_ADDITION_INFEASIBLE
        ),
    )


def _shift_slot_plan(loads: dict[str, int]) -> ShiftSlotPlan:
    """由「相位 -> 负载」构造单时段负载情况（含总负载与负载差）。"""
    return ShiftSlotPlan(
        loads=Loads(**loads),
        total_load=sum(loads.values()),
        imbalance=max(loads.values()) - min(loads.values()),
    )


@app.post(
    "/api/v1/shift-plans",
    response_model=ShiftPlanResult,
    tags=["rehearsals"],
)
def create_shift_plan(payload: ShiftPlanRequest) -> ShiftPlanResult:
    """双时段错峰接入规划：为 1~8 台设备安排运行时段（早/晚）与接入相位。

    每台设备恰选一个允许时段（morning 早 / evening 晚）与一个允许相位；
    两时段共用请求中的 A/B/C 相容量，各时段各相负载均不得超容量。目标
    依次为：两时段总负载（三相之和）的较大值最小 → 两时段三相负载差
    （最大值与最小值之差）的较大值最小 → 按设备编号排序的 (时段, 相位)
    序列字典序最小（早＜晚，A＜B＜C）。返回设备安排、各时段三相负载及
    峰值指标；无可行方案时返回 ``feasible=false``。
    仅做预演，不写入历史计算记录。
    """
    devices = [
        ShiftDevice(
            code=d.id,
            power=d.power,
            allowed_phases=tuple(d.allowed_phases),
            allowed_slots=tuple(d.allowed_slots),
        )
        for d in payload.devices
    ]
    capacities = {
        "A": payload.capacities.A,
        "B": payload.capacities.B,
        "C": payload.capacities.C,
    }
    result = solve_shift_plan(devices, capacities)

    assignments = (
        [
            ShiftAssignmentItem(
                device_id=code,
                slot=result.assignment[code][0],
                phase=result.assignment[code][1],
            )
            for code in sorted(result.assignment)
        ]
        if result.feasible
        else []
    )
    slots = (
        ShiftSlots(
            morning=_shift_slot_plan(result.slot_loads["morning"]),
            evening=_shift_slot_plan(result.slot_loads["evening"]),
        )
        if result.feasible
        else None
    )
    return ShiftPlanResult(
        capacities=Loads(**capacities),
        feasible=result.feasible,
        peak_total_load=result.peak_total_load,
        peak_imbalance=result.peak_imbalance,
        slots=slots,
        assignments=assignments,
        message=_MESSAGE_SHIFT_FEASIBLE if result.feasible else _MESSAGE_SHIFT_INFEASIBLE,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/power-log-replay",
    response_model=PowerLogReplayResult,
    tags=["calculations"],
)
def power_log_replay(
    calculation_id: int, payload: PowerLogReplayRequest
) -> PowerLogReplayResult:
    """运行功率日志复盘：对已有可行分配的记录回放窗口内的功率变更事件。

    沿用记录中的设备相位与各相容量。窗口起点所有设备功率为 0；同一时刻的
    事件批量生效，计算事件之间至窗口终点的三相负载，将连续存在任一相超容
    的区间合并为告警。返回每段告警的起止时刻与各相最大超额量，以及全窗口
    各相峰值负载。仅做复盘，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；窗口起点不早于终点、
    事件时刻落在左闭右开窗口之外、同一设备同一时刻重复、事件包含未知设备
    编号或功率为负均返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法复盘功率日志：id={calculation_id}",
        )

    record_ids = {d["device_id"] for d in record["devices"]}
    unknown = sorted({e.device_id for e in payload.events} - record_ids)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"事件包含未知设备编号：{', '.join(unknown)}",
        )

    devices = [
        PowerLogDevice(code=d["device_id"], phase=d["assigned_phase"])
        for d in record["devices"]
    ]
    events = [
        PowerLogEvent(code=e.device_id, timestamp=e.timestamp, power=e.power)
        for e in payload.events
    ]
    result = solve_power_log_replay(
        devices,
        record["capacities"],
        payload.window_start,
        payload.window_end,
        events,
    )

    alerts = [
        PowerLogAlertItem(
            start=alert.start,
            end=alert.end,
            max_overload=Loads(**alert.max_overload),
        )
        for alert in result.alerts
    ]
    return PowerLogReplayResult(
        id=record["id"],
        created_at=record["created_at"],
        capacities=Loads(**record["capacities"]),
        window_start=payload.window_start,
        window_end=payload.window_end,
        alerts=alerts,
        peak_loads=Loads(**result.peak_loads),
        message=_MESSAGE_REPLAY_ALERT if alerts else _MESSAGE_REPLAY_CLEAN,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/cable-cutting-plan",
    response_model=CableCuttingResultResponse,
    tags=["calculations"],
)
def cable_cutting_plan(
    calculation_id: int, payload: CableCuttingRequest
) -> CableCuttingResultResponse:
    """电缆盘裁切预演：为设备不超过 8 台且已有可行分配的记录规划整段裁切方案。

    请求按设备编号逐台给出正整数电缆段长度（每段电缆不可拼接），并提供至多
    8 个编号唯一、长度为正整数的库存电缆盘及非负整数切割损耗；设备编号集合
    须与计算记录完全一致。同一盘裁出 k 段时占用长度为「段长之和 +
    (k-1)·切割损耗」，不得超过盘长。在所有方案中依次：1) 最小化启用盘数；
    2) 最小化启用盘总长度；3) 取按设备编号排序的电缆盘编号序列字典序最小者。
    返回各启用盘的裁切清单（按设备编号排序）、占用与剩余长度；不存在可行
    裁切方案时返回 ``feasible=false``。仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配或设备超过 8 台返回 409；
    设备编号与记录不一致、字段不满足规则返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法进行电缆盘裁切预演：id={calculation_id}",
        )
    record_ids = {d["device_id"] for d in record["devices"]}
    if len(record_ids) > 8:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"计算记录设备数为 {len(record_ids)} 台，超过 8 台，"
                "无法进行电缆盘裁切预演"
            ),
        )
    segment_map = {item.device_id: item.length for item in payload.segments}
    if set(segment_map) != record_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="电缆段的设备编号须与计算记录完全一致（不多不少）",
        )

    segments = [
        CableSegment(code=device_id, length=length)
        for device_id, length in segment_map.items()
    ]
    reels = [
        CableReel(code=reel.id, length=reel.length) for reel in payload.reels
    ]
    result = solve_cable_cutting(segments, reels, cut_loss=payload.cut_loss)

    if not result.feasible:
        return CableCuttingResultResponse(
            id=record["id"],
            created_at=record["created_at"],
            cut_loss=payload.cut_loss,
            feasible=False,
            reel_count=None,
            reel_total_length=None,
            reel_sequence=[],
            reel_plans=[],
            message=_MESSAGE_CABLE_INFEASIBLE,
        )

    ordered_device_ids = sorted(segment_map)
    reel_sequence = [result.assignment[code] for code in ordered_device_ids]
    reel_plans = [
        CableReelPlanItem(
            reel_id=plan.reel_code,
            reel_length=plan.reel_length,
            cuts=[
                CableCutItem(device_id=cut.device_code, length=cut.length)
                for cut in plan.cuts
            ],
            occupied=plan.occupied,
            remaining=plan.remaining,
        )
        for plan in result.reel_plans
    ]
    return CableCuttingResultResponse(
        id=record["id"],
        created_at=record["created_at"],
        cut_loss=payload.cut_loss,
        feasible=True,
        reel_count=result.reel_count,
        reel_total_length=result.reel_total_length,
        reel_sequence=reel_sequence,
        reel_plans=reel_plans,
        message=_MESSAGE_CABLE_FEASIBLE,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/cable-routes",
    response_model=CableRoutesResultResponse,
    tags=["calculations"],
)
def cable_routes(
    calculation_id: int, payload: CableRoutesRequest
) -> CableRoutesResultResponse:
    """电缆路由预演：基于已有可行分相记录，在给定图上为各设备布设电缆。

    请求给出 1~6 个节点（编号 0 ~ n-1）、至多 8 条无向边（无自环、无重复，
    长度为正整数，可容纳电缆数 0~4）、A/B/C 各相起点与每台设备的终点节点。
    设备编号集合须与计算记录完全一致（不多不少、不重复）。每台设备沿用记录
    中的分相，从所属相起点走一条无重复节点的路径至其终点，起终点相同使用
    零边路径；每条边经过的电缆数不得超过该边容量。在所有方案中依次：
    1) 最小化各路径长度之和（总长度）；2) 同值时按设备编号排序，依次比较
    各路径节点序列取字典序最小者。返回各设备路径、总长度与各边占用；
    不存在可行方案时返回 ``feasible=false``、空路径与 ``null`` 总长度。
    仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；记录设备超过 4 台、
    节点 / 边超规模、设备编号与记录不一致或字段不满足规则返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法进行电缆路由预演：id={calculation_id}",
        )
    record_ids = {d["device_id"] for d in record["devices"]}
    if len(record_ids) > 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"计算记录设备数为 {len(record_ids)} 台，超过电缆路由预演支持的 4 台上限"
            ),
        )
    endpoint_map = {item.device_id: item.endpoint for item in payload.device_endpoints}
    if set(endpoint_map) != record_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="设备终点映射须完整覆盖计算记录中的设备（不多不少、不重复）",
        )

    devices = [
        CableRouteDevice(
            code=d["device_id"],
            phase=d["assigned_phase"],
            endpoint=endpoint_map[d["device_id"]],
        )
        for d in record["devices"]
    ]
    edges = [
        CableRouteEdge(
            u=edge.u,
            v=edge.v,
            length=edge.length,
            capacity=edge.capacity,
        )
        for edge in payload.edges
    ]
    phase_starts = {
        "A": payload.phase_starts.A,
        "B": payload.phase_starts.B,
        "C": payload.phase_starts.C,
    }
    result = solve_cable_routes(
        devices, edges, phase_starts=phase_starts, node_count=payload.node_count
    )

    if not result.feasible:
        edge_usage = [
            CableRouteEdgeUsageItem(
                u=min(edge.u, edge.v),
                v=max(edge.u, edge.v),
                length=edge.length,
                capacity=edge.capacity,
                occupied=0,
            )
            for edge in sorted(
                payload.edges, key=lambda e: (min(e.u, e.v), max(e.u, e.v))
            )
        ]
        return CableRoutesResultResponse(
            id=record["id"],
            created_at=record["created_at"],
            node_count=payload.node_count,
            feasible=False,
            total_length=None,
            paths=[],
            edge_usage=edge_usage,
            message=_MESSAGE_CABLE_ROUTES_INFEASIBLE,
        )

    paths = [
        CableRoutePathItem(
            device_id=item.code,
            phase=item.phase,
            endpoint=item.endpoint,
            nodes=list(item.nodes),
            length=item.length,
        )
        for item in result.paths
    ]
    edge_usage = [
        CableRouteEdgeUsageItem(
            u=item.u,
            v=item.v,
            length=item.length,
            capacity=item.capacity,
            occupied=item.occupied,
        )
        for item in result.edge_usage
    ]
    return CableRoutesResultResponse(
        id=record["id"],
        created_at=record["created_at"],
        node_count=payload.node_count,
        feasible=True,
        total_length=result.total_length,
        paths=paths,
        edge_usage=edge_usage,
        message=_MESSAGE_CABLE_ROUTES_FEASIBLE,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/maintenance-schedule",
    response_model=MaintenanceScheduleResultResponse,
    tags=["calculations"],
)
def maintenance_schedule(
    calculation_id: int, payload: MaintenanceScheduleRequest
) -> MaintenanceScheduleResultResponse:
    """检修停机排程预演：为记录内 1~6 台设备各安排一次连续停机检修。

    请求逐台给出参与检修设备的连续停机时长（1~3 个时隙）与最早 / 最晚开始
    时隙（0~11，最早不得晚于最晚），并给出总时隙数（1~12，时隙编号
    0~total_slots-1）、每时隙同时检修设备数上限（1~3）及 A/B/C 各相非负
    最低在线负载。检修设备编号不得重复且均须存在于记录中；停机为半开区间
    ``[start, start+duration)``，最晚开始加时长不得超过总时隙数。未选设备
    始终在线；选中设备在停机区间内不计入所属相负载，其余时隙按记录功率运行。

    在所有方案中依次：1) 最小化最后完工时隙 ``max(start+duration)``；
    2) 同值时取按设备编号排序的开始时隙序列字典序最小者。返回各设备检修
    安排与逐时隙各相在线负载；不存在可行排程时返回 ``feasible=false`` 及
    无解说明。仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；检修设备编号未知或重复、
    各字段超出取值范围、最早开始晚于最晚开始或停机区间超出总时隙窗口返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法进行检修停机排程预演：id={calculation_id}",
        )

    record_devices = {d["device_id"]: d for d in record["devices"]}
    selected_ids = [item.device_id for item in payload.devices]
    unknown = sorted(set(selected_ids) - set(record_devices))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"检修设备编号须存在于计算记录中：{', '.join(unknown)}",
        )

    devices = [
        MaintenanceDevice(
            code=d["device_id"],
            phase=d["assigned_phase"],
            power=d["power"],
        )
        for d in record["devices"]
    ]
    windows = [
        MaintenanceWindow(
            code=item.device_id,
            duration=item.duration,
            earliest_start=item.earliest_start,
            latest_start=item.latest_start,
        )
        for item in payload.devices
    ]
    lower_bounds = {
        "A": payload.lower_bounds.A,
        "B": payload.lower_bounds.B,
        "C": payload.lower_bounds.C,
    }
    result = solve_maintenance_schedule(
        devices,
        windows,
        total_slots=payload.total_slots,
        simultaneous_limit=payload.simultaneous_limit,
        lower_bounds=lower_bounds,
    )

    if not result.feasible:
        return MaintenanceScheduleResultResponse(
            id=record["id"],
            created_at=record["created_at"],
            total_slots=payload.total_slots,
            simultaneous_limit=payload.simultaneous_limit,
            lower_bounds=Loads(**lower_bounds),
            feasible=False,
            completion_slot=None,
            schedule=[],
            slot_loads=[],
            message=result.reason,
        )

    schedule = [
        MaintenanceScheduleItemOut(
            device_id=item.code,
            phase=item.phase,
            power=item.power,
            start=item.start,
            duration=item.duration,
            finish=item.finish,
        )
        for item in result.items
    ]
    slot_loads = [
        MaintenanceSlotLoad(slot=slot, loads=Loads(**loads))
        for slot, loads in enumerate(result.slot_loads)
    ]
    return MaintenanceScheduleResultResponse(
        id=record["id"],
        created_at=record["created_at"],
        total_slots=payload.total_slots,
        simultaneous_limit=payload.simultaneous_limit,
        lower_bounds=Loads(**lower_bounds),
        feasible=True,
        completion_slot=result.completion_slot,
        schedule=schedule,
        slot_loads=slot_loads,
        message=_MESSAGE_MAINTENANCE_FEASIBLE,
    )


@app.post(
    "/api/v1/calculations/{calculation_id}/meter-calibration",
    response_model=MeterCalibrationResultResponse,
    tags=["calculations"],
)
def meter_calibration(
    calculation_id: int, payload: MeterCalibrationRequest
) -> MeterCalibrationResultResponse:
    """仪表校准预演：用多组在线快照标定仪表通道与 A/B/C 相的对应及各相底载。

    请求提交 3~8 组仪表快照，每组给出当时在线的记录内设备编号（均须存在于
    计算记录中，组内不重复，可为空集）与仪表三个通道的非负整数读数（按
    通道 1/2/3 排列）。设备沿用记录中的功率与固定相位。假设三通道与
    A/B/C 相一一对应，且每相有跨快照不变的非负整数底载：若某通道对应相 p，
    则其预测读数为「该相在线设备功率之和 + 该相底载」。联合选择通道对应
    （3! 种）与三相底载，目标依次为：1) 最小化所有快照、所有通道读数绝对
    误差的最大值；2) 再最小化绝对误差总和；3) 同值时先按 A/B/C 对应的
    通道序列字典序、再按 A/B/C 底载序列字典序裁决。返回对应关系、底载及
    各快照预测读数与误差。仅做预演，不修改历史计算记录。

    记录不存在返回 404；原记录无可行分配返回 409；快照数不在 3~8、在线
    设备编号未知或组内重复、读数不是三个非负整数均返回 422。
    """
    record = db.get_calculation(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"计算记录不存在：id={calculation_id}",
        )
    if not record["feasible"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"计算记录无可行分配，无法进行仪表校准预演：id={calculation_id}",
        )

    record_ids = {d["device_id"] for d in record["devices"]}
    for index, snapshot in enumerate(payload.snapshots):
        unknown = sorted(set(snapshot.online_device_ids) - record_ids)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"第 {index + 1} 组快照包含未知设备编号：{', '.join(unknown)}"
                ),
            )

    devices = [
        MeterCalibrationDevice(
            code=d["device_id"],
            phase=d["assigned_phase"],
            power=d["power"],
        )
        for d in record["devices"]
    ]
    snapshots = [
        MeterSnapshot(
            online=tuple(snapshot.online_device_ids),
            readings=tuple(snapshot.readings),
        )
        for snapshot in payload.snapshots
    ]
    result = solve_meter_calibration(devices, snapshots)

    snapshot_results = [
        MeterCalibrationSnapshotOut(
            online_device_ids=list(item.online),
            observed_readings=list(item.observed_readings),
            phase_power=Loads(**item.phase_power),
            predicted_readings=list(item.predicted_readings),
            errors=list(item.errors),
        )
        for item in result.snapshots
    ]
    return MeterCalibrationResultResponse(
        id=record["id"],
        created_at=record["created_at"],
        channel_mapping=MeterChannelMapping(**result.channel_of_phase),
        base_loads=Loads(**result.base_loads),
        snapshots=snapshot_results,
        max_error=result.max_error,
        total_error=result.total_error,
        message=_MESSAGE_METER_CALIBRATION,
    )

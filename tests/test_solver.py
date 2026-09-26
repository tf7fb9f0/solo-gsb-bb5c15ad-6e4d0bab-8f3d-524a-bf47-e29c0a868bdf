"""求解器单元测试（仅依赖标准库，可直接运行：python3 -m unittest tests.test_solver）。"""

import itertools
import random
import unittest

from app.solver import (
    SLOTS,
    AdditionExistingDevice,
    CableReel,
    CableRouteDevice,
    CableRouteEdge,
    CableSegment,
    Device,
    FaultRehearsalDevice,
    MaintenanceDevice,
    MaintenanceWindow,
    MeterDevice,
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

PHASES = ("A", "B", "C")


def brute_force(devices, capacities):
    """朴素全枚举参照实现：返回 (最优差值, 字典序最小相位序列) 或 None。"""
    ordered = sorted(devices, key=lambda d: d.code)
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    best = None
    for combo in itertools.product(*allowed):
        loads = {p: 0 for p in PHASES}
        ok = True
        for device, phase in zip(ordered, combo):
            loads[phase] += device.power
            if loads[phase] > capacities[phase]:
                ok = False
                break
        if not ok:
            continue
        imbalance = max(loads.values()) - min(loads.values())
        if best is None or imbalance < best[0]:
            best = (imbalance, combo, dict(loads))
    return best


class SolveBasicTest(unittest.TestCase):
    def test_balanced_assignment(self):
        devices = [
            Device("D1", 10, ("A", "B", "C")),
            Device("D2", 20, ("A", "B", "C")),
            Device("D3", 30, ("A", "B", "C")),
        ]
        result = solve(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        # 10/20/30 无法完全均分（无子集和为 20 的拆分），最优差值为 20
        self.assertEqual(result.imbalance, 20)
        self.assertEqual(result.loads, {"A": 10, "B": 20, "C": 30})
        # 字典序最小：D1->A, D2->B, D3->C
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B", "D3": "C"})

    def test_perfect_balance(self):
        devices = [Device(f"D{i}", 10, PHASES) for i in range(1, 4)]
        result = solve(devices, {"A": 10, "B": 10, "C": 10})
        self.assertTrue(result.feasible)
        self.assertEqual(result.imbalance, 0)
        self.assertEqual(result.loads, {"A": 10, "B": 10, "C": 10})

    def test_restricted_phases(self):
        devices = [
            Device("X", 5, ("A",)),
            Device("Y", 7, ("B", "C")),
            Device("Z", 6, ("A", "C")),
        ]
        result = solve(devices, {"A": 20, "B": 20, "C": 20})
        self.assertTrue(result.feasible)
        self.assertEqual(result.assignment["X"], "A")
        self.assertEqual(result.loads["A"] + result.loads["B"] + result.loads["C"], 18)

    def test_infeasible_capacity(self):
        devices = [Device("D1", 50, ("A",)), Device("D2", 60, ("A",))]
        result = solve(devices, {"A": 100, "B": 0, "C": 0})
        self.assertFalse(result.feasible)
        self.assertIsNone(result.assignment)
        self.assertIsNone(result.loads)
        self.assertIsNone(result.imbalance)

    def test_infeasible_single_device_over_capacity(self):
        devices = [Device("BIG", 101, PHASES)]
        result = solve(devices, {"A": 100, "B": 100, "C": 100})
        self.assertFalse(result.feasible)

    def test_lexicographic_tie_break(self):
        # 两台同功率设备：多种最优解，应取编号排序后相位序列字典序最小者
        devices = [Device("B2", 10, PHASES), Device("A1", 10, PHASES)]
        result = solve(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.imbalance, 10)
        # 按编号排序为 A1, B2；字典序最小序列为 (A, B)
        self.assertEqual(result.assignment, {"A1": "A", "B2": "B"})

    def test_device_ids_sorted_as_strings(self):
        devices = [
            Device("DEV-10", 4, PHASES),
            Device("DEV-2", 4, PHASES),
            Device("DEV-1", 4, PHASES),
        ]
        result = solve(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.imbalance, 0)
        # 字符串排序 DEV-1 < DEV-10 < DEV-2，字典序最小序列 (A, B, C)
        self.assertEqual(
            result.assignment, {"DEV-1": "A", "DEV-10": "B", "DEV-2": "C"}
        )

    def test_capacity_forces_imbalance(self):
        devices = [Device("D1", 8, PHASES), Device("D2", 8, PHASES)]
        result = solve(devices, {"A": 8, "B": 8, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.loads, {"A": 8, "B": 8, "C": 0})
        self.assertEqual(result.imbalance, 8)


class SolveFuzzTest(unittest.TestCase):
    """与朴素全枚举参照实现做随机对拍。"""

    def test_against_brute_force(self):
        rng = random.Random(20260924)
        for case in range(300):
            n = rng.randint(1, 7)
            devices = []
            for i in range(n):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                devices.append(Device(f"DEV-{i}", rng.randint(1, 20), allowed))
            capacities = {p: rng.randint(0, 60) for p in PHASES}

            expected = brute_force(devices, capacities)
            result = solve(devices, capacities)

            if expected is None:
                self.assertFalse(result.feasible, f"case {case}: 应为无可行解")
                continue

            self.assertTrue(result.feasible, f"case {case}: 应有可行解")
            exp_imbalance, exp_combo, exp_loads = expected
            self.assertEqual(result.imbalance, exp_imbalance, f"case {case}: 差值不符")
            self.assertEqual(result.loads, exp_loads, f"case {case}: 负载不符")
            ordered = sorted(devices, key=lambda d: d.code)
            actual_combo = tuple(result.assignment[d.code] for d in ordered)
            self.assertEqual(actual_combo, exp_combo, f"case {case}: 字典序最小方案不符")

    def test_twelve_devices_performance(self):
        # 12 台设备、全相位可接、大容量：最恶劣情形，应在可接受时间内完成
        devices = [Device(f"D{i:02d}", 2**i, PHASES) for i in range(12)]
        result = solve(devices, {"A": 10**6, "B": 10**6, "C": 10**6})
        self.assertTrue(result.feasible)
        expected = brute_force(devices, {"A": 10**6, "B": 10**6, "C": 10**6})
        self.assertEqual(result.imbalance, expected[0])
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), expected[1]
        )


def brute_force_upgrade(devices, capacities):
    """扩容问题的朴素全枚举：返回 (总扩容, 单相最大扩容, 相位序列, 负载, 扩容量)。"""
    ordered = sorted(devices, key=lambda d: d.code)
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    best = None
    for combo in itertools.product(*allowed):
        loads = {p: 0 for p in PHASES}
        for device, phase in zip(ordered, combo):
            loads[phase] += device.power
        upgrades = {p: max(0, loads[p] - capacities[p]) for p in PHASES}
        key = (
            sum(upgrades.values()),
            max(upgrades.values()),
            combo,
        )
        if best is None or key < best[0]:
            best = (key, dict(loads), dict(upgrades))
    return best


class CapacityUpgradeTest(unittest.TestCase):
    def test_single_oversized_device(self):
        devices = [Device("D1", 50, ("A", "B", "C"))]
        result = solve_capacity_upgrade(devices, {"A": 5, "B": 0, "C": 0})
        # 总量 45 可全部加在 A 相；字典序最小为 A
        self.assertEqual(result.upgrades, {"A": 45, "B": 0, "C": 0})
        self.assertEqual(result.suggested_capacities, {"A": 50, "B": 0, "C": 0})
        self.assertEqual(result.assignment, {"D1": "A"})
        self.assertEqual(result.loads, {"A": 50, "B": 0, "C": 0})
        self.assertEqual(result.total_upgrade, 45)
        self.assertEqual(result.max_upgrade, 45)

    def test_forced_phase_requires_upgrade(self):
        devices = [Device("X", 50, ("A",)), Device("Y", 60, ("A",))]
        result = solve_capacity_upgrade(devices, {"A": 100, "B": 0, "C": 0})
        # 两台设备都只能接 A，A 相必须扩至 110（总量、单相最大均为 10）
        self.assertEqual(result.upgrades, {"A": 10, "B": 0, "C": 0})
        self.assertEqual(result.loads, {"A": 110, "B": 0, "C": 0})
        self.assertEqual(result.total_upgrade, 10)
        self.assertEqual(result.max_upgrade, 10)

    def test_minimize_total_then_max_single_phase(self):
        # 总量 20 最优：可拆成 (20,0,0) 或 (10,10,0) 等，应取单相最大最小的
        # (10,10,0)；同 max 下相位序列字典序最小，即两台设备都接 A（(A,A)
        # 字典序小于 (A,B)），扩容量 (20,0,0) 虽使两台同接 A，但 max=20
        # 并非最优 —— 故最优 max=10 由 (A,B) 实现。
        devices = [
            Device("D1", 10, ("A", "B", "C")),
            Device("D2", 10, ("A", "B", "C")),
        ]
        result = solve_capacity_upgrade(devices, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.total_upgrade, 20)
        self.assertEqual(result.max_upgrade, 10)
        # max=10 的方案要求两设备落在不同相位；序列字典序最小为 (A,B)
        self.assertEqual(result.upgrades, {"A": 10, "B": 10, "C": 0})
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B"})
        self.assertEqual(result.loads, {"A": 10, "B": 10, "C": 0})

    def test_lexicographic_tie_break(self):
        # 两台同功率全相位设备，原容量充裕时无需扩容，max 同为 0，
        # 此时没有均衡约束，取纯字典序最小相位序列 (A,A)
        devices = [Device("B2", 10, PHASES), Device("A1", 10, PHASES)]
        result = solve_capacity_upgrade(devices, {"A": 100, "B": 100, "C": 100})
        self.assertEqual(result.upgrades, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.total_upgrade, 0)
        self.assertEqual(result.max_upgrade, 0)
        self.assertEqual(result.assignment, {"A1": "A", "B2": "A"})

    def test_restricted_phases_shape_upgrade(self):
        devices = [
            Device("X", 30, ("A",)),
            Device("Y", 30, ("B",)),
            Device("Z", 30, ("C",)),
        ]
        result = solve_capacity_upgrade(devices, {"A": 10, "B": 10, "C": 10})
        # 每相被迫扩 20：总量 60，单相最大 20
        self.assertEqual(result.upgrades, {"A": 20, "B": 20, "C": 20})
        self.assertEqual(result.total_upgrade, 60)
        self.assertEqual(result.max_upgrade, 20)
        self.assertEqual(result.assignment, {"X": "A", "Y": "B", "Z": "C"})

    def test_existing_capacity_reused(self):
        # 总量最小为 8：两台都接 A（扩 8，序列 (A,A)）与分接 A/B（扩 B 8，
        # 序列 (A,B)）max 相同，字典序取 (A,A)
        devices = [
            Device("D1", 8, PHASES),
            Device("D2", 8, PHASES),
        ]
        result = solve_capacity_upgrade(devices, {"A": 8, "B": 0, "C": 0})
        self.assertEqual(result.total_upgrade, 8)
        self.assertEqual(result.max_upgrade, 8)
        self.assertEqual(result.upgrades, {"A": 8, "B": 0, "C": 0})
        self.assertEqual(result.assignment, {"D1": "A", "D2": "A"})
        self.assertEqual(result.loads, {"A": 16, "B": 0, "C": 0})


class CapacityUpgradeFuzzTest(unittest.TestCase):
    """扩容求解与朴素全枚举做随机对拍。"""

    def test_against_brute_force(self):
        rng = random.Random(20260925)
        for case in range(400):
            n = rng.randint(1, 7)
            devices = []
            for i in range(n):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                devices.append(Device(f"DEV-{i}", rng.randint(1, 20), allowed))
            capacities = {p: rng.randint(0, 40) for p in PHASES}

            expected = brute_force_upgrade(devices, capacities)
            result = solve_capacity_upgrade(devices, capacities)

            (exp_total, exp_max, exp_combo), exp_loads, exp_upgrades = expected
            self.assertEqual(
                result.total_upgrade, exp_total, f"case {case}: 扩容总量不符"
            )
            self.assertEqual(
                result.max_upgrade, exp_max, f"case {case}: 单相最大扩容不符"
            )
            self.assertEqual(result.upgrades, exp_upgrades, f"case {case}: 扩容量不符")
            self.assertEqual(result.loads, exp_loads, f"case {case}: 负载不符")
            ordered = sorted(devices, key=lambda d: d.code)
            actual_combo = tuple(result.assignment[d.code] for d in ordered)
            self.assertEqual(actual_combo, exp_combo, f"case {case}: 方案不符")
            # 一致性校验：扩容量与负载、建议容量自洽
            for p in PHASES:
                self.assertEqual(
                    result.suggested_capacities[p],
                    result.original_capacities[p] + result.upgrades[p],
                )
                self.assertGreaterEqual(
                    result.suggested_capacities[p], result.loads[p]
                )

    def test_twelve_devices_performance(self):
        # 12 台设备、全相位可接、原容量为 0：方案空间最大，应快速完成
        devices = [Device(f"D{i:02d}", 2**i, PHASES) for i in range(12)]
        result = solve_capacity_upgrade(devices, {"A": 0, "B": 0, "C": 0})
        expected = brute_force_upgrade(devices, {"A": 0, "B": 0, "C": 0})
        (exp_total, exp_max, exp_combo), _, _ = expected
        self.assertEqual(result.total_upgrade, exp_total)
        self.assertEqual(result.max_upgrade, exp_max)
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), exp_combo
        )

    def test_twelve_devices_feasible_performance(self):
        # 12 台设备在原容量下本就可行（扩容为 0）：第二遍仍须在全部可行方案
        # 中选出字典序最小者，枚举规模最大
        devices = [
            Device(f"D{i:02d}", 2 * i + 1, PHASES) for i in range(12)
        ]
        capacities = {"A": 1000, "B": 1000, "C": 1000}
        result = solve_capacity_upgrade(devices, capacities)
        expected = brute_force_upgrade(devices, capacities)
        (exp_total, exp_max, exp_combo), exp_loads, _ = expected
        self.assertEqual(result.total_upgrade, exp_total)
        self.assertEqual(result.max_upgrade, exp_max)
        self.assertEqual(result.loads, exp_loads)
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), exp_combo
        )


def brute_force_robust(devices, capacities):
    """稳健预演的朴素全枚举参照实现（内层枚举所有功率组合，仅适合小规模）。

    返回 (最坏负载差, 字典序最小相位序列, 各相负载下界, 各相负载上界) 或 None。
    同时验证闭式归约：最坏负载差 = max_{p≠q}(上界_p - 下界_q)。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    best = None
    for combo in itertools.product(*allowed):
        lower = {p: 0 for p in PHASES}
        upper = {p: 0 for p in PHASES}
        for device, phase in zip(ordered, combo):
            lower[phase] += device.min_power
            upper[phase] += device.max_power
        # 内层枚举所有功率组合，直接计算最坏负载差
        ranges = [range(d.min_power, d.max_power + 1) for d in ordered]
        worst = None
        for powers in itertools.product(*ranges):
            loads = {p: 0 for p in PHASES}
            for power, phase in zip(powers, combo):
                loads[phase] += power
            if any(loads[p] > capacities[p] for p in PHASES):
                worst = None  # 存在超容量的功率组合：非稳健可行
                break
            imbalance = max(loads.values()) - min(loads.values())
            if worst is None or imbalance > worst:
                worst = imbalance
        if worst is None:
            continue
        # 闭式归约正确性：最坏负载差 = max_{p≠q}(上界_p - 下界_q)
        closed_form = max(
            upper[p] - lower[q] for p in PHASES for q in PHASES if p != q
        )
        assert worst == closed_form, (worst, closed_form, lower, upper)
        if best is None or worst < best[0]:
            best = (worst, combo, dict(lower), dict(upper))
    return best


def brute_force_robust_closed_form(devices, capacities):
    """仅枚举相位序列、用闭式目标 max_{p≠q}(上界_p - 下界_q) 的参照实现。"""
    ordered = sorted(devices, key=lambda d: d.code)
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    best = None
    for combo in itertools.product(*allowed):
        lower = {p: 0 for p in PHASES}
        upper = {p: 0 for p in PHASES}
        for device, phase in zip(ordered, combo):
            lower[phase] += device.min_power
            upper[phase] += device.max_power
        # 稳健可行 ⟺ 任意功率组合下各相不超容量 ⟺ 上界不超容量
        if any(upper[p] > capacities[p] for p in PHASES):
            continue
        worst = max(
            upper[p] - lower[q] for p in PHASES for q in PHASES if p != q
        )
        if best is None or worst < best[0]:
            best = (worst, combo, dict(lower), dict(upper))
    return best


class RobustSolveTest(unittest.TestCase):
    def test_degenerates_to_fixed_power(self):
        # min == max 时应与普通求解结果一致
        devices = [
            RobustDevice("D1", 10, 10, PHASES),
            RobustDevice("D2", 20, 20, PHASES),
            RobustDevice("D3", 30, 30, PHASES),
        ]
        result = solve_robust(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.worst_imbalance, 20)
        self.assertEqual(result.load_lower, {"A": 10, "B": 20, "C": 30})
        self.assertEqual(result.load_upper, {"A": 10, "B": 20, "C": 30})
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B", "D3": "C"})

    def test_capacity_checked_on_upper_bound(self):
        # D1 上界 10 超过 A 相容量 8，只能接 B；下界 3 不超容量不影响结论
        devices = [RobustDevice("D1", 3, 10, ("A", "B"))]
        result = solve_robust(devices, {"A": 8, "B": 10, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.assignment, {"D1": "B"})
        self.assertEqual(result.load_upper, {"A": 0, "B": 10, "C": 0})
        self.assertEqual(result.load_lower, {"A": 0, "B": 3, "C": 0})
        self.assertEqual(result.worst_imbalance, 10)

    def test_infeasible_when_upper_exceeds_every_phase(self):
        devices = [RobustDevice("BIG", 1, 50, PHASES)]
        result = solve_robust(devices, {"A": 40, "B": 40, "C": 40})
        self.assertFalse(result.feasible)
        self.assertIsNone(result.assignment)
        self.assertIsNone(result.load_lower)
        self.assertIsNone(result.load_upper)
        self.assertIsNone(result.worst_imbalance)

    def test_worst_imbalance_uses_upper_minus_lower(self):
        # 单台设备：最坏负载差 = 上界 - 0（其余两相下界为 0）
        devices = [RobustDevice("D1", 4, 9, ("A",))]
        result = solve_robust(devices, {"A": 100, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.worst_imbalance, 9)
        self.assertEqual(result.load_lower, {"A": 4, "B": 0, "C": 0})
        self.assertEqual(result.load_upper, {"A": 9, "B": 0, "C": 0})

    def test_worst_imbalance_excludes_same_phase_pair(self):
        # 上界最大值与下界最小值同在 A 相：同一相不可能同时取到上界与下界，
        # 最坏负载差应为 max_{p≠q}(上界_p - 下界_q) = max(100-50, 60-1, ...) = 59
        devices = [
            RobustDevice("D1", 1, 100, ("A",)),
            RobustDevice("D2", 50, 50, ("B",)),
            RobustDevice("D3", 60, 60, ("C",)),
        ]
        result = solve_robust(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.load_lower, {"A": 1, "B": 50, "C": 60})
        self.assertEqual(result.load_upper, {"A": 100, "B": 50, "C": 60})
        self.assertEqual(result.worst_imbalance, 59)

    def test_uncertainty_drives_assignment(self):
        # 两台设备功率区间宽度不同：固定功率下 (A,B) 与 (B,A) 等效，
        # 但区间下界不为 0 时，最坏负载差因分配而异
        devices = [
            RobustDevice("D1", 1, 10, PHASES),
            RobustDevice("D2", 9, 10, PHASES),
        ]
        result = solve_robust(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        # (D1->A, D2->B)：上界 (10,10,0)，下界 (1,9,0)，最坏差 = 10 - 0 = 10
        # 任何同相分配上界和为 20，最坏差更大
        self.assertEqual(result.worst_imbalance, 10)
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B"})

    def test_lexicographic_tie_break(self):
        # 区间完全相同的两台设备：取编号排序后相位序列字典序最小者
        devices = [
            RobustDevice("B2", 2, 10, PHASES),
            RobustDevice("A1", 2, 10, PHASES),
        ]
        result = solve_robust(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.assignment, {"A1": "A", "B2": "B"})

    def test_perfect_robust_balance(self):
        devices = [RobustDevice(f"D{i}", 10, 10, PHASES) for i in range(1, 4)]
        result = solve_robust(devices, {"A": 10, "B": 10, "C": 10})
        self.assertTrue(result.feasible)
        self.assertEqual(result.worst_imbalance, 0)


class RobustSolveFuzzTest(unittest.TestCase):
    """与朴素全枚举参照实现做随机对拍。"""

    def _check_against(self, brute, rng, cases, max_devices, max_width):
        for case in range(cases):
            n = rng.randint(1, max_devices)
            devices = []
            for i in range(n):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                lo = rng.randint(1, 12)
                hi = lo + rng.randint(0, max_width)
                devices.append(RobustDevice(f"DEV-{i}", lo, hi, allowed))
            capacities = {p: rng.randint(0, 60) for p in PHASES}

            expected = brute(devices, capacities)
            result = solve_robust(devices, capacities)

            if expected is None:
                self.assertFalse(result.feasible, f"case {case}: 应为无稳健可行解")
                continue

            self.assertTrue(result.feasible, f"case {case}: 应有稳健可行解")
            exp_worst, exp_combo, exp_lower, exp_upper = expected
            self.assertEqual(
                result.worst_imbalance, exp_worst, f"case {case}: 最坏负载差不符"
            )
            self.assertEqual(result.load_lower, exp_lower, f"case {case}: 负载下界不符")
            self.assertEqual(result.load_upper, exp_upper, f"case {case}: 负载上界不符")
            ordered = sorted(devices, key=lambda d: d.code)
            actual_combo = tuple(result.assignment[d.code] for d in ordered)
            self.assertEqual(
                actual_combo, exp_combo, f"case {case}: 字典序最小方案不符"
            )

    def test_against_power_enumeration(self):
        # 小规模：参照实现内层枚举所有功率组合，同时验证闭式归约
        self._check_against(
            brute_force_robust, random.Random(20260926), cases=120, max_devices=4,
            max_width=3,
        )

    def test_against_closed_form_brute_force(self):
        # 较大规模：参照实现枚举相位序列、使用闭式目标
        self._check_against(
            brute_force_robust_closed_form,
            random.Random(20260927),
            cases=300,
            max_devices=7,
            max_width=8,
        )

    def test_twelve_devices_performance(self):
        # 12 台设备、全相位可接、大容量：最恶劣情形，应在可接受时间内完成
        devices = [
            RobustDevice(f"D{i:02d}", max(1, 2**i - 3), 2**i, PHASES)
            for i in range(12)
        ]
        capacities = {"A": 10**6, "B": 10**6, "C": 10**6}
        result = solve_robust(devices, capacities)
        self.assertTrue(result.feasible)
        expected = brute_force_robust_closed_form(devices, capacities)
        exp_worst, exp_combo, exp_lower, exp_upper = expected
        self.assertEqual(result.worst_imbalance, exp_worst)
        self.assertEqual(result.load_lower, exp_lower)
        self.assertEqual(result.load_upper, exp_upper)
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), exp_combo
        )


def brute_force_startup(devices, capacities):
    """启动顺序规划的朴素全排列参照实现。

    返回 (全过程负载差峰值, 编号顺序) 或 None（无安全顺序）。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    best = None
    for perm in itertools.permutations(range(len(ordered))):
        loads = {p: 0 for p in PHASES}
        peak = 0
        ok = True
        for idx in perm:
            device = ordered[idx]
            # 启动瞬间：该设备按启动功率计，此前设备按额定功率运行
            t_loads = dict(loads)
            t_loads[device.phase] += device.startup_power
            if any(t_loads[p] > capacities[p] for p in PHASES):
                ok = False
                break
            peak = max(peak, max(t_loads.values()) - min(t_loads.values()))
            # 启动完成：该设备转入额定功率持续运行
            loads[device.phase] += device.rated_power
            if any(loads[p] > capacities[p] for p in PHASES):
                ok = False
                break
            peak = max(peak, max(loads.values()) - min(loads.values()))
        if not ok:
            continue
        seq = tuple(ordered[i].code for i in perm)
        if best is None or (peak, seq) < best:
            best = (peak, seq)
    return best


class StartupPlanTest(unittest.TestCase):
    def test_single_device(self):
        devices = [StartupDevice("D1", "A", 10, 15)]
        result = solve_startup_plan(devices, {"A": 20, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.order, ("D1",))
        self.assertEqual(result.peak_imbalance, 15)
        step = result.steps[0]
        self.assertEqual(step.transient_loads, {"A": 15, "B": 0, "C": 0})
        self.assertEqual(result.steps[0].transient_imbalance, 15)
        self.assertEqual(step.steady_loads, {"A": 10, "B": 0, "C": 0})
        self.assertEqual(step.steady_imbalance, 10)
        self.assertEqual(step.rated_power, 10)
        self.assertEqual(step.startup_power, 15)

    def test_single_device_no_safe_order(self):
        # 唯一设备启动功率 25 超 A 相容量 20（额定 10 可行）：无安全顺序
        devices = [StartupDevice("D1", "A", 10, 25)]
        result = solve_startup_plan(devices, {"A": 20, "B": 0, "C": 0})
        self.assertFalse(result.feasible)
        self.assertIsNone(result.order)
        self.assertIsNone(result.steps)
        self.assertIsNone(result.peak_imbalance)

    def test_order_matters_for_feasibility(self):
        # D1（额定6/启动10）与 D2（额定4/启动4）同接 A，容量 10：
        # 先 D1 后 D2：10(瞬)→6(稳)→10(瞬) 安全；
        # 先 D2 后 D1：4(稳)→4+10=14(瞬) 超容量，故安全顺序唯一
        devices = [StartupDevice("D1", "A", 6, 10), StartupDevice("D2", "A", 4, 4)]
        result = solve_startup_plan(devices, {"A": 10, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.order, ("D1", "D2"))
        self.assertEqual(result.peak_imbalance, 10)
        self.assertEqual(
            result.steps[0].transient_loads, {"A": 10, "B": 0, "C": 0}
        )
        self.assertEqual(result.steps[0].steady_loads, {"A": 6, "B": 0, "C": 0})
        self.assertEqual(
            result.steps[1].transient_loads, {"A": 10, "B": 0, "C": 0}
        )
        self.assertEqual(result.steps[1].steady_loads, {"A": 10, "B": 0, "C": 0})

    def test_order_matters_for_peak(self):
        # 三相各一台：D3 启动功率最大，后启动可由已运行的其他相拉小负载差
        devices = [
            StartupDevice("D1", "A", 6, 8),
            StartupDevice("D2", "B", 4, 6),
            StartupDevice("D3", "C", 5, 9),
        ]
        caps = {"A": 10, "B": 10, "C": 10}
        result = solve_startup_plan(devices, caps)
        self.assertTrue(result.feasible)
        # (D1,D2,D3) 与 (D2,D1,D3) 峰值均为 8，取编号序列字典序最小者
        self.assertEqual(result.order, ("D1", "D2", "D3"))
        self.assertEqual(result.peak_imbalance, 8)

    def test_lexicographic_tie_break(self):
        # 两台完全相同的设备：两种顺序的负载过程完全一致，取字典序最小编号序列
        devices = [
            StartupDevice("B2", "A", 5, 8),
            StartupDevice("A1", "A", 5, 8),
        ]
        result = solve_startup_plan(devices, {"A": 100, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.order, ("A1", "B2"))

    def test_startup_power_may_equal_rated(self):
        # 启动瞬时功率允许恰好等于额定功率
        devices = [StartupDevice("D1", "A", 10, 10)]
        result = solve_startup_plan(devices, {"A": 10, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.peak_imbalance, 10)
        self.assertEqual(
            result.steps[0].transient_loads, result.steps[0].steady_loads
        )

    def test_final_steady_state_is_record_loads(self):
        # 末步稳定负载与全部设备额定运行的固定分配一致
        devices = [
            StartupDevice("D1", "A", 6, 9),
            StartupDevice("D2", "B", 4, 7),
            StartupDevice("D3", "C", 5, 8),
        ]
        result = solve_startup_plan(devices, {"A": 10, "B": 10, "C": 10})
        self.assertTrue(result.feasible)
        self.assertEqual(
            result.steps[-1].steady_loads, {"A": 6, "B": 4, "C": 5}
        )
        self.assertEqual(result.steps[-1].steady_imbalance, 2)
        # 全过程峰值不小于最终稳定状态的负载差
        self.assertGreaterEqual(result.peak_imbalance, 2)


class StartupPlanFuzzTest(unittest.TestCase):
    """与朴素全排列参照实现做随机对拍（含逐步负载仿真校验）。"""

    def _simulate_and_check(self, result, devices, capacities):
        """按返回顺序逐步仿真，校验瞬时/稳定负载、容量与峰值自洽。"""
        by_code = {d.code: d for d in devices}
        loads = {p: 0 for p in PHASES}
        peak = 0
        prev_code = None
        self.assertEqual(tuple(s.code for s in result.steps), result.order)
        for step in result.steps:
            device = by_code[step.code]
            self.assertEqual(step.phase, device.phase)
            self.assertEqual(step.rated_power, device.rated_power)
            self.assertEqual(step.startup_power, device.startup_power)
            t_loads = dict(loads)
            t_loads[device.phase] += device.startup_power
            self.assertEqual(step.transient_loads, t_loads)
            self.assertEqual(
                step.transient_imbalance,
                max(t_loads.values()) - min(t_loads.values()),
            )
            for p in PHASES:
                self.assertLessEqual(t_loads[p], capacities[p])
            loads[device.phase] += device.rated_power
            self.assertEqual(step.steady_loads, loads)
            self.assertEqual(
                step.steady_imbalance,
                max(loads.values()) - min(loads.values()),
            )
            for p in PHASES:
                self.assertLessEqual(loads[p], capacities[p])
            peak = max(peak, step.transient_imbalance, step.steady_imbalance)
        self.assertEqual(peak, result.peak_imbalance)

    def test_against_brute_force(self):
        rng = random.Random(20260928)
        for case in range(300):
            n = rng.randint(1, 7)
            devices = []
            for i in range(n):
                rated = rng.randint(1, 15)
                startup = rated + rng.randint(0, 10)
                devices.append(
                    StartupDevice(
                        f"DEV-{i}", rng.choice(PHASES), rated, startup
                    )
                )
            capacities = {p: rng.randint(0, 60) for p in PHASES}

            expected = brute_force_startup(devices, capacities)
            result = solve_startup_plan(devices, capacities)

            if expected is None:
                self.assertFalse(result.feasible, f"case {case}: 应为无安全启动顺序")
                continue
            exp_peak, exp_seq = expected
            self.assertTrue(result.feasible, f"case {case}: 应有安全启动顺序")
            self.assertEqual(
                result.peak_imbalance, exp_peak, f"case {case}: 峰值不符"
            )
            self.assertEqual(
                result.order, exp_seq, f"case {case}: 字典序最小顺序不符"
            )
            self._simulate_and_check(result, devices, capacities)

    def test_eight_devices_brute_force(self):
        # 8! = 40320：全排列参照仍可承受，覆盖更大状态空间
        rng = random.Random(20260929)
        devices = []
        for i in range(8):
            rated = rng.randint(1, 12)
            devices.append(
                StartupDevice(f"D{i}", PHASES[i % 3], rated, rated + i)
            )
        capacities = {"A": 80, "B": 80, "C": 80}
        result = solve_startup_plan(devices, capacities)
        expected = brute_force_startup(devices, capacities)
        self.assertEqual(result.peak_imbalance, expected[0])
        self.assertEqual(result.order, expected[1])
        self._simulate_and_check(result, devices, capacities)

    def test_twelve_devices_performance(self):
        # 12 台设备：子集 DP 状态 2^12=4096，应瞬时完成并自洽
        devices = [
            StartupDevice(
                f"D{i:02d}", PHASES[i % 3], 2 * i + 1, 2 * i + 1 + (i % 4)
            )
            for i in range(12)
        ]
        capacities = {"A": 10**6, "B": 10**6, "C": 10**6}
        result = solve_startup_plan(devices, capacities)
        self.assertTrue(result.feasible)
        self.assertEqual(len(result.order), 12)
        self.assertEqual(set(result.order), {d.code for d in devices})
        self._simulate_and_check(result, devices, capacities)

    def test_twelve_devices_tight_capacity(self):
        # 紧容量：12 台同相设备（额定均 1；D00 启动 3，其余启动 2），
        # 额定总和 12。验证可行性剪枝、无解判定与顺序约束。
        devices = [
            StartupDevice(f"D{i:02d}", "A", 1, 3 if i == 0 else 2)
            for i in range(12)
        ]
        # 容量 12：末台瞬时 11+2=13（或 D00 末台 11+3=14）均超容量，无解
        result = solve_startup_plan(devices, {"A": 12, "B": 0, "C": 0})
        self.assertFalse(result.feasible)

        # 容量 13：非 D00 设备殿后瞬时恰为 13 可行，D00 殿后为 14 不可行，
        # 故安全顺序中 D00 不得殿后；最优峰值必为 13（末台瞬时），
        # 同峰值字典序最小顺序为 D00 最先、其余按编号排列
        caps = {"A": 13, "B": 0, "C": 0}
        result = solve_startup_plan(devices, caps)
        self.assertTrue(result.feasible)
        self.assertEqual(
            result.order, tuple(f"D{i:02d}" for i in range(12))
        )
        self.assertEqual(result.peak_imbalance, 13)
        self._simulate_and_check(result, devices, caps)


def brute_force_fault(devices, capacities, fault_phase):
    """单相故障保供预演的朴素全枚举参照实现。

    健康相设备保持原分配；故障相设备可选「允许的健康相（按 A/B/C 顺序）」
    或断开（标记 "D"）。按 (保留功率, 保留数量, 选择序列) 取最优——
    保留功率/数量越大越好，同值时序列字典序越小越好（"A"<"B"<"C"<"D"）。
    返回 (选择序列, 最终负载, 迁移字典, 断开列表, 保留功率, 保留数量)。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    fault = [d for d in ordered if d.original_phase == fault_phase]
    healthy = [d for d in ordered if d.original_phase != fault_phase]
    healthy_phases = [p for p in PHASES if p != fault_phase]

    initial = {p: 0 for p in PHASES}
    fixed_power = 0
    for d in healthy:
        initial[d.original_phase] += d.power
        fixed_power += d.power

    options = []
    for d in fault:
        moves = [p for p in healthy_phases if p in d.allowed]
        options.append(moves + ["D"])

    best = None
    for combo in itertools.product(*options):
        loads = dict(initial)
        ok = True
        kept_power = 0
        for d, choice in zip(fault, combo):
            if choice != "D":
                loads[choice] += d.power
                if loads[choice] > capacities[choice]:
                    ok = False
                    break
                kept_power += d.power
        if not ok:
            continue
        kept_count = len(healthy) + sum(1 for c in combo if c != "D")
        key = (-kept_power - fixed_power, -kept_count, combo)
        if best is None or key < best[0]:
            migrations = {
                d.code: choice
                for d, choice in zip(fault, combo)
                if choice != "D"
            }
            disconnected = [d.code for d, choice in zip(fault, combo) if choice == "D"]
            loads[fault_phase] = 0
            best = (
                key,
                combo,
                dict(loads),
                migrations,
                disconnected,
                kept_power + fixed_power,
                kept_count,
            )
    return best


class PhaseFaultRehearsalTest(unittest.TestCase):
    def test_healthy_devices_keep_assignment_and_migrate(self):
        # 健康相设备不动；两台 A 相设备迁至 B/C（B 有 5 空闲，C 有 10）
        devices = [
            FaultRehearsalDevice("H1", 5, ("B",), "B"),
            FaultRehearsalDevice("M1", 10, ("A", "B", "C"), "A"),
            FaultRehearsalDevice("M2", 6, ("B", "C"), "A"),
        ]
        caps = {"A": 100, "B": 10, "C": 10}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.fault_phase, "A")
        self.assertEqual(result.original_loads, {"A": 16, "B": 5, "C": 0})
        # M1(10) 只能迁 C；M2(6) 迁 C 会与 M1 一起占满 C（10+6>10），
        # 迁 B 又超容量（5+6>10），故 M2 断开
        self.assertEqual(result.loads, {"A": 0, "B": 5, "C": 10})
        self.assertEqual(
            [(m.code, m.from_phase, m.to_phase) for m in result.migrations],
            [("M1", "A", "C")],
        )
        self.assertEqual(
            [(d.code, d.power, d.phase) for d in result.disconnected],
            [("M2", 6, "A")],
        )
        self.assertEqual(result.retained_power, 15)
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.disconnected_power, 6)
        self.assertEqual(result.disconnected_count, 1)
        self.assertEqual(result.choice_sequence, ("C", "D"))

    def test_all_devices_retained(self):
        # 两台 A 相设备均可迁 B/C 且容量充裕：全部保留；
        # 全保留方案中序列 (B,B) 字典序最小
        devices = [
            FaultRehearsalDevice("M1", 4, ("A", "B", "C"), "A"),
            FaultRehearsalDevice("M2", 4, ("B", "C"), "A"),
        ]
        caps = {"A": 100, "B": 10, "C": 10}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.loads, {"A": 0, "B": 8, "C": 0})
        self.assertEqual(result.retained_power, 8)
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.disconnected, ())
        self.assertEqual(
            [(m.code, m.to_phase) for m in result.migrations],
            [("M1", "B"), ("M2", "B")],
        )
        self.assertEqual(result.choice_sequence, ("B", "B"))

    def test_maximize_power_before_count(self):
        # 只能利用 B 相（其余健康相 C 容量为 0）：留下两台小设备（共 6）或
        # 一台大设备（10），总功率优先 -> 保留大设备，尽管设备数更少
        devices = [
            FaultRehearsalDevice("M1", 3, ("A", "B"), "A"),
            FaultRehearsalDevice("M2", 3, ("A", "B"), "A"),
            FaultRehearsalDevice("M3", 10, ("A", "B"), "A"),
        ]
        caps = {"A": 100, "B": 10, "C": 0}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.retained_power, 10)
        self.assertEqual(result.retained_count, 1)
        self.assertEqual(result.loads, {"A": 0, "B": 10, "C": 0})
        self.assertEqual([m.code for m in result.migrations], ["M3"])
        self.assertEqual(
            [d.code for d in result.disconnected], ["M1", "M2"]
        )
        # M1、M2 断开，M3 迁 B：序列 (D, D, B)
        self.assertEqual(result.choice_sequence, ("D", "D", "B"))

    def test_maximize_count_on_equal_power(self):
        # 单台 6 与两台 3 只能竞用 B 相 6 容量：总功率相同，取设备数多者
        devices = [
            FaultRehearsalDevice("M1", 3, ("A", "B"), "A"),
            FaultRehearsalDevice("M2", 3, ("A", "B"), "A"),
            FaultRehearsalDevice("M3", 6, ("A", "B"), "A"),
        ]
        caps = {"A": 100, "B": 6, "C": 0}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.retained_power, 6)
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.loads, {"A": 0, "B": 6, "C": 0})
        self.assertEqual(
            [m.code for m in result.migrations], ["M1", "M2"]
        )
        self.assertEqual([d.code for d in result.disconnected], ["M3"])
        self.assertEqual(result.choice_sequence, ("B", "B", "D"))

    def test_lexicographic_tie_break_prefers_healthy_phase(self):
        # 功率与设备数都相同的方案间：同编号设备可迁 B 或 C 时取序号更小的 B
        devices = [
            FaultRehearsalDevice("M1", 4, ("B", "C"), "A"),
            FaultRehearsalDevice("M2", 4, ("B", "C"), "A"),
        ]
        caps = {"A": 100, "B": 10, "C": 10}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        # (B,B) 与 (B,C)/(C,B)/(C,C) 同为全保留，取字典序最小 (B,B)
        self.assertEqual(result.choice_sequence, ("B", "B"))
        self.assertEqual(result.loads, {"A": 0, "B": 8, "C": 0})
        self.assertEqual(
            [(m.code, m.to_phase) for m in result.migrations],
            [("M1", "B"), ("M2", "B")],
        )

    def test_lexicographic_order_disconnect_last(self):
        # 迁移与断开在同功率方案间：A＜B＜C＜断开，能迁移时不优先断开
        devices = [
            FaultRehearsalDevice("M1", 4, ("C",), "A"),
            FaultRehearsalDevice("M2", 4, ("B",), "A"),
        ]
        caps = {"A": 100, "B": 4, "C": 4}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        # 两台均可保留（分别只能迁 C、B）：序列按编号排序为 (C, B)
        self.assertEqual(result.choice_sequence, ("C", "B"))
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.loads, {"A": 0, "B": 4, "C": 4})

    def test_fault_only_device_without_healthy_option_disconnected(self):
        # 故障相设备的允许相位只含故障相：只能断开
        devices = [
            FaultRehearsalDevice("F1", 9, ("A",), "A"),
            FaultRehearsalDevice("H1", 3, ("B",), "B"),
        ]
        result = solve_phase_fault_rehearsal(
            devices, {"A": 100, "B": 100, "C": 100}, "A"
        )
        self.assertEqual(result.loads, {"A": 0, "B": 3, "C": 0})
        self.assertEqual(result.migrations, ())
        self.assertEqual([d.code for d in result.disconnected], ["F1"])
        self.assertEqual(result.choice_sequence, ("D",))
        self.assertEqual(result.retained_power, 3)
        self.assertEqual(result.retained_count, 1)

    def test_no_fault_devices(self):
        # 故障相本就无设备：负载不变，迁移 / 断开均为空
        devices = [
            FaultRehearsalDevice("H1", 5, ("B",), "B"),
            FaultRehearsalDevice("H2", 7, ("C",), "C"),
        ]
        result = solve_phase_fault_rehearsal(
            devices, {"A": 10, "B": 10, "C": 10}, "A"
        )
        self.assertEqual(result.original_loads, {"A": 0, "B": 5, "C": 7})
        self.assertEqual(result.loads, {"A": 0, "B": 5, "C": 7})
        self.assertEqual(result.migrations, ())
        self.assertEqual(result.disconnected, ())
        self.assertEqual(result.retained_power, 12)
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.choice_sequence, ())

    def test_fault_with_b_and_c_healthy_phases(self):
        # B 相故障：健康相为 A、C，选项顺序 A→C→断开
        devices = [
            FaultRehearsalDevice("F1", 4, ("A", "B"), "B"),
            FaultRehearsalDevice("H1", 2, ("A",), "A"),
        ]
        result = solve_phase_fault_rehearsal(
            devices, {"A": 10, "B": 10, "C": 10}, "B"
        )
        self.assertEqual(result.loads, {"A": 6, "B": 0, "C": 0})
        self.assertEqual([m.code for m in result.migrations], ["F1"])
        self.assertEqual(result.migrations[0].to_phase, "A")
        self.assertEqual(result.choice_sequence, ("A",))

    def test_capacity_never_exceeded(self):
        # 健康相已被占满：故障相设备无容量可迁，全部断开
        devices = [
            FaultRehearsalDevice("F1", 5, ("B", "C"), "A"),
            FaultRehearsalDevice("F2", 5, ("B", "C"), "A"),
            FaultRehearsalDevice("H1", 10, ("B",), "B"),
            FaultRehearsalDevice("H2", 10, ("C",), "C"),
        ]
        caps = {"A": 100, "B": 10, "C": 10}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.loads, {"A": 0, "B": 10, "C": 10})
        self.assertEqual(result.migrations, ())
        self.assertEqual(
            [d.code for d in result.disconnected], ["F1", "F2"]
        )
        self.assertEqual(result.choice_sequence, ("D", "D"))
        self.assertEqual(result.retained_power, 20)
        self.assertEqual(result.retained_count, 2)


class PhaseFaultRehearsalFuzzTest(unittest.TestCase):
    """与朴素全枚举参照实现做随机对拍。"""

    def _check_against(self, devices, capacities, fault_phase):
        result = solve_phase_fault_rehearsal(devices, capacities, fault_phase)
        expected = brute_force_fault(devices, capacities, fault_phase)
        self.assertIsNotNone(expected)  # 全断开恒可行
        _, exp_combo, exp_loads, exp_migrations, exp_disconnected, exp_power, exp_count = expected
        self.assertEqual(result.loads, exp_loads)
        self.assertEqual(result.retained_power, exp_power)
        self.assertEqual(result.retained_count, exp_count)
        actual_migrations = {m.code: m.to_phase for m in result.migrations}
        self.assertEqual(actual_migrations, exp_migrations)
        self.assertEqual(
            [d.code for d in result.disconnected], exp_disconnected
        )
        ordered_fault = sorted(
            (d for d in devices if d.original_phase == fault_phase),
            key=lambda d: d.code,
        )
        self.assertEqual(
            result.choice_sequence,
            tuple(exp_combo),
        )
        self.assertEqual(len(result.choice_sequence), len(ordered_fault))
        # 自洽性：故障相负载为零，健康相负载不超容量
        self.assertEqual(result.loads[fault_phase], 0)
        for p in PHASES:
            self.assertLessEqual(result.loads[p], capacities[p])
        self.assertEqual(
            result.disconnected_power,
            sum(d.power for d in result.disconnected),
        )
        total_power = sum(d.power for d in devices)
        self.assertEqual(
            result.retained_power + result.disconnected_power, total_power
        )
        self.assertEqual(
            result.retained_count + result.disconnected_count, len(devices)
        )

    def test_against_brute_force(self):
        rng = random.Random(20260930)
        for case in range(500):
            n = rng.randint(1, 7)
            devices = []
            original_loads = {p: 0 for p in PHASES}
            for i in range(n):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                # 原相位取自允许集合（模拟可行计算记录的分配结果）
                original_phase = rng.choice(allowed)
                power = rng.randint(1, 20)
                devices.append(
                    FaultRehearsalDevice(
                        f"DEV-{i}", power, allowed, original_phase
                    )
                )
                original_loads[original_phase] += power
            # 容量不低于原分配负载（记录可行），叠加随机余量以同时覆盖
            # 「无迁移空间」与「有迁移空间」两类情形
            capacities = {
                p: original_loads[p] + rng.randint(0, 30) for p in PHASES
            }
            fault_phase = PHASES[case % 3]
            self._check_against(devices, capacities, fault_phase)

    def test_twelve_devices_performance(self):
        # 12 台设备全部位于故障相、全相位可接、紧容量：求解器须在极短时间内
        # 完成（剪枝后实际枚举远小于 4^12），并保证结果自洽
        devices = [
            FaultRehearsalDevice(
                f"D{i:02d}", 2 * i + 1, PHASES, "A"
            )
            for i in range(12)
        ]
        capacities = {"A": 10**6, "B": 40, "C": 50}
        result = solve_phase_fault_rehearsal(devices, capacities, "A")
        self.assertEqual(result.loads["A"], 0)
        for p in PHASES:
            self.assertLessEqual(result.loads[p], capacities[p])
        # 保留功率 + 断开功率 = 全部设备总功率；保留数 + 断开数 = 设备总数
        total_power = sum(d.power for d in devices)
        self.assertEqual(
            result.retained_power + result.disconnected_power, total_power
        )
        self.assertEqual(
            result.retained_count + result.disconnected_count, 12
        )
        # 选择序列长度等于故障相设备数，元素取自 B/C/D
        self.assertEqual(len(result.choice_sequence), 12)
        self.assertTrue(all(c in ("B", "C", "D") for c in result.choice_sequence))
        # B/C 上保留的功率即保留总功率（无健康相设备），且不超容量
        self.assertEqual(
            result.retained_power, result.loads["B"] + result.loads["C"]
        )

    def test_nine_devices_against_brute_force(self):
        # 9 台故障相设备对拍：4^9 ≈ 26 万全枚举，紧容量下大量组合
        # 被容量约束提前终止，覆盖较大规模下的最优性与字典序
        devices = [
            FaultRehearsalDevice(f"D{i:02d}", 2 * i + 1, PHASES, "A")
            for i in range(9)
        ]
        capacities = {"A": 10**6, "B": 30, "C": 30}
        result = solve_phase_fault_rehearsal(devices, capacities, "A")
        expected = brute_force_fault(devices, capacities, "A")
        self.assertEqual(result.retained_power, expected[5])
        self.assertEqual(result.retained_count, expected[6])
        self.assertEqual(result.choice_sequence, expected[1])
        self.assertEqual(result.loads, expected[2])

    def test_twelve_devices_all_fault_phase_tight(self):
        # 极端情形：无健康相设备，所有设备只能断开（允许相位仅故障相）
        devices = [
            FaultRehearsalDevice(f"D{i:02d}", i + 1, ("A",), "A")
            for i in range(12)
        ]
        caps = {"A": 100, "B": 100, "C": 100}
        result = solve_phase_fault_rehearsal(devices, caps, "A")
        self.assertEqual(result.loads, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.migrations, ())
        self.assertEqual(result.disconnected_count, 12)
        self.assertEqual(result.retained_power, 0)
        self.assertEqual(result.choice_sequence, ("D",) * 12)


def brute_force_addition(existing, new_devices, capacities):
    """新增设备接入预演的朴素全枚举参照实现。

    返回 ((改相台数, 负载差, 相位序列), 各相负载) 或 None（无可行方案）。
    新旧设备合并后按编号排序，相位序列按全部设备编号排序产生。
    """
    combined = sorted(
        [
            (
                d.code,
                d.power,
                tuple(p for p in PHASES if p in d.allowed),
                d.original_phase,
            )
            for d in existing
        ]
        + [
            (d.code, d.power, tuple(p for p in PHASES if p in d.allowed), None)
            for d in new_devices
        ],
        key=lambda item: item[0],
    )
    best = None
    for combo in itertools.product(*[item[2] for item in combined]):
        loads = {p: 0 for p in PHASES}
        ok = True
        for item, phase in zip(combined, combo):
            loads[phase] += item[1]
            if loads[phase] > capacities[phase]:
                ok = False
                break
        if not ok:
            continue
        migrations = sum(
            1
            for item, phase in zip(combined, combo)
            if item[3] is not None and phase != item[3]
        )
        imbalance = max(loads.values()) - min(loads.values())
        key = (migrations, imbalance, combo)
        if best is None or key < best[0]:
            best = (key, dict(loads))
    return best


class DeviceAdditionTest(unittest.TestCase):
    def test_no_migration_needed(self):
        # 原设备 D1->A(6)、D2->B(4)；新设备 N1 只能接 C：不改相即得均衡方案
        existing = [
            AdditionExistingDevice("D1", 6, ("A", "B"), "A"),
            AdditionExistingDevice("D2", 4, ("B", "C"), "B"),
        ]
        new_devices = [Device("N1", 4, ("C",))]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 10, "C": 10}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 0)
        self.assertEqual(result.migrations, ())
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B", "N1": "C"})
        self.assertEqual(result.loads, {"A": 6, "B": 4, "C": 4})
        self.assertEqual(result.imbalance, 2)

    def test_min_migrations_before_imbalance(self):
        # 不改相时唯一可行方案负载差为 10（N1 只能接 B：负载 6/10/0）；
        # 改相 1 台可达负载差 2（D2 迁 C、N1 接 B：6/6/4）。
        # 改相台数优先，应取不改相方案。
        existing = [
            AdditionExistingDevice("D1", 6, ("A", "B"), "A"),
            AdditionExistingDevice("D2", 4, ("B", "C"), "B"),
        ]
        new_devices = [Device("N1", 6, ("A", "B"))]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 10, "C": 10}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 0)
        self.assertEqual(result.migrations, ())
        self.assertEqual(result.assignment, {"D1": "A", "D2": "B", "N1": "B"})
        self.assertEqual(result.loads, {"A": 6, "B": 10, "C": 0})
        self.assertEqual(result.imbalance, 10)

    def test_migration_forced(self):
        # 容量 8：D1->A(6)、D2->B(4) 时新设备 N1(5, A/B) 无处可放，
        # 必须改相一台：D2 迁 C、N1 接 B -> 负载 6/5/4（负载差 2）
        existing = [
            AdditionExistingDevice("D1", 6, ("A", "B"), "A"),
            AdditionExistingDevice("D2", 4, ("B", "C"), "B"),
        ]
        new_devices = [Device("N1", 5, ("A", "B"))]
        result = solve_device_addition(
            existing, new_devices, {"A": 8, "B": 8, "C": 8}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 1)
        self.assertEqual(len(result.migrations), 1)
        migration = result.migrations[0]
        self.assertEqual(migration.code, "D2")
        self.assertEqual(migration.power, 4)
        self.assertEqual(migration.from_phase, "B")
        self.assertEqual(migration.to_phase, "C")
        self.assertEqual(result.assignment, {"D1": "A", "D2": "C", "N1": "B"})
        self.assertEqual(result.loads, {"A": 6, "B": 5, "C": 4})
        self.assertEqual(result.imbalance, 2)

    def test_imbalance_then_lexicographic_tie_break(self):
        # 原设备 D1(4) 固定 A；两台同功率新设备：唯一不改相均衡方案为
        # 负载 4/4/4，序列 (D1,N1,N2) 字典序最小为 (A,B,C)
        existing = [AdditionExistingDevice("D1", 4, ("A", "B", "C"), "A")]
        new_devices = [
            Device("N1", 4, ("A", "B", "C")),
            Device("N2", 4, ("A", "B", "C")),
        ]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 10, "C": 10}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 0)
        self.assertEqual(result.imbalance, 0)
        self.assertEqual(
            result.assignment, {"D1": "A", "N1": "B", "N2": "C"}
        )
        self.assertEqual(result.loads, {"A": 4, "B": 4, "C": 4})

    def test_lexicographic_sequence_covers_new_and_existing(self):
        # 新设备编号 A1 排在原设备 B1 之前：不改相时 B1 固定 A，
        # A1 接 B 或 C 负载差相同，按全部设备排序序列取 (B,A)
        existing = [AdditionExistingDevice("B1", 10, ("A", "B", "C"), "A")]
        new_devices = [Device("A1", 10, ("A", "B", "C"))]
        result = solve_device_addition(
            existing, new_devices, {"A": 100, "B": 100, "C": 100}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 0)
        self.assertEqual(result.assignment, {"A1": "B", "B1": "A"})
        self.assertEqual(result.loads, {"A": 10, "B": 10, "C": 0})

    def test_migration_may_be_required_for_new_forced_phase(self):
        # 新设备 N1 只能接 A 且 A 已被原设备占满：原设备须让出 A
        existing = [
            AdditionExistingDevice("D1", 6, ("A", "B", "C"), "A"),
            AdditionExistingDevice("D2", 4, ("B", "C"), "B"),
        ]
        new_devices = [Device("N1", 6, ("A",))]
        result = solve_device_addition(
            existing, new_devices, {"A": 6, "B": 10, "C": 10}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 1)
        self.assertEqual(result.migrations[0].code, "D1")
        self.assertEqual(result.migrations[0].from_phase, "A")
        self.assertEqual(result.assignment["N1"], "A")
        self.assertEqual(result.loads["A"], 6)
        self.assertLessEqual(result.loads["B"], 10)
        self.assertLessEqual(result.loads["C"], 10)

    def test_infeasible(self):
        # 原设备 D1(10) 占满 A（容量 10，B/C 容量 0），新设备无处可接
        existing = [AdditionExistingDevice("D1", 10, ("A",), "A")]
        new_devices = [Device("N1", 1, ("A", "B", "C"))]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 0, "C": 0}
        )
        self.assertFalse(result.feasible)
        self.assertIsNone(result.assignment)
        self.assertIsNone(result.migrations)
        self.assertIsNone(result.loads)
        self.assertIsNone(result.imbalance)
        self.assertIsNone(result.migrated_count)

    def test_all_existing_devices_in_assignment_when_migrating(self):
        existing = [
            AdditionExistingDevice("D1", 5, ("A", "B"), "A"),
            AdditionExistingDevice("D2", 5, ("A", "B"), "B"),
        ]
        new_devices = [Device("N1", 5, ("A", "B"))]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 10, "C": 0}
        )
        self.assertTrue(result.feasible)
        # 所有新旧设备都有相位，负载合计等于功率合计
        self.assertEqual(set(result.assignment), {"D1", "D2", "N1"})
        self.assertEqual(
            sum(result.loads[p] for p in PHASES), 15
        )
        for p in PHASES:
            self.assertLessEqual(result.loads[p], {"A": 10, "B": 10, "C": 0}[p])

    def test_migrations_sorted_by_code(self):
        # 两台原设备都被迫改相：迁移清单按编号排序
        existing = [
            AdditionExistingDevice("Z9", 5, ("A", "B"), "A"),
            AdditionExistingDevice("A0", 5, ("A", "B"), "A"),
        ]
        new_devices = [Device("N1", 10, ("A",))]
        result = solve_device_addition(
            existing, new_devices, {"A": 10, "B": 10, "C": 0}
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, 2)
        self.assertEqual([m.code for m in result.migrations], ["A0", "Z9"])


class DeviceAdditionFuzzTest(unittest.TestCase):
    """与朴素全枚举参照实现做随机对拍。"""

    def _check_against(self, existing, new_devices, capacities):
        result = solve_device_addition(existing, new_devices, capacities)
        expected = brute_force_addition(existing, new_devices, capacities)
        if expected is None:
            self.assertFalse(result.feasible)
            return
        (exp_mig, exp_imb, exp_combo), exp_loads = expected
        self.assertTrue(result.feasible)
        self.assertEqual(result.migrated_count, exp_mig)
        self.assertEqual(result.imbalance, exp_imb)
        self.assertEqual(result.loads, exp_loads)
        combined_codes = [
            item[0]
            for item in sorted(
                [(d.code, d.original_phase) for d in existing]
                + [(d.code, None) for d in new_devices],
                key=lambda item: item[0],
            )
        ]
        actual_combo = tuple(result.assignment[code] for code in combined_codes)
        self.assertEqual(actual_combo, exp_combo)
        # 迁移清单与负载自洽
        for m in result.migrations:
            self.assertNotEqual(m.from_phase, m.to_phase)
        self.assertEqual(len(result.migrations), exp_mig)
        for p in PHASES:
            self.assertLessEqual(result.loads[p], capacities[p])

    def test_against_brute_force(self):
        rng = random.Random(20261001)
        for case in range(400):
            n_old = rng.randint(1, 5)
            n_new = rng.randint(1, 6 - n_old) if n_old < 6 else 1
            existing = []
            for i in range(n_old):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                original_phase = rng.choice(allowed)
                existing.append(
                    AdditionExistingDevice(
                        f"OLD-{i}", rng.randint(1, 20), allowed, original_phase
                    )
                )
            new_devices = [
                Device(
                    f"NEW-{i}",
                    rng.randint(1, 20),
                    tuple(p for p in PHASES if rng.random() < 0.7) or ("A",),
                )
                for i in range(n_new)
            ]
            capacities = {p: rng.randint(0, 60) for p in PHASES}
            self._check_against(existing, new_devices, capacities)

    def test_twelve_devices_performance(self):
        # 12 台（6 旧 6 新）、全相位可接、大容量：最恶劣情形，应快速完成
        existing = [
            AdditionExistingDevice(f"O{i:02d}", 2**i, PHASES, PHASES[i % 3])
            for i in range(6)
        ]
        new_devices = [
            Device(f"N{i:02d}", 2 ** (i + 6), PHASES) for i in range(6)
        ]
        caps = {"A": 10**6, "B": 10**6, "C": 10**6}
        result = solve_device_addition(existing, new_devices, caps)
        self.assertTrue(result.feasible)
        self.assertEqual(len(result.assignment), 12)
        expected = brute_force_addition(existing, new_devices, caps)
        (exp_mig, exp_imb, exp_combo), exp_loads = expected
        self.assertEqual(result.migrated_count, exp_mig)
        self.assertEqual(result.imbalance, exp_imb)
        self.assertEqual(result.loads, exp_loads)
        combined = sorted(
            [(d.code, d.original_phase) for d in existing]
            + [(d.code, None) for d in new_devices],
            key=lambda item: item[0],
        )
        self.assertEqual(
            tuple(result.assignment[code] for code, _ in combined), exp_combo
        )

    def test_twelve_devices_tight_capacity(self):
        # 紧容量下 12 台设备：6 台原设备集中在 A，新设备迫使部分原设备改相
        existing = [
            AdditionExistingDevice(f"O{i:02d}", 1, ("A", "B", "C"), "A")
            for i in range(6)
        ]
        new_devices = [
            Device(f"N{i:02d}", 1, ("A", "B", "C")) for i in range(6)
        ]
        caps = {"A": 4, "B": 4, "C": 4}
        result = solve_device_addition(existing, new_devices, caps)
        self.assertTrue(result.feasible)
        # 12 台功率各 1、三相容量各 4：负载恰为 4/4/4，负载差 0；
        # A 相最多保留 4 台原设备，至少 2 台原设备改相
        self.assertEqual(result.loads, {"A": 4, "B": 4, "C": 4})
        self.assertEqual(result.imbalance, 0)
        self.assertEqual(result.migrated_count, 2)


def brute_force_shift(devices, capacities):
    """双时段错峰规划的朴素全枚举：返回 (目标键, (时段, 相位) 序列, 各时段负载)。"""
    ordered = sorted(devices, key=lambda d: d.code)
    options = [
        [
            (slot, phase)
            for slot in SLOTS
            if slot in d.allowed_slots
            for phase in PHASES
            if phase in d.allowed_phases
        ]
        for d in ordered
    ]
    best = None
    for combo in itertools.product(*options):
        loads = {s: {p: 0 for p in PHASES} for s in SLOTS}
        ok = True
        for (slot, phase), device in zip(combo, ordered):
            loads[slot][phase] += device.power
            if loads[slot][phase] > capacities[phase]:
                ok = False
                break
        if not ok:
            continue
        totals = {s: sum(loads[s].values()) for s in SLOTS}
        imbalances = {
            s: max(loads[s].values()) - min(loads[s].values()) for s in SLOTS
        }
        # itertools.product 按选项顺序产生组合，天然为 (时段, 相位) 序列
        # 字典序；同键保留先遇到的组合即字典序最小方案
        key = (max(totals.values()), max(imbalances.values()))
        if best is None or key < best[0]:
            best = (key, combo, {s: dict(loads[s]) for s in SLOTS})
    return best


class ShiftPlanTest(unittest.TestCase):
    def test_peak_total_then_peak_imbalance(self):
        # 总功率 57，目标 1 下界 ceil(57/2)=29；D3 只能晚(15)、D4 只能早(12)，
        # 唯一达到 32 的时段划分：D1 晚、D2 早（早 32 / 晚 25）
        devices = [
            ShiftDevice("D1", 10, ("A", "B"), ("morning", "evening")),
            ShiftDevice("D2", 20, ("A", "B", "C"), ("morning", "evening")),
            ShiftDevice("D3", 15, ("B", "C"), ("evening",)),
            ShiftDevice("D4", 12, ("A", "C"), ("morning",)),
        ]
        result = solve_shift_plan(devices, {"A": 30, "B": 30, "C": 30})
        self.assertTrue(result.feasible)
        self.assertEqual(result.peak_total_load, 32)
        # 早时段 D2(20) 与 D4(12) 必分两相，最小差 20；晚时段最小差 15
        self.assertEqual(result.peak_imbalance, 20)
        self.assertEqual(
            result.slot_loads,
            {
                "morning": {"A": 20, "B": 0, "C": 12},
                "evening": {"A": 10, "B": 15, "C": 0},
            },
        )
        # 字典序最小：D1=(晚,A)、D2=(早,A)、D3=(晚,B)、D4=(早,C)
        # D4 取 (早,A) 会使早 A 相 32 超容量，故取 C
        self.assertEqual(
            result.assignment,
            {
                "D1": ("evening", "A"),
                "D2": ("morning", "A"),
                "D3": ("evening", "B"),
                "D4": ("morning", "C"),
            },
        )

    def test_single_slot_only(self):
        # 全部设备只允许早时段：晚时段负载恒为 0
        devices = [
            ShiftDevice("Z1", 5, PHASES, ("morning",)),
            ShiftDevice("Z2", 5, PHASES, ("morning",)),
        ]
        result = solve_shift_plan(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.peak_total_load, 10)
        self.assertEqual(result.peak_imbalance, 5)
        self.assertEqual(
            result.slot_loads,
            {
                "morning": {"A": 5, "B": 5, "C": 0},
                "evening": {"A": 0, "B": 0, "C": 0},
            },
        )
        # 字典序最小：Z1->(早,A)、Z2->(早,B)
        self.assertEqual(
            result.assignment,
            {"Z1": ("morning", "A"), "Z2": ("morning", "B")},
        )

    def test_single_device(self):
        result = solve_shift_plan(
            [ShiftDevice("X", 7, ("B",), ("evening",))],
            {"A": 10, "B": 10, "C": 10},
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.assignment, {"X": ("evening", "B")})
        self.assertEqual(
            result.slot_loads,
            {
                "morning": {"A": 0, "B": 0, "C": 0},
                "evening": {"A": 0, "B": 7, "C": 0},
            },
        )
        self.assertEqual(result.peak_total_load, 7)
        self.assertEqual(result.peak_imbalance, 7)

    def test_lex_within_budget_may_use_non_minimal_slot_imbalance(self):
        # 对拍中发现的关键情形：联合峰值由晚时段（13）决定时，早时段可在
        # 13 的预算内放宽容差，换取 DEV-5 处相位 B < C 的字典序更小方案
        devices = [
            ShiftDevice("DEV-0", 8, PHASES, ("morning",)),
            ShiftDevice("DEV-1", 3, PHASES, ("evening",)),
            ShiftDevice("DEV-2", 12, ("B", "C"), ("morning", "evening")),
            ShiftDevice("DEV-3", 16, ("A",), ("evening",)),
            ShiftDevice("DEV-4", 4, ("B",), ("morning",)),
            ShiftDevice("DEV-5", 10, ("B", "C"), ("morning", "evening")),
            ShiftDevice("DEV-6", 8, PHASES, ("morning", "evening")),
        ]
        caps = {"A": 58, "B": 30, "C": 14}
        result = solve_shift_plan(devices, caps)
        expected = brute_force_shift(devices, caps)
        self.assertTrue(result.feasible)
        self.assertEqual(
            (result.peak_total_load, result.peak_imbalance), expected[0]
        )
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), expected[1]
        )
        self.assertEqual(result.slot_loads, expected[2])
        # 早时段负载差为 6（非子集最小值 4），但序列在 DEV-5 处更小
        self.assertEqual(result.slot_loads["morning"], {"A": 8, "B": 14, "C": 8})

    def test_slot_lexicographic_morning_before_evening(self):
        # 两台完全对称的自由设备：镜像时段划分同键，应取时段序列字典序最小
        devices = [
            ShiftDevice("S1", 5, ("A",), ("morning", "evening")),
            ShiftDevice("S2", 5, ("A",), ("morning", "evening")),
        ]
        result = solve_shift_plan(devices, {"A": 10, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        # 总负载较大值最小为 5：一台早一台晚；字典序 S1 早、S2 晚
        self.assertEqual(result.peak_total_load, 5)
        self.assertEqual(
            result.assignment,
            {"S1": ("morning", "A"), "S2": ("evening", "A")},
        )
        self.assertEqual(
            result.slot_loads,
            {
                "morning": {"A": 5, "B": 0, "C": 0},
                "evening": {"A": 5, "B": 0, "C": 0},
            },
        )

    def test_infeasible_capacity(self):
        # 单台设备功率超过两时段任一允许相位容量：无解
        devices = [
            ShiftDevice("BIG", 10, ("A", "B", "C"), ("morning", "evening")),
        ]
        result = solve_shift_plan(devices, {"A": 5, "B": 0, "C": 0})
        self.assertFalse(result.feasible)
        self.assertIsNone(result.assignment)
        self.assertIsNone(result.slot_loads)
        self.assertIsNone(result.peak_total_load)
        self.assertIsNone(result.peak_imbalance)

    def test_infeasible_forced_slot(self):
        # 只能晚时段的设备，其允许相位在晚时段容量内放不下：无解
        devices = [
            ShiftDevice("F1", 8, ("A",), ("evening",)),
            ShiftDevice("F2", 3, ("A",), ("morning",)),
        ]
        result = solve_shift_plan(devices, {"A": 5, "B": 100, "C": 100})
        self.assertFalse(result.feasible)
        self.assertIsNone(result.assignment)

    def test_capacity_shared_across_slots(self):
        # 两时段共用容量：两台只能接 A 的设备功率各 6、容量 A=6，
        # 分处两时段即可（各时段 A 相负载 6 不超容量）
        devices = [
            ShiftDevice("E1", 6, ("A",), ("morning", "evening")),
            ShiftDevice("E2", 6, ("A",), ("morning", "evening")),
        ]
        result = solve_shift_plan(devices, {"A": 6, "B": 0, "C": 0})
        self.assertTrue(result.feasible)
        self.assertEqual(result.peak_total_load, 6)
        self.assertEqual(result.peak_imbalance, 6)
        self.assertEqual(result.slot_loads["morning"]["A"], 6)
        self.assertEqual(result.slot_loads["evening"]["A"], 6)

    def test_device_ids_sorted_as_strings(self):
        devices = [
            ShiftDevice("DEV-2", 4, PHASES, SLOTS),
            ShiftDevice("DEV-10", 4, PHASES, SLOTS),
            ShiftDevice("DEV-1", 4, PHASES, SLOTS),
        ]
        result = solve_shift_plan(devices, {"A": 100, "B": 100, "C": 100})
        self.assertTrue(result.feasible)
        self.assertEqual(result.peak_total_load, 8)
        self.assertEqual(result.peak_imbalance, 4)
        # 字符串排序 DEV-1 < DEV-10 < DEV-2；字典序最小方案为
        # DEV-1=(早,A)、DEV-10=(早,B)、DEV-2=(晚,A)（早 8 / 晚 4，差 4）
        self.assertEqual(
            result.assignment,
            {
                "DEV-1": ("morning", "A"),
                "DEV-10": ("morning", "B"),
                "DEV-2": ("evening", "A"),
            },
        )


class ShiftPlanFuzzTest(unittest.TestCase):
    """错峰规划求解与朴素全枚举做随机对拍。"""

    def test_against_brute_force(self):
        rng = random.Random(20260925)
        for case in range(500):
            n = rng.randint(1, 7)
            devices = []
            for i in range(n):
                allowed = tuple(p for p in PHASES if rng.random() < 0.7) or ("A",)
                slots = tuple(s for s in SLOTS if rng.random() < 0.7) or ("morning",)
                devices.append(ShiftDevice(f"DEV-{i}", rng.randint(1, 20), allowed, slots))
            capacities = {p: rng.randint(0, 60) for p in PHASES}

            expected = brute_force_shift(devices, capacities)
            result = solve_shift_plan(devices, capacities)

            if expected is None:
                self.assertFalse(result.feasible, f"case {case}: 应为无可行解")
                continue

            self.assertTrue(result.feasible, f"case {case}: 应有可行解")
            exp_key, exp_combo, exp_loads = expected
            self.assertEqual(
                (result.peak_total_load, result.peak_imbalance),
                exp_key,
                f"case {case}: 目标键不符",
            )
            self.assertEqual(result.slot_loads, exp_loads, f"case {case}: 负载不符")
            ordered = sorted(devices, key=lambda d: d.code)
            actual_combo = tuple(result.assignment[d.code] for d in ordered)
            self.assertEqual(actual_combo, exp_combo, f"case {case}: 字典序不符")
            # 一致性校验：安排与允许集合、容量自洽
            for device, (slot, phase) in zip(ordered, actual_combo):
                self.assertIn(slot, device.allowed_slots)
                self.assertIn(phase, device.allowed_phases)
            for slot in SLOTS:
                for p in PHASES:
                    self.assertLessEqual(result.slot_loads[slot][p], capacities[p])

    def test_eight_devices_performance(self):
        # 8 台设备、时段与相位全允许、大容量：选项空间最大的最坏情形
        devices = [
            ShiftDevice(f"D{i:02d}", 2**i, PHASES, SLOTS) for i in range(8)
        ]
        caps = {"A": 10**6, "B": 10**6, "C": 10**6}
        result = solve_shift_plan(devices, caps)
        expected = brute_force_shift(devices, caps)
        self.assertTrue(result.feasible)
        self.assertEqual(
            (result.peak_total_load, result.peak_imbalance), expected[0]
        )
        ordered = sorted(devices, key=lambda d: d.code)
        self.assertEqual(
            tuple(result.assignment[d.code] for d in ordered), expected[1]
        )

    def test_eight_devices_tight_capacity_performance(self):
        # 紧容量、受限时段 / 相位的随机 8 台用例（求解器仍应快速完成）
        rng = random.Random(99)
        devices = []
        for i in range(8):
            allowed = tuple(p for p in PHASES if rng.random() < 0.6) or ("A",)
            slots = tuple(s for s in SLOTS if rng.random() < 0.6) or ("morning",)
            devices.append(ShiftDevice(f"DEV-{i}", rng.randint(1, 25), allowed, slots))
        capacities = {"A": 30, "B": 30, "C": 30}
        result = solve_shift_plan(devices, capacities)
        expected = brute_force_shift(devices, capacities)
        if expected is None:
            self.assertFalse(result.feasible)
        else:
            self.assertTrue(result.feasible)
            ordered = sorted(devices, key=lambda d: d.code)
            self.assertEqual(
                (result.peak_total_load, result.peak_imbalance), expected[0]
            )
            self.assertEqual(
                tuple(result.assignment[d.code] for d in ordered), expected[1]
            )


# ---------------------------------------------------------------------------
# 运行功率日志复盘
# ---------------------------------------------------------------------------


def brute_force_replay(devices, capacities, window_start, window_end, events):
    """朴素参照实现：每段独立从头重放全部事件计算负载，再合并超容段。

    返回 (alerts, peak)：alerts 为 (start, end, max_overload) 三元组列表。
    """
    phase_of = {d.code: d.phase for d in devices}
    ordered_events = sorted(events, key=lambda e: e.timestamp)
    points = sorted({window_start, window_end} | {e.timestamp for e in events})
    peak = {p: 0 for p in PHASES}
    alerts = []
    open_alert = None
    for i in range(len(points) - 1):
        t = points[i]
        current = {code: 0 for code in phase_of}
        for event in ordered_events:
            if event.timestamp > t:
                break
            current[event.code] = event.power
        loads = {p: 0 for p in PHASES}
        for code, power in current.items():
            loads[phase_of[code]] += power
        for p in PHASES:
            peak[p] = max(peak[p], loads[p])
        overload = {p: max(0, loads[p] - capacities[p]) for p in PHASES}
        if any(v > 0 for v in overload.values()):
            if open_alert is None:
                open_alert = [t, points[i + 1], overload]
            else:
                open_alert[1] = points[i + 1]
                open_alert[2] = {
                    p: max(open_alert[2][p], overload[p]) for p in PHASES
                }
        elif open_alert is not None:
            alerts.append(tuple(open_alert))
            open_alert = None
    if open_alert is not None:
        alerts.append(tuple(open_alert))
    return alerts, peak


class PowerLogReplayTest(unittest.TestCase):
    DEVICES = [
        PowerLogDevice("D1", "A"),
        PowerLogDevice("D2", "B"),
        PowerLogDevice("D3", "C"),
    ]
    CAPS = {"A": 25, "B": 25, "C": 25}

    def test_alerts_merged_and_peaks(self):
        events = [
            PowerLogEvent("D1", 1100, 20),
            PowerLogEvent("D1", 1200, 30),
            PowerLogEvent("D2", 1300, 30),
            PowerLogEvent("D1", 1400, 0),
            PowerLogEvent("D2", 1500, 10),
            PowerLogEvent("D3", 1600, 40),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(result.peak_loads, {"A": 30, "B": 30, "C": 40})
        self.assertEqual(len(result.alerts), 2)
        # [1200,1500) 三段连续超容合并：A 最大超额 5、B 最大超额 5
        self.assertEqual((result.alerts[0].start, result.alerts[0].end), (1200, 1500))
        self.assertEqual(
            result.alerts[0].max_overload, {"A": 5, "B": 5, "C": 0}
        )
        # [1600,2000) 超容延伸至窗口终点
        self.assertEqual((result.alerts[1].start, result.alerts[1].end), (1600, 2000))
        self.assertEqual(
            result.alerts[1].max_overload, {"A": 0, "B": 0, "C": 15}
        )

    def test_same_timestamp_events_apply_together(self):
        # 同一时刻两台设备的事件批量生效：段内两相同时计入
        events = [
            PowerLogEvent("D1", 1100, 30),
            PowerLogEvent("D2", 1100, 30),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(result.peak_loads, {"A": 30, "B": 30, "C": 0})
        self.assertEqual(len(result.alerts), 1)
        self.assertEqual(
            (result.alerts[0].start, result.alerts[0].end), (1100, 2000)
        )
        self.assertEqual(
            result.alerts[0].max_overload, {"A": 5, "B": 5, "C": 0}
        )

    def test_event_at_window_start(self):
        # 事件时刻等于窗口起点：自窗口起点即生效
        events = [PowerLogEvent("D1", 1000, 30)]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(len(result.alerts), 1)
        self.assertEqual(
            (result.alerts[0].start, result.alerts[0].end), (1000, 2000)
        )

    def test_no_events(self):
        result = solve_power_log_replay(self.DEVICES, self.CAPS, 1000, 2000, [])
        self.assertEqual(result.alerts, ())
        self.assertEqual(result.peak_loads, {"A": 0, "B": 0, "C": 0})

    def test_no_overload_no_alert(self):
        events = [
            PowerLogEvent("D1", 1100, 25),  # 恰好等于容量，不超容
            PowerLogEvent("D2", 1200, 10),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(result.alerts, ())
        self.assertEqual(result.peak_loads, {"A": 25, "B": 10, "C": 0})

    def test_separate_overload_segments_not_merged(self):
        # 两段超容之间隔着正常段：不合并
        events = [
            PowerLogEvent("D1", 1100, 30),
            PowerLogEvent("D1", 1200, 10),
            PowerLogEvent("D1", 1300, 40),
            PowerLogEvent("D1", 1400, 0),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(
            [(a.start, a.end) for a in result.alerts],
            [(1100, 1200), (1300, 1400)],
        )
        self.assertEqual(result.alerts[0].max_overload["A"], 5)
        self.assertEqual(result.alerts[1].max_overload["A"], 15)

    def test_zero_power_event_turns_device_off(self):
        # 功率 0 事件即设备关停，超容区间随之结束
        events = [
            PowerLogEvent("D1", 1100, 30),
            PowerLogEvent("D1", 1200, 0),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(
            [(a.start, a.end) for a in result.alerts], [(1100, 1200)]
        )
        self.assertEqual(result.peak_loads, {"A": 30, "B": 0, "C": 0})

    def test_unordered_events_input(self):
        # 事件无需按时刻顺序给出
        events = [
            PowerLogEvent("D3", 1600, 40),
            PowerLogEvent("D1", 1100, 30),
            PowerLogEvent("D2", 1300, 30),
        ]
        result = solve_power_log_replay(
            self.DEVICES, self.CAPS, 1000, 2000, events
        )
        self.assertEqual(
            [(a.start, a.end) for a in result.alerts], [(1100, 2000)]
        )
        self.assertEqual(
            result.alerts[0].max_overload, {"A": 5, "B": 5, "C": 15}
        )


class PowerLogReplayFuzzTest(unittest.TestCase):
    """复盘求解与朴素逐段重放参照实现做随机对拍。"""

    def test_against_brute_force(self):
        rng = random.Random(20260925)
        for case in range(500):
            n = rng.randint(1, 6)
            devices = [
                PowerLogDevice(f"DEV-{i}", rng.choice(PHASES)) for i in range(n)
            ]
            capacities = {p: rng.randint(0, 40) for p in PHASES}
            window_start = rng.randint(0, 100)
            window_end = window_start + rng.randint(1, 500)
            m = rng.randint(0, 40)
            used = set()
            events = []
            for _ in range(m):
                for _ in range(20):  # 生成互不相同的 (设备, 时刻)
                    code = rng.choice([d.code for d in devices])
                    t = rng.randrange(window_start, window_end)
                    if (code, t) not in used:
                        used.add((code, t))
                        events.append(PowerLogEvent(code, t, rng.randint(0, 60)))
                        break

            expected_alerts, expected_peak = brute_force_replay(
                devices, capacities, window_start, window_end, events
            )
            result = solve_power_log_replay(
                devices, capacities, window_start, window_end, events
            )
            self.assertEqual(
                result.peak_loads, expected_peak, f"case {case}: 峰值不符"
            )
            actual_alerts = [
                (a.start, a.end, a.max_overload) for a in result.alerts
            ]
            self.assertEqual(
                actual_alerts, expected_alerts, f"case {case}: 告警不符"
            )


# ---------------------------------------------------------------------------
# 电缆盘裁切预演
# ---------------------------------------------------------------------------


def brute_force_cable(segments, reels, cut_loss):
    """朴素全枚举参照实现：枚举每段所属盘，返回最优目标键与归属序列或 None。

    目标键为 (启用盘数, 启用盘总长度, 按设备编号排序的盘编号序列)。
    """
    ordered_segments = sorted(segments, key=lambda s: s.code)
    ordered_reels = sorted(reels, key=lambda r: r.code)
    best = None
    for combo in itertools.product(range(len(ordered_reels)), repeat=len(ordered_segments)):
        used = {}
        for i, j in enumerate(combo):
            total, count = used.get(j, (0, 0))
            used[j] = (total + ordered_segments[i].length, count + 1)
        ok = all(
            total + (count - 1) * cut_loss <= ordered_reels[j].length
            for j, (total, count) in used.items()
        )
        if not ok:
            continue
        used_indexes = sorted(used)
        key = (
            len(used_indexes),
            sum(ordered_reels[j].length for j in used_indexes),
            tuple(ordered_reels[j].code for j in combo),
        )
        if best is None or key < best[0]:
            best = (key, combo)
    return best


class CableCuttingTest(unittest.TestCase):
    def test_single_reel_all_segments(self):
        segments = [
            CableSegment("D1", 10),
            CableSegment("D2", 20),
            CableSegment("D3", 20),
        ]
        reels = [CableReel("R1", 100), CableReel("R2", 50)]
        result = solve_cable_cutting(segments, reels, cut_loss=0)
        self.assertTrue(result.feasible)
        # 单盘即可装下全部 50：启用盘数最少为 1，并取最短的可容纳盘 R2(50)
        self.assertEqual(result.reel_count, 1)
        self.assertEqual(result.reel_total_length, 50)
        self.assertEqual(result.assignment, {"D1": "R2", "D2": "R2", "D3": "R2"})
        plan = result.reel_plans[0]
        self.assertEqual(plan.reel_code, "R2")
        self.assertEqual(plan.occupied, 50)
        self.assertEqual(plan.remaining, 0)
        self.assertEqual(
            [c.device_code for c in plan.cuts], ["D1", "D2", "D3"]
        )

    def test_cut_loss_occupied_formula(self):
        # 两段 10、损耗 1：同盘占用 10 + 1（切口）+ 10 = 21，盘长 21 恰好可行
        segments = [CableSegment("D1", 10), CableSegment("D2", 10)]
        self.assertTrue(solve_cable_cutting(segments, [CableReel("R1", 21)], 1).feasible)
        # 盘长 20 时放不下（占用需 21）：无其他盘即无解
        result = solve_cable_cutting(segments, [CableReel("R1", 20)], 1)
        self.assertFalse(result.feasible)
        self.assertIsNone(result.reel_plans)

        # 盘长 22：占用 21，剩余 1
        result = solve_cable_cutting(segments, [CableReel("R1", 22)], 1)
        self.assertTrue(result.feasible)
        self.assertEqual(result.reel_plans[0].occupied, 21)
        self.assertEqual(result.reel_plans[0].remaining, 1)

    def test_segment_too_long_infeasible(self):
        # 单段 99 超过所有盘：不可拼接，无解
        result = solve_cable_cutting(
            [CableSegment("D1", 99)],
            [CableReel("R1", 50), CableReel("R2", 50)],
            0,
        )
        self.assertFalse(result.feasible)

    def test_no_reels_infeasible(self):
        result = solve_cable_cutting([CableSegment("D1", 1)], [], 0)
        self.assertFalse(result.feasible)

    def test_min_reel_count_before_total_length(self):
        # 三段各 5：盘 B(15) 单盘可装全部（盘数 1、总长 15），
        # 盘 A(8) + B 需两盘：盘数目标优先，取单盘 B
        segments = [CableSegment(f"D{i}", 5) for i in range(3)]
        reels = [CableReel("A", 8), CableReel("B", 15)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertTrue(result.feasible)
        self.assertEqual(result.reel_count, 1)
        self.assertEqual(result.reel_total_length, 15)
        self.assertTrue(all(v == "B" for v in result.assignment.values()))

    def test_min_total_length_among_min_count(self):
        # 两段 7 不能同盘（任一盘均 < 14）：必须 2 盘。
        # 候选盘 R1(10)/R2(10)/R3(12)，两盘总长最小为 20（取两个 10 长盘）
        segments = [CableSegment("D1", 7), CableSegment("D2", 7)]
        reels = [
            CableReel("R1", 10),
            CableReel("R2", 10),
            CableReel("R3", 12),
        ]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertEqual(result.reel_count, 2)
        self.assertEqual(result.reel_total_length, 20)
        self.assertEqual(sorted(set(result.assignment.values())), ["R1", "R2"])

    def test_lex_sequence_tie_break(self):
        # 两段 5、两个等长盘 R1/R2 均可单盘装下：盘数 1，序列字典序最小 -> R1,R1
        segments = [CableSegment("D1", 5), CableSegment("D2", 5)]
        reels = [CableReel("R1", 10), CableReel("R2", 10)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertEqual(result.reel_count, 1)
        self.assertEqual(result.assignment, {"D1": "R1", "D2": "R1"})

        # 两段 6 必须分盘：序列字典序最小 -> D1:R1, D2:R2
        segments = [CableSegment("D1", 6), CableSegment("D2", 6)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertEqual(result.reel_count, 2)
        self.assertEqual(result.assignment, {"D1": "R1", "D2": "R2"})

    def test_lex_order_not_prioritize_opened_reel(self):
        # 关键回归：字典序逐位比较盘编号，并非「优先复用已启用盘」。
        # 损耗 2，段 D1..D6 = 7,5,3,8,10,9；盘 R1(7)/R2(12)/R3(17)/
        # R4(1)/R5(13)/R6(14)。最优 4 盘、总长 49。
        # 前四段定为 R1,R3,R5,R5 后：D5=10 时已启用的 R3 放得下（已用 7，
        # 变换容量 19），而未启用的 R2 编号更小但需新开盘；两种走法都能达成
        # 最优 (4,49)。逐位字典序应在第五位选编号更小的 R2（D6 再回 R3），
        # 而非优先复用已启用的 R3 得到 (...,R3,R2)。
        segments = [
            CableSegment("D1", 7),
            CableSegment("D2", 5),
            CableSegment("D3", 3),
            CableSegment("D4", 8),
            CableSegment("D5", 10),
            CableSegment("D6", 9),
        ]
        reels = [
            CableReel("R1", 7),
            CableReel("R2", 12),
            CableReel("R3", 17),
            CableReel("R4", 1),
            CableReel("R5", 13),
            CableReel("R6", 14),
        ]
        result = solve_cable_cutting(segments, reels, cut_loss=2)
        self.assertTrue(result.feasible)
        self.assertEqual(result.reel_count, 4)
        self.assertEqual(result.reel_total_length, 49)
        seq = tuple(
            result.assignment[s.code] for s in sorted(segments, key=lambda s: s.code)
        )
        self.assertEqual(seq, ("R1", "R3", "R5", "R5", "R2", "R3"))

    def test_reel_plans_sorted_with_occupied_remaining(self):
        segments = [CableSegment("D1", 3), CableSegment("D2", 4), CableSegment("D3", 5)]
        reels = [CableReel("B", 10), CableReel("A", 7)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertTrue(result.feasible)
        # 裁切清单按电缆盘编号排序（A 在 B 前）
        self.assertEqual([p.reel_code for p in result.reel_plans], ["A", "B"])
        for plan in result.reel_plans:
            expected_occupied = sum(c.length for c in plan.cuts)
            self.assertEqual(plan.occupied, expected_occupied)
            self.assertEqual(plan.remaining, plan.reel_length - expected_occupied)
            self.assertGreaterEqual(plan.remaining, 0)


class CableCuttingFuzzTest(unittest.TestCase):
    """裁切求解与朴素全枚举参照实现做随机对拍。"""

    def test_against_brute_force(self):
        rng = random.Random(20260926)
        for case in range(400):
            n = rng.randint(1, 5)
            m = rng.randint(0, 6)
            cut_loss = rng.randint(0, 4)
            segments = [
                CableSegment(f"D{i:02d}", rng.randint(1, 15)) for i in range(n)
            ]
            reels = [CableReel(f"R{j:02d}", rng.randint(1, 25)) for j in range(m)]

            expected = brute_force_cable(segments, reels, cut_loss)
            result = solve_cable_cutting(segments, reels, cut_loss)

            if expected is None:
                self.assertFalse(result.feasible, f"case {case}: 应为无解")
                continue
            self.assertTrue(result.feasible, f"case {case}: 应有解")
            self.assertEqual(
                (result.reel_count, result.reel_total_length),
                expected[0][:2],
                f"case {case}: 目标键不符",
            )
            ordered = sorted(segments, key=lambda s: s.code)
            actual_seq = tuple(result.assignment[s.code] for s in ordered)
            self.assertEqual(actual_seq, expected[0][2], f"case {case}: 字典序不符")
            # 自洽校验：占用公式、剩余非负
            for plan in result.reel_plans:
                occupied = sum(c.length for c in plan.cuts) + cut_loss * (
                    len(plan.cuts) - 1
                )
                self.assertEqual(plan.occupied, occupied)
                self.assertEqual(plan.remaining, plan.reel_length - occupied)
                self.assertLessEqual(occupied, plan.reel_length)

    def test_eight_segments_eight_reels_performance(self):
        # 8 段 8 盘、紧容量：状态规模最大的最坏情形
        segments = [CableSegment(f"D{i:02d}", 1) for i in range(8)]
        reels = [CableReel(f"R{j:02d}", 1) for j in range(8)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertTrue(result.feasible)
        self.assertEqual(result.reel_count, 8)
        ordered = sorted(segments, key=lambda s: s.code)
        self.assertEqual(
            tuple(result.assignment[s.code] for s in ordered),
            tuple(f"R{i:02d}" for i in range(8)),
        )

        # 全允许大盘、各段长度为 2 的幂：单盘即可，应快速完成
        segments = [CableSegment(f"D{i:02d}", 2**i) for i in range(8)]
        reels = [CableReel(f"R{j:02d}", 10**9) for j in range(8)]
        result = solve_cable_cutting(segments, reels, 0)
        self.assertTrue(result.feasible)
        self.assertEqual(result.reel_count, 1)
        self.assertTrue(
            all(v == "R00" for v in result.assignment.values())
        )


# ---------------------------------------------------------------------------
# 电缆路由预演
# ---------------------------------------------------------------------------


def _brute_force_cable_routes(devices, edges, phase_starts, node_count):
    """朴素全枚举参照实现：返回 (总长度, 按设备排序的节点序列元组) 或 None。"""
    adj = {u: [] for u in range(node_count)}
    cap = {}
    length = {}
    for e in edges:
        a, b = min(e.u, e.v), max(e.u, e.v)
        adj[a].append(b)
        adj[b].append(a)
        cap[(a, b)] = e.capacity
        length[(a, b)] = e.length
    for u in adj:
        adj[u].sort()

    def edge_key(a, b):
        return (min(a, b), max(a, b))

    def all_paths(start, target):
        results = []

        def dfs(node, visited, nodes):
            if node == target:
                results.append(tuple(nodes))
                return
            for nxt in adj[node]:
                if nxt not in visited:
                    visited.add(nxt)
                    nodes.append(nxt)
                    dfs(nxt, visited, nodes)
                    nodes.pop()
                    visited.remove(nxt)

        dfs(start, {start}, [start])
        return results

    def path_info(nodes):
        total = 0
        ids = []
        for a, b in zip(nodes, nodes[1:]):
            key = edge_key(a, b)
            total += length[key]
            ids.append(key)
        return total, ids

    ordered = sorted(devices, key=lambda d: d.code)
    candidate_paths = []
    for d in ordered:
        starts = phase_starts[d.phase]
        paths = all_paths(starts, d.endpoint)
        if not paths:
            return None
        candidate_paths.append(paths)

    used = {}
    best = None

    def combine(i, total):
        nonlocal best
        if i == len(ordered):
            key = (total, tuple(tuple(p) for p in chosen))
            if best is None or key < best:
                best = key
            return
        for nodes in candidate_paths[i]:
            plen, eids = path_info(nodes)
            if all(used.get(eid, 0) < cap[eid] for eid in eids):
                for eid in eids:
                    used[eid] = used.get(eid, 0) + 1
                chosen.append(nodes)
                combine(i + 1, total + plen)
                chosen.pop()
                for eid in eids:
                    used[eid] -= 1

    chosen = []
    combine(0, 0)
    return best


class CableRoutesBasicTest(unittest.TestCase):
    def _edges(self, specs):
        return [
            CableRouteEdge(u=u, v=v, length=w, capacity=c)
            for u, v, w, c in specs
        ]

    def test_zero_edge_path(self):
        edges = self._edges([(0, 1, 5, 1)])
        devices = [CableRouteDevice("D1", "A", 0)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 1, "C": 1}, node_count=2
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 0)
        self.assertEqual(result.paths[0].nodes, (0,))
        self.assertEqual(result.paths[0].length, 0)
        self.assertEqual([u.occupied for u in result.edge_usage], [0])

    def test_shortest_path_basic(self):
        edges = self._edges([(0, 1, 1, 1), (0, 2, 1, 1), (1, 3, 1, 1), (2, 3, 1, 1)])
        devices = [CableRouteDevice("D1", "A", 3)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=4
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 2)
        self.assertEqual(result.paths[0].nodes, (0, 1, 3))

    def test_capacity_zero_edge_unusable(self):
        edges = self._edges([(0, 1, 1, 0)])
        devices = [CableRouteDevice("D1", "A", 1)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=2
        )
        self.assertFalse(result.feasible)
        self.assertIsNone(result.total_length)
        self.assertIsNone(result.paths)

    def test_disconnected_is_infeasible(self):
        edges = self._edges([(0, 1, 1, 4)])
        devices = [CableRouteDevice("D1", "A", 2)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=3
        )
        self.assertFalse(result.feasible)

    def test_capacity_forces_detour(self):
        edges = self._edges([
            (0, 3, 1, 1),
            (0, 1, 1, 4),
            (1, 2, 1, 4),
            (2, 3, 1, 4),
        ])
        devices = [
            CableRouteDevice("D1", "A", 3),
            CableRouteDevice("D2", "A", 3),
        ]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=4
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 4)
        nodes = {p.code: p.nodes for p in result.paths}
        # 两种搭配总长相同，字典序最小者让 D1 走 (0,1,2,3)、D2 走 (0,3)
        self.assertEqual(nodes["D1"], (0, 1, 2, 3))
        self.assertEqual(nodes["D2"], (0, 3))
        by_edge = {(u.u, u.v): u.occupied for u in result.edge_usage}
        self.assertEqual(by_edge[(0, 3)], 1)
        self.assertEqual(by_edge[(0, 1)], 1)
        self.assertEqual(by_edge[(1, 2)], 1)
        self.assertEqual(by_edge[(2, 3)], 1)
        for usage in result.edge_usage:
            self.assertLessEqual(usage.occupied, usage.capacity)

    def test_same_phase_share_capacity(self):
        edges = self._edges([(0, 1, 1, 2)])
        devices = [CableRouteDevice(f"D{i}", "A", 1) for i in range(1, 4)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=2
        )
        self.assertFalse(result.feasible)

    def test_different_phases_independent_starts(self):
        edges = self._edges([(0, 2, 3, 1), (1, 2, 5, 1)])
        devices = [
            CableRouteDevice("D1", "A", 2),
            CableRouteDevice("D2", "B", 2),
        ]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 1, "C": 0}, node_count=3
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 8)
        nodes = {p.code: p.nodes for p in result.paths}
        self.assertEqual(nodes["D1"], (0, 2))
        self.assertEqual(nodes["D2"], (1, 2))

    def test_tie_break_lexicographic_by_device_order(self):
        edges = self._edges([
            (0, 1, 1, 4),
            (1, 2, 1, 4),
            (0, 3, 1, 4),
            (3, 2, 1, 4),
        ])
        devices = [
            CableRouteDevice("D1", "A", 2),
            CableRouteDevice("D2", "A", 2),
        ]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=4
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 4)
        nodes = {p.code: p.nodes for p in result.paths}
        self.assertEqual(nodes["D1"], (0, 1, 2))
        self.assertEqual(nodes["D2"], (0, 1, 2))

    def test_edges_normalized_and_sorted(self):
        edges = self._edges([(2, 0, 4, 1), (0, 1, 2, 1), (1, 2, 1, 1)])
        devices = [CableRouteDevice("D1", "A", 2)]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 0, "C": 0}, node_count=3
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.total_length, 3)
        self.assertEqual(result.paths[0].nodes, (0, 1, 2))
        self.assertEqual(
            [(u.u, u.v) for u in result.edge_usage], [(0, 1), (0, 2), (1, 2)]
        )
        self.assertEqual([u.occupied for u in result.edge_usage], [1, 0, 1])

    def test_infeasible_due_to_joint_capacity(self):
        edges = self._edges([
            (0, 2, 1, 1),
            (1, 2, 1, 1),
            (2, 3, 1, 1),
        ])
        devices = [
            CableRouteDevice("D1", "A", 3),
            CableRouteDevice("D2", "B", 3),
        ]
        result = solve_cable_routes(
            devices, edges, {"A": 0, "B": 1, "C": 0}, node_count=4
        )
        self.assertFalse(result.feasible)


class CableRoutesRandomTest(unittest.TestCase):
    def test_random_graphs_match_brute_force(self):
        rng = random.Random(20260926)
        checked = 0
        for _ in range(300):
            n = rng.randint(1, 5)
            m_max = min(8, n * (n - 1) // 2)
            m = rng.randint(0, m_max)
            all_pairs = [(u, v) for u in range(n) for v in range(u + 1, n)]
            rng.shuffle(all_pairs)
            edges = [
                CableRouteEdge(u=u, v=v, length=rng.randint(1, 4), capacity=rng.randint(0, 2))
                for u, v in all_pairs[:m]
            ]
            k = rng.randint(1, min(4, max(1, 2 * n)))
            codes = [f"D{i}" for i in range(k)]
            phases = [rng.choice(PHASES) for _ in range(k)]
            endpoints = [rng.randrange(n) for _ in range(k)]
            devices = [
                CableRouteDevice(code, phase, endpoint)
                for code, phase, endpoint in zip(codes, phases, endpoints)
            ]
            phase_starts = {p: rng.randrange(n) for p in PHASES}

            result = solve_cable_routes(devices, edges, phase_starts, node_count=n)
            expected = _brute_force_cable_routes(devices, edges, phase_starts, n)
            if expected is None:
                self.assertFalse(result.feasible)
                continue
            self.assertTrue(result.feasible)
            exp_total, exp_nodes = expected
            self.assertEqual(result.total_length, exp_total)
            self.assertEqual(tuple(p.nodes for p in result.paths), exp_nodes)
            for p in result.paths:
                self.assertEqual(len(p.nodes), len(set(p.nodes)))
            for usage in result.edge_usage:
                self.assertLessEqual(usage.occupied, usage.capacity)
            checked += 1
        self.assertGreater(checked, 50)


# ---------------------------------------------------------------------------
# 检修停机排程预演
# ---------------------------------------------------------------------------


def _brute_force_maintenance(all_devices, windows, total_slots, limit, lower_bounds):
    """朴素全枚举参照实现：返回 (完工时隙, 开始时隙元组) 或 None。

    设备按编号排序枚举开始时隙，校验同时检修上限与各相在线负载下限。
    """
    ordered_windows = sorted(windows, key=lambda w: w.code)
    phase_of = {d.code: d.phase for d in all_devices}
    power_of = {d.code: d.power for d in all_devices}
    base = {p: 0 for p in PHASES}
    for d in all_devices:
        base[d.phase] += d.power
    ranges = [
        list(range(w.earliest_start, w.latest_start + 1)) for w in ordered_windows
    ]
    best = None
    for starts in itertools.product(*ranges):
        completion = max(
            s + w.duration for s, w in zip(starts, ordered_windows)
        )
        ok = True
        for t in range(total_slots):
            down = [
                i
                for i, (s, w) in enumerate(zip(starts, ordered_windows))
                if s <= t < s + w.duration
            ]
            if len(down) > limit:
                ok = False
                break
            loads = dict(base)
            for i in down:
                loads[phase_of[ordered_windows[i].code]] -= power_of[
                    ordered_windows[i].code
                ]
            if any(loads[p] < lower_bounds[p] for p in PHASES):
                ok = False
                break
        if ok:
            key = (completion, tuple(starts))
            if best is None or key < best:
                best = key
    return best


class MaintenanceScheduleBasicTest(unittest.TestCase):
    def _result(self, devices, windows, total_slots=6, limit=1, bounds=None):
        return solve_maintenance_schedule(
            devices,
            windows,
            total_slots=total_slots,
            simultaneous_limit=limit,
            lower_bounds=bounds or {p: 0 for p in PHASES},
        )

    def test_single_device_earliest_start(self):
        devices = [MaintenanceDevice("D1", "A", 10)]
        result = self._result(
            devices, [MaintenanceWindow("D1", 2, 1, 4)], total_slots=6
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.completion_slot, 3)
        item = result.items[0]
        self.assertEqual((item.code, item.start, item.duration, item.finish),
                         ("D1", 1, 2, 3))
        # 停机时隙 1、2 的 A 相负载为 0，其余时隙为 10
        for t, loads in enumerate(result.slot_loads):
            self.assertEqual(loads["A"], 0 if t in (1, 2) else 10)

    def test_unselected_devices_always_online(self):
        devices = [
            MaintenanceDevice("D1", "A", 10),
            MaintenanceDevice("D2", "A", 5),
        ]
        result = self._result(
            devices, [MaintenanceWindow("D1", 1, 0, 2)], total_slots=4
        )
        self.assertTrue(result.feasible)
        # D2 始终在线：停机时隙 A 相负载恰为 5
        self.assertEqual(result.slot_loads[0]["A"], 5)
        self.assertEqual(result.slot_loads[1]["A"], 15)

    def test_makespan_minimized_before_lex(self):
        # D1 时长 3、D2 时长 1，上限 1：串行排程完工最少为 4。
        # 字典序倾向 D1 尽早开始（0），D2 排在 3，完工 4。
        devices = [
            MaintenanceDevice("D1", "A", 1),
            MaintenanceDevice("D2", "B", 1),
        ]
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 3, 0, 1),
                MaintenanceWindow("D2", 1, 0, 3),
            ],
            total_slots=4,
        )
        self.assertTrue(result.feasible)
        self.assertEqual(result.completion_slot, 4)
        starts = {it.code: it.start for it in result.items}
        self.assertEqual(starts, {"D1": 0, "D2": 3})

    def test_lexicographic_tie_break(self):
        # 两台同相设备时长均 1、窗口 [0,1]，上限 1：必占两个时隙，
        # 完工恒为 2；字典序最小开始序列为 (0, 1)。
        devices = [
            MaintenanceDevice("D1", "A", 1),
            MaintenanceDevice("D2", "A", 1),
        ]
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 1, 0, 1),
                MaintenanceWindow("D2", 1, 0, 1),
            ],
            total_slots=2,
        )
        self.assertTrue(result.feasible)
        self.assertEqual([it.start for it in result.items], [0, 1])

    def test_simultaneous_limit_forces_spread(self):
        devices = [
            MaintenanceDevice(f"D{i}", p, 1)
            for i, p in enumerate("ABC", start=1)
        ]
        windows = [
            MaintenanceWindow("D1", 1, 0, 0),
            MaintenanceWindow("D2", 1, 0, 0),
            MaintenanceWindow("D3", 1, 0, 0),
        ]
        # 三台都只能在时隙 0 开始：上限 2 不可行
        result = self._result(devices, windows, total_slots=3, limit=2)
        self.assertFalse(result.feasible)
        self.assertIsNotNone(result.reason)
        # 上限 3 可同时检修
        result = self._result(devices, windows, total_slots=3, limit=3)
        self.assertTrue(result.feasible)
        self.assertEqual(result.completion_slot, 1)

    def test_phase_lower_bound_blocks_overlap(self):
        # 两台 A 相设备功率 6、4（基础负载 10），下限 5：
        # 功率 6 的设备任何时隙停机都会使负载降到 4 < 5 -> 无解
        devices = [
            MaintenanceDevice("D1", "A", 6),
            MaintenanceDevice("D2", "A", 4),
            MaintenanceDevice("X", "B", 9),
        ]
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 1, 0, 1),
                MaintenanceWindow("D2", 1, 0, 1),
            ],
            total_slots=2,
            limit=2,
            bounds={"A": 5, "B": 0, "C": 0},
        )
        self.assertFalse(result.feasible)
        self.assertIn("D1", result.reason)

    def test_phase_lower_bound_forces_separate_slots(self):
        # 功率 4 与 3 的两台 A 相设备（基础 7），下限 4：不得同时停机，
        # 但各自单独停机时负载 3/4 中 D2(3) 单停为 4 可行、D1(4) 单停为 3
        # 不可行 -> 仅 D2 可停机；D1 任何安排都违反下限 -> 无解
        devices = [MaintenanceDevice("D1", "A", 4), MaintenanceDevice("D2", "A", 3)]
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 1, 0, 1),
                MaintenanceWindow("D2", 1, 0, 1),
            ],
            total_slots=2,
            limit=2,
            bounds={"A": 4, "B": 0, "C": 0},
        )
        self.assertFalse(result.feasible)

        # 下限放宽为 3：两台可错峰（不可同时），上限 1 强制串行，
        # 字典序最小为 D1=0、D2=1
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 1, 0, 1),
                MaintenanceWindow("D2", 1, 0, 1),
            ],
            total_slots=2,
            limit=1,
            bounds={"A": 3, "B": 0, "C": 0},
        )
        self.assertTrue(result.feasible)
        self.assertEqual([it.start for it in result.items], [0, 1])
        # 时隙 0：D1 停机，A 相仅剩 D2 的 3；时隙 1：D2 停机，仅剩 D1 的 4
        self.assertEqual(result.slot_loads[0]["A"], 3)
        self.assertEqual(result.slot_loads[1]["A"], 4)

    def test_base_load_below_bound_is_infeasible(self):
        # 某相全部设备在线也低于下限（未选设备在该相的情形）
        devices = [MaintenanceDevice("D1", "A", 2), MaintenanceDevice("X", "B", 1)]
        result = self._result(
            devices,
            [MaintenanceWindow("D1", 1, 0, 1)],
            total_slots=2,
            limit=1,
            bounds={"A": 3, "B": 0, "C": 0},
        )
        self.assertFalse(result.feasible)
        self.assertIn("全部设备在线", result.reason)

    def test_total_demand_exceeds_capacity(self):
        devices = [
            MaintenanceDevice("D1", "A", 1),
            MaintenanceDevice("D2", "B", 1),
            MaintenanceDevice("D3", "C", 1),
        ]
        # 总需求 3 个设备·时隙 > 上限 1 × 2 时隙
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 1, 0, 1),
                MaintenanceWindow("D2", 1, 0, 1),
                MaintenanceWindow("D3", 1, 0, 1),
            ],
            total_slots=2,
            limit=1,
        )
        self.assertFalse(result.feasible)
        self.assertIn("同时检修上限", result.reason)

    def test_slot_loads_cover_all_slots_and_respect_bounds(self):
        devices = [
            MaintenanceDevice("D1", "A", 10),
            MaintenanceDevice("D2", "B", 20),
            MaintenanceDevice("X", "B", 5),
        ]
        result = self._result(
            devices,
            [
                MaintenanceWindow("D1", 2, 0, 3),
                MaintenanceWindow("D2", 1, 0, 3),
            ],
            total_slots=5,
            limit=2,
            bounds={"A": 0, "B": 5, "C": 0},
        )
        self.assertTrue(result.feasible)
        self.assertEqual(len(result.slot_loads), 5)
        for loads in result.slot_loads:
            self.assertGreaterEqual(loads["A"], 0)
            self.assertGreaterEqual(loads["B"], 5)
            self.assertEqual(loads["C"], 0)


class MaintenanceScheduleRandomTest(unittest.TestCase):
    def test_random_instances_match_brute_force(self):
        rng = random.Random(20260926)
        checked = 0
        for _ in range(400):
            n = rng.randint(1, 6)
            total_slots = rng.randint(1, 8)
            limit = rng.randint(1, 3)
            codes = [f"D{i:02d}" for i in range(n)]
            devices = [
                MaintenanceDevice(code, rng.choice(PHASES), rng.randint(1, 8))
                for code in codes
            ]
            windows = []
            for device in devices:
                duration = rng.randint(1, min(3, total_slots))
                earliest = rng.randint(0, total_slots - duration)
                latest = rng.randint(earliest, total_slots - duration)
                windows.append(
                    MaintenanceWindow(device.code, duration, earliest, latest)
                )
            # 只选 1~n 台（保持编号顺序），至少 1 台
            k = rng.randint(1, n)
            selected = windows[:k]
            bounds = {p: rng.choice([0, 0, 0, 2, 6]) for p in PHASES}

            result = solve_maintenance_schedule(
                devices,
                selected,
                total_slots=total_slots,
                simultaneous_limit=limit,
                lower_bounds=bounds,
            )
            expected = _brute_force_maintenance(
                devices, selected, total_slots, limit, bounds
            )
            if expected is None:
                self.assertFalse(result.feasible)
                self.assertIsNone(result.completion_slot)
                self.assertIsNone(result.items)
                continue
            self.assertTrue(result.feasible)
            exp_completion, exp_starts = expected
            self.assertEqual(result.completion_slot, exp_completion)
            self.assertEqual(
                tuple(item.start for item in result.items), exp_starts
            )
            # 逐时隙负载与约束复核
            base = {p: 0 for p in PHASES}
            for d in devices:
                base[d.phase] += d.power
            down_count = [0] * total_slots
            for item in result.items:
                for t in range(item.start, item.finish):
                    down_count[t] += 1
            for t, loads in enumerate(result.slot_loads):
                self.assertLessEqual(down_count[t], limit)
                expected_loads = dict(base)
                for item in result.items:
                    if item.start <= t < item.finish:
                        expected_loads[item.phase] -= item.power
                self.assertEqual(loads, expected_loads)
                for p in PHASES:
                    self.assertGreaterEqual(loads[p], bounds[p])
            checked += 1
        self.assertGreater(checked, 50)


def _brute_force_meter(devices, snapshots):
    """朴素全枚举参照实现：返回 (最大误差, 误差总和, 通道序列, 底载序列)。

    枚举全部 6 种通道对应，并枚举各相 0..最大读数 的全部底载组合（底载超过
    最大读数只会令所有误差单调变大，不可能最优）。
    """
    phase_of = {d.code: d.phase for d in devices}
    power_of = {d.code: d.power for d in devices}
    online_loads = []
    for snap in snapshots:
        row = {p: 0 for p in PHASES}
        for code in snap.online:
            row[phase_of[code]] += power_of[code]
        online_loads.append(row)
    max_reading = max(
        reading for snap in snapshots for reading in snap.readings
    )
    best = None
    for perm in itertools.permutations((1, 2, 3)):
        for bases in itertools.product(range(max_reading + 1), repeat=3):
            max_err = 0
            total_err = 0
            for s, snap in enumerate(snapshots):
                for i, p in enumerate(PHASES):
                    predicted = online_loads[s][p] + bases[i]
                    err = abs(snap.readings[perm[i] - 1] - predicted)
                    max_err = max(max_err, err)
                    total_err += err
            key = (max_err, total_err, perm, bases)
            if best is None or key < best:
                best = key
    return best


class MeterCalibrationTest(unittest.TestCase):
    def _assert_snapshot_consistency(self, devices, snapshots, result):
        phase_of = {d.code: d.phase for d in devices}
        power_of = {d.code: d.power for d in devices}
        phase_of_channel = {
            channel: p for p, channel in result.channel_mapping.items()
        }
        self.assertEqual(
            sorted(phase_of_channel), [1, 2, 3]
        )  # 通道编号恰为 1/2/3
        max_err = total_err = 0
        for snap, item in zip(snapshots, result.snapshots):
            row = {p: 0 for p in PHASES}
            for code in snap.online:
                row[phase_of[code]] += power_of[code]
            for channel in (1, 2, 3):
                p = phase_of_channel[channel]
                predicted = row[p] + result.base_loads[p]
                self.assertEqual(item.predicted[channel - 1], predicted)
                err = abs(snap.readings[channel - 1] - predicted)
                self.assertEqual(item.errors[channel - 1], err)
                max_err = max(max_err, err)
                total_err += err
        self.assertEqual(result.max_error, max_err)
        self.assertEqual(result.total_error, total_err)

    def test_perfect_fit_identity_mapping(self):
        devices = [
            MeterDevice("D1", "A", 10),
            MeterDevice("D2", "B", 20),
            MeterDevice("D3", "C", 30),
        ]
        snapshots = [
            MeterSnapshot(frozenset({"D1", "D2", "D3"}), (10, 20, 30)),
            MeterSnapshot(frozenset({"D1"}), (10, 0, 0)),
            MeterSnapshot(frozenset({"D2", "D3"}), (0, 20, 30)),
            MeterSnapshot(frozenset(), (0, 0, 0)),
        ]
        result = solve_meter_calibration(devices, snapshots)
        self.assertEqual(result.channel_mapping, {"A": 1, "B": 2, "C": 3})
        self.assertEqual(result.base_loads, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.max_error, 0)
        self.assertEqual(result.total_error, 0)
        for item in result.snapshots:
            self.assertEqual(item.errors, (0, 0, 0))
        self._assert_snapshot_consistency(devices, snapshots, result)

    def test_perfect_fit_permuted_mapping(self):
        devices = [
            MeterDevice("D1", "A", 5),
            MeterDevice("D2", "B", 7),
        ]
        # A 相在通道 3、B 相在通道 2、C 相在通道 1；底载全 0
        snapshots = [
            MeterSnapshot(frozenset({"D1", "D2"}), (0, 7, 5)),
            MeterSnapshot(frozenset({"D1"}), (0, 0, 5)),
            MeterSnapshot(frozenset({"D2"}), (0, 7, 0)),
            MeterSnapshot(frozenset(), (0, 0, 0)),
        ]
        result = solve_meter_calibration(devices, snapshots)
        self.assertEqual(result.channel_mapping, {"A": 3, "B": 2, "C": 1})
        self.assertEqual(result.base_loads, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.max_error, 0)
        self.assertEqual(result.total_error, 0)
        self._assert_snapshot_consistency(devices, snapshots, result)

    def test_noisy_readings_median_base(self):
        devices = [
            MeterDevice("D1", "A", 10),
            MeterDevice("D2", "B", 20),
            MeterDevice("D3", "C", 30),
        ]
        snapshots = [
            MeterSnapshot(frozenset({"D1", "D2", "D3"}), (13, 18, 32)),
            MeterSnapshot(frozenset({"D1", "D2"}), (12, 22, 0)),
            MeterSnapshot(frozenset({"D3"}), (0, 0, 30)),
        ]
        result = solve_meter_calibration(devices, snapshots)
        # 通道 1/2/3 依次对应 A/B/C；d_A=[3,2,0] 取中位底载 2、
        # d_B=[-2,2,0] 底载 0、d_C=[2,0,0] 底载 0；最大误差 2、总和 9
        self.assertEqual(result.channel_mapping, {"A": 1, "B": 2, "C": 3})
        self.assertEqual(result.base_loads, {"A": 2, "B": 0, "C": 0})
        self.assertEqual(result.max_error, 2)
        self.assertEqual(result.total_error, 9)
        self.assertEqual(
            [item.predicted for item in result.snapshots],
            [(12, 20, 30), (12, 20, 0), (2, 0, 30)],
        )
        self.assertEqual(
            [item.errors for item in result.snapshots],
            [(1, 2, 2), (0, 2, 0), (2, 0, 0)],
        )
        self._assert_snapshot_consistency(devices, snapshots, result)

    def test_base_load_non_negative_constraint(self):
        # A 相设备在线时通道 1 读数仅 2（小于功率 10）：底载非负，最佳即底载 0
        devices = [MeterDevice("D1", "A", 10)]
        snapshots = [
            MeterSnapshot(frozenset({"D1"}), (2, 0, 0)),
            MeterSnapshot(frozenset(), (0, 0, 0)),
            MeterSnapshot(frozenset({"D1"}), (2, 0, 0)),
        ]
        result = solve_meter_calibration(devices, snapshots)
        self.assertEqual(result.channel_mapping, {"A": 1, "B": 2, "C": 3})
        self.assertEqual(result.base_loads, {"A": 0, "B": 0, "C": 0})
        self.assertEqual(result.max_error, 8)
        self.assertEqual(result.total_error, 16)
        self.assertEqual(
            [item.errors for item in result.snapshots],
            [(8, 0, 0), (0, 0, 0), (8, 0, 0)],
        )
        self._assert_snapshot_consistency(devices, snapshots, result)

    def test_nonzero_base_load_with_empty_channel_tie(self):
        # A 相真实对应通道 2，底载 5；通道 1/3 恒为 0，空相通道归 B/C 由
        # 通道序列字典序裁决：A->2 固定后 (B,C) 取 (1,3)
        devices = [MeterDevice("D1", "A", 10)]
        snapshots = [
            MeterSnapshot(frozenset({"D1"}), (0, 15, 0)),
            MeterSnapshot(frozenset(), (0, 5, 0)),
            MeterSnapshot(frozenset({"D1"}), (0, 15, 0)),
            MeterSnapshot(frozenset(), (0, 5, 0)),
        ]
        result = solve_meter_calibration(devices, snapshots)
        self.assertEqual(result.channel_mapping, {"A": 2, "B": 1, "C": 3})
        self.assertEqual(result.base_loads, {"A": 5, "B": 0, "C": 0})
        self.assertEqual(result.max_error, 0)
        self.assertEqual(result.total_error, 0)
        self._assert_snapshot_consistency(devices, snapshots, result)


class MeterCalibrationFuzzTest(unittest.TestCase):
    def test_random_instances_match_brute_force(self):
        rng = random.Random(20260926)
        for _ in range(150):
            n = rng.randint(1, 5)
            codes = [f"D{i:02d}" for i in range(n)]
            devices = [
                MeterDevice(code, rng.choice(PHASES), rng.randint(1, 12))
                for code in codes
            ]
            s_count = rng.randint(3, 6)
            snapshots = []
            for _ in range(s_count):
                online = frozenset(
                    code for code in codes if rng.random() < 0.6
                )
                readings = tuple(rng.randint(0, 9) for _ in range(3))
                snapshots.append(MeterSnapshot(online=online, readings=readings))

            result = solve_meter_calibration(devices, snapshots)
            exp_max, exp_total, exp_perm, exp_bases = _brute_force_meter(
                devices, snapshots
            )
            self.assertEqual(result.max_error, exp_max)
            self.assertEqual(result.total_error, exp_total)
            self.assertEqual(
                tuple(result.channel_mapping[p] for p in PHASES), exp_perm
            )
            self.assertEqual(
                tuple(result.base_loads[p] for p in PHASES), exp_bases
            )
            for base in result.base_loads.values():
                self.assertGreaterEqual(base, 0)
            # 预测读数与绝对误差复核
            phase_of = {d.code: d.phase for d in devices}
            power_of = {d.code: d.power for d in devices}
            phase_of_channel = {
                channel: p for p, channel in result.channel_mapping.items()
            }
            for snap, item in zip(snapshots, result.snapshots):
                row = {p: 0 for p in PHASES}
                for code in snap.online:
                    row[phase_of[code]] += power_of[code]
                for channel in (1, 2, 3):
                    p = phase_of_channel[channel]
                    predicted = row[p] + result.base_loads[p]
                    self.assertEqual(item.predicted[channel - 1], predicted)
                    self.assertEqual(
                        item.errors[channel - 1],
                        abs(snap.readings[channel - 1] - predicted),
                    )


if __name__ == "__main__":
    unittest.main()

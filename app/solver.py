"""三相配电最优分配求解器（纯标准库实现，便于独立测试）。

问题：每台设备不可拆分，只能接入其允许集合中的一个相位；
所有设备均须接入且各相负载不超过对应容量。
目标：最小化「三相负载最大值与最小值之差」；
差值相同时，取按设备编号排序后的相位序列字典序最小的方案。

求解方式：按设备编号排序后做深度优先搜索，相位按 A/B/C 顺序展开，
因此完整方案按相位序列的字典序依次产生；仅在差值严格更小时更新最优解，
即可保证同差值下保留字典序最小方案。同时使用容量约束与下界剪枝加速。

扩容问题（solve_capacity_upgrade）：原容量下无可行分配时，保持设备功率与
允许相位不变，逐相增加非负整数容量，使所有设备均可接入。目标依次为：
1) 三相扩容总量最小；2) 单相最大扩容量最小；3) 仍相同时取按设备编号排序的
相位序列字典序最小。枚举所有相位序列（至多 3^12），分两遍 DFS 配合
扩容总量 / 单相扩容量的上下界剪枝求解。

稳健分相预演（solve_robust）：每台设备功率为正整数区间 [min_power, max_power]，
区间内可独立取任意整数。对固定分配，某相负载可独立取遍
[该相 min_power 之和, 该相 max_power 之和] 内的所有整数，因此：
- 稳健可行（任意功率组合下各相均不超容量）⟺ 各相负载上界不超容量；
- 任意功率组合可能产生的最坏负载差
  = max_{L}(max_p L_p - min_p L_p) = max_{p≠q}(上界_p - 下界_q)
  （注意不是「上界最大值 - 下界最小值」：同一相不可能同时取到上界与下界）。
据此归约为与 solve 同构的 DFS：容量约束作用于负载上界，目标函数为上述
有序相异相位对差值的最大值，同值时取按设备编号排序的相位序列字典序最小者。

启动顺序预演（solve_startup_plan）：沿用可行计算记录的固定相位与容量，
每台设备另给定不低于额定功率的启动瞬时功率。设备一台接一台启动：启动瞬间
该设备按启动功率计，此前已启动的设备按额定功率持续运行，启动完成后该设备
亦按额定功率运行；每个启动瞬间与每个稳定状态各相负载均不得超容量。
目标：最小化全过程「三相负载最大值与最小值之差」的峰值；同峰值取设备编号
序列字典序最小的启动顺序。

关键观察：任一启动顺序对应子集 DAG 上 空集→全集 的一条路径——途经节点为
已启动设备集合（稳定状态），途经边为一次启动（瞬时状态）；节点与边的负载差
只取决于集合 / 边本身，与到达路径无关。故「最小化全过程负载差峰值」等价于
子集 DAG 上的 minimax 路径，按子集递推即可（n≤12，2^12 规模瞬时完成）；
同峰值取编号序列字典序最小：先求最优峰值 P*，再自全集反向递推「途经状态
负载差均不超 P* 且满足容量、可达全集」的子集集合，最后自空集出发按设备
编号字典序贪心选边。容量方面：稳定状态负载是最终负载的部分和（记录可行时
自动满足，求解器仍显式校验以独立成立）；启动瞬间需校验
「启动前该相负载 + 启动功率 ≤ 该相容量」（其余相与稳定状态相同）。

单相故障保供预演（solve_phase_fault_rehearsal）：给定一条已有可行分配的
记录与故障相，健康相设备保持原分配不动（其负载构成各健康相的初始负载），
故障相设备只能迁至其允许的健康相（不得使该相超容量）或断开，故障相最终
负载必为零。全部断开总是可行，故问题总有应急方案。目标依次为：
1) 保留设备的总功率最大；2) 再使保留设备数最多；3) 仍同值时，按故障相
设备编号排序，取相位选择序列字典序最小者（A＜B＜C＜断开）。只需对故障相
设备（至多 12 台）做 DFS，每台按「允许的健康相 A→B→C，最后断开」的顺序
展开，故完整方案按选择序列字典序依次产生，仅在 (保留功率, 保留设备数)
严格更优时更新，同值自然保留字典序最小方案；并以剩余设备功率和 / 数量和
做乐观上界剪枝。

新增设备接入预演（solve_device_addition）：对已有可行分配的记录提交一批
新设备（沿用编号、功率与允许相位规则，新旧合计不超过 12 台且编号互不重复），
保持原容量不变，新旧设备均须接入其允许相位且各相不超容量；原设备可改相
（迁移），也可保持原相位。目标依次为：1) 改相的原设备台数最少；
2) 三相负载最大值与最小值之差最小；3) 按全部设备编号排序的相位序列字典序
最小。搜索结构与 solve 相同：全部设备（新 + 旧）按编号排序后 DFS，相位按
A/B/C 展开，完整方案按相位序列字典序依次产生；目标键为 (改相台数, 负载差)，
仅严格更优才更新，同键时先枚举到的方案字典序最小。剪枝：容量约束；改相
台数超过当前最优即剪（改相台数只增不减）；改相台数持平最优时沿用 solve 的
负载差下界剪枝（此时改相台数与负载差均不可能再严格更优）。

双时段错峰接入规划（solve_shift_plan）：每台设备恰选一个允许运行时段
（早 morning / 晚 evening）与一个允许相位，两时段共用同一组 A/B/C 相容量，
各时段各相负载均不得超容量。目标依次为：1) 两时段总负载（三相之和）的
较大值最小；2) 两时段「三相负载最大值与最小值之差」的较大值最小；
3) 按设备编号排序的 (时段, 相位) 序列字典序最小（早＜晚，A＜B＜C）。

求解利用时段与相位的可分解结构：时段分配确定后，两时段的相位分配互不影响
（容量约束按时段逐相独立），故先对全部 2^n 个子集分别求解「该子集作为单一
时段设备集合」的相位子问题（与 solve 同构的 DFS，求最小三相负载差；全部
子集的总枚举量为 4^n，n≤8 时仅 65536）；随后按时段序列字典序枚举全部
时段分配（2^n 个掩码，设备须允许对应时段且两时段的相位子问题均可行），
以 (总负载较大值, 负载差较大值) 为目标键、仅严格更优才更新，同键时先
枚举到的时段序列字典序最小。最优时段分配确定后，以最优负载差峰值为各时段
预算，对两时段设备子集分别做「预算内字典序最小」的相位 DFS（相位按 A→B→C
展开，首个满足预算的完整方案即字典序最小）——注意不能简单取各时段最小
负载差的方案：联合目标只要求两时段负载差不超过最优峰值，某时段在预算内
放宽容差可换取字典序更小的相位选择。两时段各自最优的相位子序列交错合并
即 (时段, 相位) 联合序列的字典序最小者：联合序列逐位比较时首个差异位置
必属某一时段，由该时段子序列的字典序最小性保证不被其他同键方案超越。

运行功率日志复盘（solve_power_log_replay）：对已有可行分配的记录，沿用其
设备相位与各相容量，回放窗口内的设备实际功率变更日志。窗口起点所有设备
功率为 0；同一时刻的事件批量生效，段 [t_i, t_{i+1}) 的负载取 t_i 时刻事件
生效后的功率（t_i 依次为窗口起点与各事件时刻，末段延伸至窗口终点）。任一相
负载超过容量即超容；相邻超容段合并为一段告警，报告每段告警的起止时刻与
各相最大超额量，以及全窗口各相峰值负载。事件数不超过 200，按时刻分组后
一次顺序扫描即可完成。

电缆盘裁切预演（solve_cable_cutting）：对设备不超过 8 台且已有可行分配的
计算记录，逐台设备给出一段正整数长度电缆（不可拼接），另给至多 8 个编号唯一、
长度为正整数的库存电缆盘与非负整数切割损耗。同一盘裁出 k 段时占用
「段长之和 + (k-1)·损耗」。做权值变换 w=段长+损耗、容量 C=盘长+损耗后，
占用约束等价于 Σw ≤ C，问题归约为「每个电缆段整体放入一个盘」的装箱：
目标依次为 1) 启用盘数最少；2) 启用盘总长度最短；3) 按设备编号排序的
电缆盘编号序列字典序最小。前两个目标用逐盘 0/1 背包式子集划分 DP 求最优
（设备、盘均不超过 8，状态 2^8、单盘子集枚举总量 3^8，瞬时完成）；
再在最优 (盘数, 总长度) 预算内按设备编号顺序 DFS，盘按编号顺序展开，
首个完整方案即编号序列字典序最小者，配合容量、盘数 / 总长度预算剪枝与
失败状态记忆化。

检修停机排程预演（solve_maintenance_schedule）：对已有可行分配的记录，选择其中
1~6 台设备各安排一次连续停机检修，给出总时隙数 T（时隙编号 0~T-1）、每时隙
同时检修设备数上限 C 与 A/B/C 各相的非负最低在线负载。每台选中设备给定停机
时长（1~3 个时隙）与最早 / 最晚开始时隙（0~11），停机为半开区间 [s, s+d)，
须整体落在窗口内；未选设备始终在线，选中设备在停机区间内不计入所属相负载，
其余时隙按记录功率运行。约束：每时隙停机设备数不超过 C；每时隙各相在线负载
（该相全部设备功率减去停机设备功率）不低于给定下限。目标依次为：
1) 最后完工时隙 max_i(s_i+d_i) 最小；2) 同值时按设备编号排序的开始时隙序列
字典序最小。规模很小（设备不超过 6、每台候选开始时隙不超过 12）：先做若干
整体性必要判定（基础负载低于下限、总停机需求超过 C·T、单设备功率超过该相
可停电余量等），再用「最小候选值优先（MRV）+ 前向检查」的回溯判定给定完工
时限 L 是否可行（候选开始时隙只取决于当前停机预订，后续预订只会令其更难，
故未分配设备当前无候选即可剪枝），对 L 二分求出最小完工时隙；最后在 L* 时限
内按设备编号顺序、开始时隙升序做字典序 DFS（同样带前向检查），首个完整方案
即字典序最小者。

电缆路由预演（solve_cable_routes）：在 1~6 个节点、至多 8 条无向边
（正整数长度、容量 0~4）构成的图上，为至多 4 台设备各选一条自所属相起点
到其终点的无重复节点简单路径（起终点相同用零边路径），各边经过的电缆数
不得超过其容量。目标为 1) 各路径长度之和（总长度）最小；2) 同值时按
设备编号排序、依次比较各路径节点序列取字典序最小者。设备数、节点数与
边数都很小：先对每台设备 DFS 枚举全部简单路径（邻接点按编号升序展开、
到达终点即先记录，路径按节点序列字典序依次产生），再按设备编号做组合
DFS，每条路径候选按字典序展开，首个达到更优总长度的完整方案即字典序
最小者；配合「当前长度 + 剩余设备各自最短路径长度」的总长度乐观下界
剪枝（等长只会落在字典序更靠后的方案上，剪枝安全）与失败状态记忆化。

仪表校准预演（solve_meter_calibration）：对已有可行分配的记录提交 3~8 组快照，
每组给出当时在线的记录内设备与仪表三个通道的非负整数读数。设备沿用记录功率与
固定相位；三通道与 A/B/C 相位一一对应（对应关系未知），每相另有跨快照不变的
非负整数底载。给定通道对应后各相互不影响：对相位 p，令
d_s = 该相对应通道在快照 s 的读数 − 快照 s 该相在线设备功率之和，则拟合为
d_s ≈ b_p（b_p 为非负整数底载）。一级目标（该相最大绝对误差）的最优值
m_p = max(ceil((max d_s − min d_s)/2), −min d_s)（后者来自底载非负约束）；
全局最优最大误差 M* = max_p m_p。二级目标在「各相最大误差不超 M*」的底载区间
[max(0, max d_s − M*), min d_s + M*] 内取绝对误差总和（关于 b 的凸函数，其
无约束最小集为 d_s 的中位数区间）到该区间的投影点，即总和最小的非负整数底载；
该点同时是同值底载集合的最左点。枚举全部 3!=6 种通道对应，以
(最大误差, 误差总和, A/B/C 对应通道序列, A/B/C 底载序列) 为键取字典序最小者。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from math import ceil
from typing import Iterable, Optional

PHASES: tuple[str, str, str] = ("A", "B", "C")


@dataclass(frozen=True)
class Device:
    """待分配设备。"""

    code: str  # 设备唯一编号
    power: int  # 正整数功率
    allowed: tuple[str, ...]  # 可接入相位集合（PHASES 的非空子集）


@dataclass(frozen=True)
class SolveResult:
    """求解结果。feasible 为 False 时其余字段为 None。"""

    feasible: bool
    assignment: Optional[dict[str, str]]  # 设备编号 -> 相位
    loads: Optional[dict[str, int]]  # 相位 -> 负载
    imbalance: Optional[int]  # 最大相负载 - 最小相负载


def solve(devices: Iterable[Device], capacities: dict[str, int]) -> SolveResult:
    """求解最优分配方案。

    :param devices: 设备集合（编号唯一、功率为正整数、允许相位非空）。
    :param capacities: 各相容量，形如 {"A": int, "B": int, "C": int}。
    :return: SolveResult；无可行分配时 feasible=False。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    n = len(ordered)
    powers = [d.power for d in ordered]
    # 每个设备的可接入相位按 A/B/C 固定顺序排列，保证 DFS 按字典序枚举方案
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    caps = {p: capacities[p] for p in PHASES}

    # suffix_addable[i][p]：第 i..n-1 台设备中可接入相位 p 的功率和（剪枝用）
    suffix_addable = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        prev, cur = suffix_addable[i + 1], suffix_addable[i]
        for p in PHASES:
            cur[p] = prev[p] + (powers[i] if p in allowed[i] else 0)

    # suffix_total[i]：第 i..n-1 台设备的功率总和
    suffix_total = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix_total[i] = suffix_total[i + 1] + powers[i]

    loads = {p: 0 for p in PHASES}
    current: list[Optional[str]] = [None] * n
    best_imbalance: Optional[int] = None
    best_assignment: Optional[list[str]] = None

    def dfs(i: int, used: int) -> None:
        nonlocal best_imbalance, best_assignment
        if best_imbalance == 0:
            return  # 已达成理论最优（差值为 0），无需继续搜索
        if i == n:
            values = loads.values()
            imbalance = max(values) - min(values)
            # 仅严格更优才更新：同差值时先枚举到的方案字典序更小
            if best_imbalance is None or imbalance < best_imbalance:
                best_imbalance = imbalance
                best_assignment = current.copy()
            return
        if best_imbalance is not None:
            # 下界剪枝：
            #   最终最大负载 >= max(当前最大负载, 总功率平均值上取整)
            #   最终最小负载 <= min(当前各相负载 + 该相剩余可接入功率)
            remaining = suffix_total[i]
            lb_max = max(max(loads.values()), ceil((used + remaining) / 3))
            ub_min = min(loads[p] + suffix_addable[i][p] for p in PHASES)
            if lb_max - ub_min >= best_imbalance:
                return
        for phase in allowed[i]:
            if loads[phase] + powers[i] <= caps[phase]:
                loads[phase] += powers[i]
                current[i] = phase
                dfs(i + 1, used + powers[i])
                loads[phase] -= powers[i]
                current[i] = None

    dfs(0, 0)

    if best_assignment is None:
        return SolveResult(feasible=False, assignment=None, loads=None, imbalance=None)

    final_loads = {p: 0 for p in PHASES}
    for idx, phase in enumerate(best_assignment):
        final_loads[phase] += powers[idx]
    assignment = {ordered[i].code: best_assignment[i] for i in range(n)}
    return SolveResult(
        feasible=True,
        assignment=assignment,
        loads=final_loads,
        imbalance=best_imbalance,
    )


@dataclass(frozen=True)
class UpgradeResult:
    """扩容求解结果。

    original_capacities：原各相容量；upgrades：各相增加的非负整数容量；
    suggested_capacities：原容量 + 扩容量；assignment：设备编号 -> 相位；
    loads：相位 -> 实际负载。
    """

    original_capacities: dict[str, int]
    upgrades: dict[str, int]
    suggested_capacities: dict[str, int]
    assignment: dict[str, str]
    loads: dict[str, int]
    total_upgrade: int  # 三相扩容总量
    max_upgrade: int  # 单相最大扩容量


def _upgrade_bounds(
    i: int,
    loads: dict[str, int],
    caps: dict[str, int],
    suffix_forced: list[dict[str, int]],
    suffix_free_total: list[int],
) -> tuple[int, int]:
    """返回当前部分分配状态下扩容总量与单相扩容的乐观下界。

    返回 (lb_total, lb_max)：
    lb_total —— 三相扩容总量的下界；
    lb_max   —— 单相扩容量的下界，取 max(被迫超载量, ceil(lb_total/3))。

    后续只允许单一相位的设备所落相位已确定（被迫负载 forced），其超载必须
    扩容承担；其余自由设备（允许集合至少两个相位）的功率总和 F 忽略相位
    限制（视为可任意切分），先填充各相被迫负载之外的空闲容量，填不满的
    部分才必须扩容。忽略自由设备的相位限制只会低估扩容，故为合法下界。
    """
    forced_deficit = 0  # 被迫负载造成的必扩容总量
    spare = 0  # 各相可接纳自由设备功率的空闲容量之和
    forced_max = 0
    for p in PHASES:
        forced = loads[p] + suffix_forced[i][p]
        if forced > caps[p]:
            deficit = forced - caps[p]
            forced_deficit += deficit
            if deficit > forced_max:
                forced_max = deficit
        else:
            spare += caps[p] - forced
    lb_total = forced_deficit + max(0, suffix_free_total[i] - spare)
    return lb_total, max(forced_max, ceil(lb_total / 3))


def solve_capacity_upgrade(
    devices: Iterable[Device], capacities: dict[str, int]
) -> UpgradeResult:
    """在保持设备功率与允许相位不变的前提下，求解最小扩容方案。

    目标依次为：三相扩容总量最小 → 单相最大扩容量最小 →
    按设备编号排序的相位序列字典序最小。扩容后总有可行方案
    （每台设备至少存在一个允许相位，各相扩至足够大即可接入）。

    :param devices: 设备集合（编号唯一、功率为正整数、允许相位非空）。
    :param capacities: 各相原容量，形如 {"A": int, "B": int, "C": int}。
    :return: UpgradeResult。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    n = len(ordered)
    powers = [d.power for d in ordered]
    # 每个设备的可接入相位按 A/B/C 固定顺序排列，保证 DFS 按字典序枚举方案
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    caps = {p: capacities[p] for p in PHASES}

    # suffix_forced[i][p]：第 i..n-1 台设备中只允许相位 p 的设备功率和
    # suffix_free_total[i]：第 i..n-1 台设备中允许集合非单一的设备功率总和
    suffix_forced = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    suffix_free_total = [0] * (n + 1)
    for idx in range(n - 1, -1, -1):
        prev_f, cur_f = suffix_forced[idx + 1], suffix_forced[idx]
        for p in PHASES:
            cur_f[p] = prev_f[p]
            if p in allowed[idx] and len(allowed[idx]) == 1:
                cur_f[p] += powers[idx]
        suffix_free_total[idx] = suffix_free_total[idx + 1] + (
            powers[idx] if len(allowed[idx]) > 1 else 0
        )

    loads = {p: 0 for p in PHASES}
    current: list[Optional[str]] = [None] * n

    # 第一遍：最小化三相扩容总量
    best_total: Optional[int] = None
    root_lb_total, _ = _upgrade_bounds(
        0, loads, caps, suffix_forced, suffix_free_total
    )
    optimal_total_found = False

    def dfs_total(i: int) -> None:
        nonlocal best_total, optimal_total_found
        if optimal_total_found:
            return  # 已命中空状态理论最优下界，且回溯由各层正常完成
        lb_total, _ = _upgrade_bounds(
            i, loads, caps, suffix_forced, suffix_free_total
        )
        # 已无法严格改善当前最优（下界不会随分配下降，剪枝安全）
        if best_total is not None and lb_total >= best_total:
            return
        if i == n:
            total = sum(max(0, loads[p] - caps[p]) for p in PHASES)
            if best_total is None or total < best_total:
                best_total = total
                if total == root_lb_total:
                    optimal_total_found = True
            return
        for phase in allowed[i]:
            loads[phase] += powers[i]
            current[i] = phase
            dfs_total(i + 1)
            loads[phase] -= powers[i]
            current[i] = None
            if optimal_total_found:
                break

    dfs_total(0)

    assert best_total is not None  # 扩容后必有解
    target_total = best_total

    # 第二遍：在扩容总量固定最小的方案中，以 (单相最大扩容量, 相位序列) 为
    # 键取字典序最小，即先最小化单相最大扩容、再最小化相位序列。
    best_max: Optional[int] = None
    best_assignment: Optional[list[str]] = None
    best_key: Optional[tuple[int, tuple[str, ...]]] = None

    def dfs_max(i: int) -> None:
        nonlocal best_max, best_assignment, best_key
        lb_total, lb_max = _upgrade_bounds(
            i, loads, caps, suffix_forced, suffix_free_total
        )
        if lb_total > target_total:
            return
        # 仅当子树不可能得到「严格更小」的单相最大扩容时剪枝；
        # lb_max == best_max 时子树仍可能含有同值但字典序更小的方案，不可剪枝
        if best_max is not None and lb_max > best_max:
            return
        if i == n:
            extras = {p: max(0, loads[p] - caps[p]) for p in PHASES}
            if sum(extras.values()) != target_total:
                return
            current_max = max(extras.values())
            # 以 (单相最大扩容, 相位序列) 为键严格更优才更新，
            # 同 max 时保留字典序更小的完整方案
            candidate_key = (current_max, tuple(current))
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_max = current_max
                best_assignment = current.copy()
            return
        for phase in allowed[i]:
            loads[phase] += powers[i]
            current[i] = phase
            dfs_max(i + 1)
            loads[phase] -= powers[i]
            current[i] = None

    dfs_max(0)

    assert best_assignment is not None
    final_loads = {p: 0 for p in PHASES}
    for idx, phase in enumerate(best_assignment):
        final_loads[phase] += powers[idx]
    upgrades = {p: max(0, final_loads[p] - caps[p]) for p in PHASES}
    suggested = {p: caps[p] + upgrades[p] for p in PHASES}
    assignment = {ordered[i].code: best_assignment[i] for i in range(n)}
    return UpgradeResult(
        original_capacities=dict(caps),
        upgrades=upgrades,
        suggested_capacities=suggested,
        assignment=assignment,
        loads=final_loads,
        total_upgrade=sum(upgrades.values()),
        max_upgrade=max(upgrades.values()),
    )


@dataclass(frozen=True)
class RobustDevice:
    """稳健预演设备：功率为正整数区间 [min_power, max_power]。"""

    code: str  # 设备唯一编号
    min_power: int  # 功率下界（正整数）
    max_power: int  # 功率上界（正整数，不小于下界）
    allowed: tuple[str, ...]  # 可接入相位集合（PHASES 的非空子集）


@dataclass(frozen=True)
class RobustResult:
    """稳健预演求解结果。feasible 为 False 时其余字段为 None。

    load_lower / load_upper：各相负载下界 / 上界（该相设备分别取功率
    下界 / 上界之和）；worst_imbalance：任意功率组合下「三相负载最大值
    与最小值之差」可能达到的最大值。
    """

    feasible: bool
    assignment: Optional[dict[str, str]]  # 设备编号 -> 相位
    load_lower: Optional[dict[str, int]]  # 相位 -> 负载下界
    load_upper: Optional[dict[str, int]]  # 相位 -> 负载上界
    worst_imbalance: Optional[int]  # 最坏负载差


def solve_robust(
    devices: Iterable[RobustDevice], capacities: dict[str, int]
) -> RobustResult:
    """求解稳健分相预演：任意功率组合下各相均不超容量，且最坏负载差最小。

    对固定分配，各相负载独立取遍 [下界, 上界] 内的所有整数，故：
    - 稳健可行 ⟺ 各相负载上界（max_power 之和）不超过对应容量；
    - 最坏负载差 = max_{p≠q}(上界_p - 下界_q)
      （max_L(max_p L_p - min_p L_p) = max_{p≠q} max_L(L_p - L_q)，
      同一相不可能同时取到上界与下界，故只取相异相位对）。

    目标：在稳健可行方案中最小化最坏负载差；同值时取按设备编号排序的
    相位序列字典序最小者。搜索结构与 solve 相同：按设备编号排序 DFS、
    相位按 A/B/C 展开、仅严格更优才更新，配合容量约束与下界剪枝。

    :param devices: 设备集合（编号唯一、0 < min_power <= max_power、允许相位非空）。
    :param capacities: 各相容量，形如 {"A": int, "B": int, "C": int}。
    :return: RobustResult；无稳健可行分配时 feasible=False。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    n = len(ordered)
    lows = [d.min_power for d in ordered]
    highs = [d.max_power for d in ordered]
    # 每个设备的可接入相位按 A/B/C 固定顺序排列，保证 DFS 按字典序枚举方案
    allowed = [tuple(p for p in PHASES if p in d.allowed) for d in ordered]
    caps = {p: capacities[p] for p in PHASES}

    # suffix_addable_lo[i][p]：第 i..n-1 台设备中可接入相位 p 的功率下界和（剪枝用）
    suffix_addable_lo = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    # suffix_forced_hi[i][p]：第 i..n-1 台设备中只允许相位 p 的设备功率上界和（剪枝用）
    suffix_forced_hi = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    # suffix_forced_lo[i][p]：同上，功率下界和（剪枝用）
    suffix_forced_lo = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    # suffix_lo[i] / suffix_hi[i]：第 i..n-1 台设备的功率下界 / 上界总和
    suffix_lo = [0] * (n + 1)
    suffix_hi = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        prev_lo, cur_lo = suffix_addable_lo[i + 1], suffix_addable_lo[i]
        prev_fh, cur_fh = suffix_forced_hi[i + 1], suffix_forced_hi[i]
        prev_fl, cur_fl = suffix_forced_lo[i + 1], suffix_forced_lo[i]
        for p in PHASES:
            cur_lo[p] = prev_lo[p] + (lows[i] if p in allowed[i] else 0)
            forced = highs[i] if allowed[i] == (p,) else 0
            cur_fh[p] = prev_fh[p] + forced
            cur_fl[p] = prev_fl[p] + (lows[i] if allowed[i] == (p,) else 0)
        suffix_lo[i] = suffix_lo[i + 1] + lows[i]
        suffix_hi[i] = suffix_hi[i + 1] + highs[i]

    lower = {p: 0 for p in PHASES}
    upper = {p: 0 for p in PHASES}
    current: list[Optional[str]] = [None] * n
    best_imbalance: Optional[int] = None
    best_assignment: Optional[list[str]] = None

    def dfs(i: int, used_lo: int, used_hi: int) -> None:
        nonlocal best_imbalance, best_assignment
        if best_imbalance == 0:
            return  # 已达成理论最优（最坏负载差为 0），无需继续搜索
        if i == n:
            # 最坏负载差 = max_{p≠q}(上界_p - 下界_q)
            imbalance = max(
                upper[p] - lower[q] for p in PHASES for q in PHASES if p != q
            )
            # 仅严格更优才更新：同差值时先枚举到的方案字典序更小
            if best_imbalance is None or imbalance < best_imbalance:
                best_imbalance = imbalance
                best_assignment = current.copy()
            return
        if best_imbalance is not None:
            # 下界剪枝一（相位对）：对任意有序相异相位对 (p, q)，
            #   最终上界_p >= 当前上界_p + 剩余被迫接入 p 的上界和
            #   最终下界_q <= 当前下界_q + 剩余可接入 q 的下界和
            lb = max(
                upper[p] + suffix_forced_hi[i][p] - lower[q] - suffix_addable_lo[i][q]
                for p in PHASES
                for q in PHASES
                if p != q
            )
            # 下界剪枝二（总量平均）：设 p* 为最终上界最大的相位，则
            #   最终上界最大值 >= ceil(上界总和 / 3)
            #   其余两相最终下界的最小值 <= (下界总和 - p* 相下界) / 2
            #     <= (下界总和 - 各相被迫下界的最小值) / 2
            total_lo = used_lo + suffix_lo[i]
            total_hi = used_hi + suffix_hi[i]
            min_forced_lo = min(
                lower[p] + suffix_forced_lo[i][p] for p in PHASES
            )
            lb = max(
                lb,
                ceil(total_hi / 3) - (total_lo - min_forced_lo) // 2,
            )
            if lb >= best_imbalance:
                return
        for phase in allowed[i]:
            # 稳健可行性：任意功率组合下不超容量 ⟺ 负载上界不超容量
            if upper[phase] + highs[i] <= caps[phase]:
                lower[phase] += lows[i]
                upper[phase] += highs[i]
                current[i] = phase
                dfs(i + 1, used_lo + lows[i], used_hi + highs[i])
                lower[phase] -= lows[i]
                upper[phase] -= highs[i]
                current[i] = None

    dfs(0, 0, 0)

    if best_assignment is None:
        return RobustResult(
            feasible=False,
            assignment=None,
            load_lower=None,
            load_upper=None,
            worst_imbalance=None,
        )

    final_lower = {p: 0 for p in PHASES}
    final_upper = {p: 0 for p in PHASES}
    for idx, phase in enumerate(best_assignment):
        final_lower[phase] += lows[idx]
        final_upper[phase] += highs[idx]
    assignment = {ordered[i].code: best_assignment[i] for i in range(n)}
    return RobustResult(
        feasible=True,
        assignment=assignment,
        load_lower=final_lower,
        load_upper=final_upper,
        worst_imbalance=best_imbalance,
    )


@dataclass(frozen=True)
class StartupDevice:
    """启动顺序规划的设备：接入相位固定（沿用原计算记录）。"""

    code: str  # 设备唯一编号
    phase: str  # 固定接入相位（A/B/C）
    rated_power: int  # 额定功率（正整数）
    startup_power: int  # 启动瞬时功率（正整数，不低于额定功率）


@dataclass(frozen=True)
class StartupStepInfo:
    """启动顺序中的一步：某台设备的启动瞬间与其后的稳定状态。"""

    code: str  # 设备编号
    phase: str  # 接入相位
    rated_power: int  # 额定功率
    startup_power: int  # 启动瞬时功率
    transient_loads: dict[str, int]  # 启动瞬间各相负载
    transient_imbalance: int  # 启动瞬间负载差
    steady_loads: dict[str, int]  # 启动完成后各相稳定负载
    steady_imbalance: int  # 稳定状态负载差


@dataclass(frozen=True)
class StartupPlanResult:
    """启动顺序预演结果。feasible 为 False 时其余字段为 None。"""

    feasible: bool
    order: Optional[tuple[str, ...]]  # 启动顺序（设备编号）
    steps: Optional[tuple[StartupStepInfo, ...]]  # 逐步瞬时 / 稳定负载
    peak_imbalance: Optional[int]  # 全过程三相负载差峰值


def solve_startup_plan(
    devices: Iterable[StartupDevice], capacities: dict[str, int]
) -> StartupPlanResult:
    """求解安全启动顺序：全过程负载差峰值最小，同峰值取编号序列字典序最小。

    设备一台接一台启动，接入相位固定。启动瞬间该设备按启动功率计，此前已
    启动的设备按额定功率持续运行；启动完成后该设备亦按额定功率运行。每个
    启动瞬间与每个稳定状态各相负载均不得超容量。无安全顺序时返回
    feasible=False。

    求解结构（详见模块 docstring）：启动顺序与子集 DAG 上 空集→全集 的路径
    一一对应，节点 / 边的负载差与到达路径无关，故最小化峰值等价于 minimax
    路径，按子集递推；再据最优峰值反向求可达全集的子集集合，自空集按设备
    编号字典序贪心选出字典序最小的最优顺序。

    :param devices: 设备集合（编号唯一、相位固定、0 < 额定功率 <= 启动功率）。
    :param capacities: 各相容量，形如 {"A": int, "B": int, "C": int}。
    :return: StartupPlanResult；无安全启动顺序时 feasible=False。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    n = len(ordered)
    phase_of = [d.phase for d in ordered]
    rated = [d.rated_power for d in ordered]
    startup = [d.startup_power for d in ordered]
    caps = {p: capacities[p] for p in PHASES}

    size = 1 << n
    full = size - 1

    # steady_loads[mask]：已启动集合为 mask 时的稳定各相负载（额定功率部分和）
    steady_loads: list[dict[str, int]] = [
        {p: 0 for p in PHASES} for _ in range(size)
    ]
    steady_imb = [0] * size  # 各稳定状态的负载差
    steady_ok = [True] * size  # 各稳定状态是否满足容量
    for mask in range(1, size):
        lsb = mask & (-mask)
        i = lsb.bit_length() - 1
        prev = steady_loads[mask ^ lsb]
        cur = dict(prev)
        cur[phase_of[i]] += rated[i]
        steady_loads[mask] = cur
        steady_imb[mask] = max(cur.values()) - min(cur.values())
        steady_ok[mask] = all(cur[p] <= caps[p] for p in PHASES)

    def transient(mask: int, i: int) -> tuple[dict[str, int], int]:
        """状态 mask 下启动设备 i 的瞬时各相负载与负载差。"""
        cur = dict(steady_loads[mask])
        cur[phase_of[i]] += startup[i]
        return cur, max(cur.values()) - min(cur.values())

    def edge_ok(mask: int, i: int) -> bool:
        """启动瞬间容量校验：仅该设备所在相负载变化，其余相同稳定状态。"""
        p = phase_of[i]
        return steady_loads[mask][p] + startup[i] <= caps[p]

    # dist[mask]：到达 mask 的全过程负载差峰值的最小值；None 表示不可达。
    # 路径代价为途经节点（稳定状态）与边（启动瞬间）负载差的最大值（minimax）；
    # mask 的前驱均小于 mask，按整数序递推即可。
    dist: list[Optional[int]] = [None] * size
    dist[0] = 0
    for mask in range(1, size):
        if not steady_ok[mask]:
            continue
        best: Optional[int] = None
        m = mask
        while m:
            lsb = m & (-m)
            i = lsb.bit_length() - 1
            m ^= lsb
            prev_mask = mask ^ lsb
            if dist[prev_mask] is None or not edge_ok(prev_mask, i):
                continue
            _, t_imb = transient(prev_mask, i)
            candidate = max(dist[prev_mask], t_imb)
            if best is None or candidate < best:
                best = candidate
        if best is not None:
            dist[mask] = max(best, steady_imb[mask])

    peak = dist[full]
    if peak is None:
        return StartupPlanResult(
            feasible=False, order=None, steps=None, peak_imbalance=None
        )

    # can[mask]：自 mask 出发，途经状态负载差均不超 peak 且满足容量，可达全集
    can = [False] * size
    can[full] = True
    for mask in range(full - 1, -1, -1):
        if not steady_ok[mask]:
            continue
        for i in range(n):
            bit = 1 << i
            if mask & bit:
                continue
            nxt = mask | bit
            if not can[nxt] or not edge_ok(mask, i):
                continue
            _, t_imb = transient(mask, i)
            if t_imb <= peak and steady_imb[nxt] <= peak:
                can[mask] = True
                break

    # 自空集出发按设备编号字典序贪心：每步选取后缀仍可完成的最小编号设备，
    # 所得启动顺序即为同峰值下编号序列字典序最小者
    order_idx: list[int] = []
    mask = 0
    while mask != full:
        for i in range(n):  # 设备已按编号排序，即按编号序列字典序尝试
            bit = 1 << i
            if mask & bit:
                continue
            nxt = mask | bit
            if not can[nxt] or not edge_ok(mask, i):
                continue
            _, t_imb = transient(mask, i)
            if t_imb <= peak and steady_imb[nxt] <= peak:
                order_idx.append(i)
                mask = nxt
                break
        else:  # can[0] 为真时必然每步可选，不会走到这里
            raise AssertionError("贪心构造启动顺序失败：无可行后继设备")

    steps = []
    mask = 0
    for i in order_idx:
        t_loads, t_imb = transient(mask, i)
        mask |= 1 << i
        steps.append(
            StartupStepInfo(
                code=ordered[i].code,
                phase=phase_of[i],
                rated_power=rated[i],
                startup_power=startup[i],
                transient_loads=t_loads,
                transient_imbalance=t_imb,
                steady_loads=dict(steady_loads[mask]),
                steady_imbalance=steady_imb[mask],
            )
        )
    return StartupPlanResult(
        feasible=True,
        order=tuple(ordered[i].code for i in order_idx),
        steps=tuple(steps),
        peak_imbalance=peak,
    )


# ---------------------------------------------------------------------------
# 单相故障保供预演
# ---------------------------------------------------------------------------

# 相位选择的字典序：A＜B＜C＜断开（断开用 "D" 内部标记）
_DISCONNECT: str = "D"


@dataclass(frozen=True)
class FaultRehearsalDevice:
    """单相故障预演输入设备（沿用可行计算记录的功率、允许相位与原分配）。"""

    code: str  # 设备唯一编号
    power: int  # 正整数功率
    allowed: tuple[str, ...]  # 可接入相位集合（PHASES 的非空子集）
    original_phase: str  # 记录中的原接入相位（A/B/C）


@dataclass(frozen=True)
class FaultRehearsalMigration:
    """一台故障相设备的迁移结果。"""

    code: str  # 设备编号
    power: int  # 设备功率
    from_phase: str  # 原接入相位（即故障相）
    to_phase: str  # 迁入的健康相（A/B/C）


@dataclass(frozen=True)
class FaultRehearsalDisconnect:
    """一台被断开的故障相设备。"""

    code: str  # 设备编号
    power: int  # 设备功率
    phase: str  # 原接入相位（即故障相）


@dataclass(frozen=True)
class FaultRehearsalResult:
    """单相故障保供预演结果（断开总是可行，故无 feasible=False 情形）。"""

    fault_phase: str  # 故障相
    capacities: dict[str, int]  # 各相容量（沿用记录）
    original_loads: dict[str, int]  # 故障前各相负载（记录中的分配负载）
    loads: dict[str, int]  # 预演后各相负载（故障相必为零）
    migrations: tuple[FaultRehearsalMigration, ...]  # 迁移的故障相设备（按编号排序）
    disconnected: tuple[FaultRehearsalDisconnect, ...]  # 断开的故障相设备（按编号排序）
    retained_power: int  # 保留设备的总功率（含健康相不动设备）
    retained_count: int  # 保留设备数（含健康相不动设备）
    disconnected_power: int  # 断开设备的总功率
    disconnected_count: int  # 断开设备数
    choice_sequence: tuple[str, ...]  # 按故障相设备编号排序的相位选择序列


def solve_phase_fault_rehearsal(
    devices: Iterable[FaultRehearsalDevice],
    capacities: dict[str, int],
    fault_phase: str,
) -> FaultRehearsalResult:
    """求解单相故障保供预演。

    健康相设备保持原分配不动；故障相设备依次选择「允许接入的健康相（A→B→C）
    或断开」。迁至健康相时该相负载不得超过容量。目标依次为：保留设备总功率
    最大 → 保留设备数最多 → 按故障相设备编号排序的相位选择序列字典序最小
    （A＜B＜C＜断开）。故障相最终负载恒为零；全部断开恒可行。

    :param devices: 设备集合（编号唯一、功率正整数、允许相位非空且含原相位）。
    :param capacities: 各相容量，形如 {"A": int, "B": int, "C": int}。
    :param fault_phase: 故障相（"A"/"B"/"C"）。
    :return: FaultRehearsalResult。
    """
    ordered_all = sorted(devices, key=lambda d: d.code)
    healthy_devices = [d for d in ordered_all if d.original_phase != fault_phase]
    fault_devices = [d for d in ordered_all if d.original_phase == fault_phase]
    healthy_phases = [p for p in PHASES if p != fault_phase]
    caps = {p: capacities[p] for p in PHASES}

    # 故障前各相负载：全部设备按记录中的原相位累加
    original_loads = {p: 0 for p in PHASES}
    for device in ordered_all:
        original_loads[device.original_phase] += device.power

    # 健康相设备保持原分配：构成健康相的初始（不可迁出）负载
    initial_loads = {p: 0 for p in PHASES}
    retained_power_fixed = 0
    for device in healthy_devices:
        initial_loads[device.original_phase] += device.power
        retained_power_fixed += device.power
    retained_count_fixed = len(healthy_devices)

    m = len(fault_devices)
    powers = [d.power for d in fault_devices]
    # 每台故障相设备的可选动作：允许的健康相（按 A/B/C 顺序），末尾为断开
    options: list[list[str]] = []
    for device in fault_devices:
        moves = [p for p in healthy_phases if p in device.allowed]
        options.append(moves + [_DISCONNECT])

    # suffix_power[i] / suffix_count：第 i..m-1 台故障设备的功率和 / 数量（剪枝用）
    suffix_power = [0] * (m + 1)
    for i in range(m - 1, -1, -1):
        suffix_power[i] = suffix_power[i + 1] + powers[i]

    loads = dict(initial_loads)
    current: list[Optional[str]] = [None] * m
    # 最优值（仅统计故障相设备中被保留的部分）：总功率优先，设备数次之
    best_power: Optional[int] = None
    best_count: Optional[int] = None
    best_choices: Optional[list[str]] = None

    def dfs(i: int, kept_power: int, kept_count: int) -> None:
        nonlocal best_power, best_count, best_choices
        if i == m:
            # 仅 (保留功率, 保留设备数) 严格更优才更新；同值时先枚举到的
            # 方案选择序列字典序更小（选项按 A→B→C→断开 顺序展开）
            if (
                best_power is None
                or (kept_power, kept_count) > (best_power, best_count)
            ):
                best_power = kept_power
                best_count = kept_count
                best_choices = current.copy()
            return
        # 乐观上界剪枝：即使剩余故障设备全部保留
        if best_power is not None:
            upper_power = kept_power + suffix_power[i]
            if upper_power < best_power:
                return
            if upper_power == best_power and kept_count + (m - i) < (best_count or 0):
                return
        for choice in options[i]:
            if choice == _DISCONNECT:
                current[i] = choice
                dfs(i + 1, kept_power, kept_count)
                current[i] = None
            elif loads[choice] + powers[i] <= caps[choice]:
                loads[choice] += powers[i]
                current[i] = choice
                dfs(i + 1, kept_power + powers[i], kept_count + 1)
                loads[choice] -= powers[i]
                current[i] = None

    dfs(0, 0, 0)

    assert best_choices is not None  # 断开总是可行
    final_loads = dict(initial_loads)
    migrations: list[FaultRehearsalMigration] = []
    disconnected: list[FaultRehearsalDisconnect] = []
    for idx, choice in enumerate(best_choices):
        device = fault_devices[idx]
        if choice == _DISCONNECT:
            disconnected.append(
                FaultRehearsalDisconnect(
                    code=device.code, power=device.power, phase=fault_phase
                )
            )
        else:
            final_loads[choice] += powers[idx]
            migrations.append(
                FaultRehearsalMigration(
                    code=device.code,
                    power=device.power,
                    from_phase=fault_phase,
                    to_phase=choice,
                )
            )
    final_loads[fault_phase] = 0

    migrations.sort(key=lambda item: item.code)
    disconnected.sort(key=lambda item: item.code)
    return FaultRehearsalResult(
        fault_phase=fault_phase,
        capacities=dict(caps),
        original_loads=original_loads,
        loads=final_loads,
        migrations=tuple(migrations),
        disconnected=tuple(disconnected),
        retained_power=retained_power_fixed + (best_power or 0),
        retained_count=retained_count_fixed + (best_count or 0),
        disconnected_power=sum(item.power for item in disconnected),
        disconnected_count=len(disconnected),
        choice_sequence=tuple(best_choices),
    )


# ---------------------------------------------------------------------------
# 新增设备接入预演
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdditionExistingDevice:
    """新增设备接入预演中的原设备（沿用可行计算记录的功率、允许相位与原分配）。"""

    code: str  # 设备唯一编号
    power: int  # 正整数功率
    allowed: tuple[str, ...]  # 可接入相位集合（PHASES 的非空子集）
    original_phase: str  # 记录中的原接入相位（A/B/C）


@dataclass(frozen=True)
class AdditionMigration:
    """一台改相的原设备。"""

    code: str  # 设备编号
    power: int  # 设备功率
    from_phase: str  # 原接入相位（A/B/C）
    to_phase: str  # 新接入相位（A/B/C）


@dataclass(frozen=True)
class AdditionResult:
    """新增设备接入预演结果。feasible 为 False 时其余字段为 None。"""

    feasible: bool
    assignment: Optional[dict[str, str]]  # 全部设备（新 + 旧）编号 -> 相位
    migrations: Optional[tuple[AdditionMigration, ...]]  # 改相的原设备（按编号排序）
    loads: Optional[dict[str, int]]  # 相位 -> 负载
    imbalance: Optional[int]  # 最大相负载 - 最小相负载
    migrated_count: Optional[int]  # 改相的原设备台数


def solve_device_addition(
    existing_devices: Iterable[AdditionExistingDevice],
    new_devices: Iterable[Device],
    capacities: dict[str, int],
) -> AdditionResult:
    """求解新增设备接入预演。

    保持原容量不变，新旧设备（合计不超过 12 台、编号互不重复）均须接入其
    允许相位且各相不超容量；原设备可改相（迁移），也可保持原相位。目标
    依次为：1) 改相的原设备台数最少；2) 三相负载最大值与最小值之差最小；
    3) 按全部设备编号排序的相位序列字典序最小。

    求解结构（详见模块 docstring）：全部设备（新 + 旧）按编号排序后 DFS，
    相位按 A/B/C 展开，完整方案按相位序列字典序依次产生；目标键为
    (改相台数, 负载差)，仅严格更优才更新，同键时先枚举到的方案字典序更小。

    :param existing_devices: 原设备集合（编号唯一、允许相位非空且含原相位）。
    :param new_devices: 新设备集合（编号唯一且与原设备不重复、允许相位非空）。
    :param capacities: 各相容量（沿用原记录），形如 {"A": int, "B": int, "C": int}。
    :return: AdditionResult；无可行分配时 feasible=False。
    """
    combined = sorted(
        [
            (d.code, d.power, d.allowed, d.original_phase)
            for d in existing_devices
        ]
        + [(d.code, d.power, d.allowed, None) for d in new_devices],
        key=lambda item: item[0],
    )
    n = len(combined)
    powers = [item[1] for item in combined]
    # 每个设备的可接入相位按 A/B/C 固定顺序排列，保证 DFS 按字典序枚举方案
    allowed = [tuple(p for p in PHASES if p in item[2]) for item in combined]
    # 原设备的原接入相位；新设备为 None（不涉及改相）
    original: list[Optional[str]] = [item[3] for item in combined]
    caps = {p: capacities[p] for p in PHASES}

    # suffix_addable[i][p]：第 i..n-1 台设备中可接入相位 p 的功率和（剪枝用）
    suffix_addable = [{p: 0 for p in PHASES} for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        prev, cur = suffix_addable[i + 1], suffix_addable[i]
        for p in PHASES:
            cur[p] = prev[p] + (powers[i] if p in allowed[i] else 0)

    # suffix_total[i]：第 i..n-1 台设备的功率总和
    suffix_total = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix_total[i] = suffix_total[i + 1] + powers[i]

    loads = {p: 0 for p in PHASES}
    current: list[Optional[str]] = [None] * n
    best_migrations: Optional[int] = None
    best_imbalance: Optional[int] = None
    best_assignment: Optional[list[str]] = None

    def dfs(i: int, used: int, migrations: int) -> None:
        nonlocal best_migrations, best_imbalance, best_assignment
        if best_migrations == 0 and best_imbalance == 0:
            return  # 已达成理论最优（不改相且差值为 0），无需继续搜索
        if i == n:
            values = loads.values()
            imbalance = max(values) - min(values)
            # 目标键 (改相台数, 负载差) 仅严格更优才更新：
            # 同键时先枚举到的方案相位序列字典序更小
            if best_migrations is None or (migrations, imbalance) < (
                best_migrations,
                best_imbalance,
            ):
                best_migrations = migrations
                best_imbalance = imbalance
                best_assignment = current.copy()
            return
        if best_migrations is not None:
            # 改相台数只增不减：超过当前最优即可剪枝
            if migrations > best_migrations:
                return
            if migrations == best_migrations:
                # 改相台数持平最优时，子树内只有负载差严格更小才可能更优，
                # 沿用 solve 的负载差下界剪枝
                remaining = suffix_total[i]
                lb_max = max(max(loads.values()), ceil((used + remaining) / 3))
                ub_min = min(loads[p] + suffix_addable[i][p] for p in PHASES)
                if lb_max - ub_min >= best_imbalance:
                    return
        for phase in allowed[i]:
            if loads[phase] + powers[i] <= caps[phase]:
                moved = 1 if original[i] is not None and phase != original[i] else 0
                loads[phase] += powers[i]
                current[i] = phase
                dfs(i + 1, used + powers[i], migrations + moved)
                loads[phase] -= powers[i]
                current[i] = None

    dfs(0, 0, 0)

    if best_assignment is None:
        return AdditionResult(
            feasible=False,
            assignment=None,
            migrations=None,
            loads=None,
            imbalance=None,
            migrated_count=None,
        )

    final_loads = {p: 0 for p in PHASES}
    for idx, phase in enumerate(best_assignment):
        final_loads[phase] += powers[idx]
    assignment = {combined[i][0]: best_assignment[i] for i in range(n)}
    migrations = tuple(
        AdditionMigration(
            code=combined[i][0],
            power=powers[i],
            from_phase=original[i],
            to_phase=best_assignment[i],
        )
        for i in range(n)
        if original[i] is not None and best_assignment[i] != original[i]
    )
    return AdditionResult(
        feasible=True,
        assignment=assignment,
        migrations=migrations,
        loads=final_loads,
        imbalance=best_imbalance,
        migrated_count=len(migrations),
    )


# ---------------------------------------------------------------------------
# 双时段错峰接入规划
# ---------------------------------------------------------------------------

SLOTS: tuple[str, str] = ("morning", "evening")  # 早、晚


@dataclass(frozen=True)
class ShiftDevice:
    """双时段错峰接入规划的设备。"""

    code: str  # 设备唯一编号
    power: int  # 正整数功率
    allowed_phases: tuple[str, ...]  # 可接入相位集合（PHASES 的非空子集）
    allowed_slots: tuple[str, ...]  # 允许运行时段集合（SLOTS 的非空子集）


@dataclass(frozen=True)
class ShiftResult:
    """双时段错峰接入规划结果。feasible 为 False 时其余字段为 None。

    slot_loads：时段 -> 相位 -> 负载；peak_total_load：两时段总负载
    （三相之和）的较大值；peak_imbalance：两时段「三相负载最大值与
    最小值之差」的较大值。
    """

    feasible: bool
    assignment: Optional[dict[str, tuple[str, str]]]  # 设备编号 -> (时段, 相位)
    slot_loads: Optional[dict[str, dict[str, int]]]  # 时段 -> 相位 -> 负载
    peak_total_load: Optional[int]  # 两时段总负载的较大值
    peak_imbalance: Optional[int]  # 两时段三相负载差的较大值


def solve_shift_plan(
    devices: Iterable[ShiftDevice], capacities: dict[str, int]
) -> ShiftResult:
    """求解双时段错峰接入规划。

    每台设备恰选一个允许时段（早/晚）与一个允许相位；两时段共用同一组
    A/B/C 相容量，各时段各相负载均不得超容量。目标依次为：
    1) 两时段总负载（三相之和）的较大值最小；
    2) 两时段三相负载差（最大值与最小值之差）的较大值最小；
    3) 按设备编号排序的 (时段, 相位) 序列字典序最小（早＜晚，A＜B＜C）。

    求解结构（详见模块 docstring）：时段分配确定后两时段的相位分配互相
    独立，故先对全部 2^n 个子集分别求解单时段相位子问题（与 solve 同构），
    再按时段序列字典序枚举时段分配并取目标键最优者。

    :param devices: 设备集合（编号唯一、功率正整数、允许时段与相位非空）。
    :param capacities: 两时段共用的各相容量，形如 {"A": int, "B": int, "C": int}。
    :return: ShiftResult；无可行方案时 feasible=False。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    n = len(ordered)
    powers = [d.power for d in ordered]
    # 每台设备的允许相位 / 时段按 A→B→C、早→晚固定顺序排列
    allowed = [tuple(p for p in PHASES if p in d.allowed_phases) for d in ordered]
    slots_of = [tuple(s for s in SLOTS if s in d.allowed_slots) for d in ordered]
    caps = {p: capacities[p] for p in PHASES}

    size = 1 << n

    # subset_total[mask]：子集内设备的功率和
    subset_total = [0] * size
    for mask in range(1, size):
        lsb = mask & (-mask)
        i = lsb.bit_length() - 1
        subset_total[mask] = subset_total[mask ^ lsb] + powers[i]

    # 逐子集求解相位子问题：该子集设备在同一时段内、各相不超容量下的
    # 最小三相负载差（结构与 solve 相同，仅需求可行性与最小差值）
    sub_feasible = [False] * size
    sub_imbalance = [0] * size
    sub_feasible[0] = True
    for mask in range(1, size):
        idxs = [i for i in range(n) if mask & (1 << i)]
        m = len(idxs)
        sub_powers = [powers[i] for i in idxs]
        sub_allowed = [allowed[i] for i in idxs]

        # suffix_addable[k][p]：子集第 k..m-1 台设备中可接入相位 p 的功率和
        suffix_addable = [{p: 0 for p in PHASES} for _ in range(m + 1)]
        # suffix_remaining[k]：子集第 k..m-1 台设备的功率总和
        suffix_remaining = [0] * (m + 1)
        for k in range(m - 1, -1, -1):
            for p in PHASES:
                suffix_addable[k][p] = suffix_addable[k + 1][p] + (
                    sub_powers[k] if p in sub_allowed[k] else 0
                )
            suffix_remaining[k] = suffix_remaining[k + 1] + sub_powers[k]

        loads = {p: 0 for p in PHASES}
        best_imb: Optional[int] = None

        def dfs(k: int, used: int) -> None:
            nonlocal best_imb
            if best_imb == 0:
                return  # 已达成理论最优（差值为 0），无需继续搜索
            if k == m:
                values = loads.values()
                imbalance = max(values) - min(values)
                if best_imb is None or imbalance < best_imb:
                    best_imb = imbalance
                return
            if best_imb is not None:
                # 与 solve 相同的负载差下界剪枝
                remaining = suffix_remaining[k]
                lb_max = max(max(loads.values()), ceil((used + remaining) / 3))
                ub_min = min(loads[p] + suffix_addable[k][p] for p in PHASES)
                if lb_max - ub_min >= best_imb:
                    return
            for phase in sub_allowed[k]:
                if loads[phase] + sub_powers[k] <= caps[phase]:
                    loads[phase] += sub_powers[k]
                    dfs(k + 1, used + sub_powers[k])
                    loads[phase] -= sub_powers[k]

        dfs(0, 0)
        if best_imb is not None:
            sub_feasible[mask] = True
            sub_imbalance[mask] = best_imb

    # 按时段序列字典序枚举时段分配：bit (n-1-i) 为 1 表示第 i 台设备排入
    # 晚时段（早=0 < 晚=1），掩码递增即时段序列字典序；目标键严格更优才更新，
    # 同键时先枚举到的时段序列字典序最小
    best_key: Optional[tuple[int, int]] = None
    best_masks: Optional[tuple[int, int]] = None  # (早时段子集, 晚时段子集)
    for slot_mask in range(size):
        morning_mask = 0
        evening_mask = 0
        for i in range(n):
            if slot_mask & (1 << (n - 1 - i)):
                if "evening" not in slots_of[i]:
                    break
                evening_mask |= 1 << i
            else:
                if "morning" not in slots_of[i]:
                    break
                morning_mask |= 1 << i
        else:
            if not (sub_feasible[morning_mask] and sub_feasible[evening_mask]):
                continue
            key = (
                max(subset_total[morning_mask], subset_total[evening_mask]),
                max(sub_imbalance[morning_mask], sub_imbalance[evening_mask]),
            )
            if best_key is None or key < best_key:
                best_key = key
                best_masks = (morning_mask, evening_mask)

    if best_masks is None:
        return ShiftResult(
            feasible=False,
            assignment=None,
            slot_loads=None,
            peak_total_load=None,
            peak_imbalance=None,
        )

    # 最优时段分配下重构相位方案。注意不能简单取各时段「最小负载差」的
    # 字典序最小方案：联合目标只要求两时段负载差不超过最优峰值 best_key[1]，
    # 某时段在预算内可放宽容差以换取字典序更小的相位选择。故以 best_key[1]
    # 为各时段负载差预算，相位按 A→B→C 展开做 DFS，首个满足预算的完整方案
    # 即该时段字典序最小方案；两时段各自最优的交错合并即联合序列字典序最小。
    budget = best_key[1]

    def lex_first_phases(mask: int) -> tuple[str, ...]:
        """子集 mask 的设备在负载差不超 budget 下字典序最小的相位方案。"""
        idxs = [i for i in range(n) if mask & (1 << i)]
        m = len(idxs)
        sub_powers = [powers[i] for i in idxs]
        sub_allowed = [allowed[i] for i in idxs]
        suffix_addable = [{p: 0 for p in PHASES} for _ in range(m + 1)]
        suffix_remaining = [0] * (m + 1)
        for k in range(m - 1, -1, -1):
            for p in PHASES:
                suffix_addable[k][p] = suffix_addable[k + 1][p] + (
                    sub_powers[k] if p in sub_allowed[k] else 0
                )
            suffix_remaining[k] = suffix_remaining[k + 1] + sub_powers[k]

        loads = {p: 0 for p in PHASES}
        current: list[Optional[str]] = [None] * m
        found: Optional[tuple[str, ...]] = None

        def dfs(k: int, used: int) -> None:
            nonlocal found
            if found is not None:
                return
            if k == m:
                values = loads.values()
                if max(values) - min(values) <= budget:
                    found = tuple(current)
                return
            # 负载差下界超过预算即剪枝（与 solve 相同的下界）
            remaining = suffix_remaining[k]
            lb_max = max(max(loads.values()), ceil((used + remaining) / 3))
            ub_min = min(loads[p] + suffix_addable[k][p] for p in PHASES)
            if lb_max - ub_min > budget:
                return
            for phase in sub_allowed[k]:
                if loads[phase] + sub_powers[k] <= caps[phase]:
                    loads[phase] += sub_powers[k]
                    current[k] = phase
                    dfs(k + 1, used + sub_powers[k])
                    loads[phase] -= sub_powers[k]
                    current[k] = None

        dfs(0, 0)
        assert found is not None  # 子集最小负载差不超预算，必有满足预算的方案
        return found

    assignment: dict[str, tuple[str, str]] = {}
    slot_loads = {s: {p: 0 for p in PHASES} for s in SLOTS}
    for slot, mask in zip(SLOTS, best_masks):
        idxs = [i for i in range(n) if mask & (1 << i)]
        for i, phase in zip(idxs, lex_first_phases(mask)):
            assignment[ordered[i].code] = (slot, phase)
            slot_loads[slot][phase] += powers[i]
    return ShiftResult(
        feasible=True,
        assignment=assignment,
        slot_loads=slot_loads,
        peak_total_load=max(sum(slot_loads[s].values()) for s in SLOTS),
        peak_imbalance=max(
            max(slot_loads[s].values()) - min(slot_loads[s].values()) for s in SLOTS
        ),
    )


# ---------------------------------------------------------------------------
# 运行功率日志复盘
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PowerLogDevice:
    """功率日志复盘的设备：接入相位固定（沿用原计算记录）。"""

    code: str  # 设备唯一编号
    phase: str  # 固定接入相位（A/B/C）


@dataclass(frozen=True)
class PowerLogEvent:
    """一条设备实际功率变更事件。"""

    code: str  # 设备编号
    timestamp: int  # 变更时刻（Unix 秒，落在左闭右开窗口内）
    power: int  # 变更后的实际功率（非负整数）


@dataclass(frozen=True)
class PowerLogAlert:
    """一段超容告警：连续存在任一相超容的区间合并结果（左闭右开）。"""

    start: int  # 告警区间起点（Unix 秒）
    end: int  # 告警区间终点（Unix 秒）
    max_overload: dict[str, int]  # 相位 -> 区间内该相最大超额量（未超容相为 0）


@dataclass(frozen=True)
class PowerLogReplayResult:
    """运行功率日志复盘结果。"""

    alerts: tuple[PowerLogAlert, ...]  # 合并后的超容告警（按起点升序）
    peak_loads: dict[str, int]  # 相位 -> 全窗口峰值负载


def solve_power_log_replay(
    devices: Iterable[PowerLogDevice],
    capacities: dict[str, int],
    window_start: int,
    window_end: int,
    events: Iterable[PowerLogEvent],
) -> PowerLogReplayResult:
    """复盘窗口内的设备功率变更日志，汇总超容告警与各相峰值负载。

    窗口起点所有设备功率为 0；同一时刻的事件批量生效，段 [t_i, t_{i+1})
    的负载取 t_i 时刻事件生效后的功率（t_i 依次为窗口起点与各事件时刻，
    末段延伸至窗口终点）。任一相负载超过容量即超容；相邻超容段合并为一段
    告警，给出每段告警的起止时刻与各相最大超额量，以及全窗口各相峰值负载。

    :param devices: 设备集合（编号唯一、相位固定）。
    :param capacities: 各相容量（沿用记录），形如 {"A": int, "B": int, "C": int}。
    :param window_start: 窗口起点（Unix 秒，须早于窗口终点）。
    :param window_end: 窗口终点（Unix 秒）。
    :param events: 功率变更事件（时刻落在左闭右开窗口内、同一设备同一时刻不重复）。
    :return: PowerLogReplayResult。
    """
    phase_of = {d.code: d.phase for d in devices}
    caps = {p: capacities[p] for p in PHASES}

    # 同一时刻的事件批量生效：按时刻分组
    by_time: dict[int, list[PowerLogEvent]] = {}
    for event in events:
        by_time.setdefault(event.timestamp, []).append(event)

    # 段边界：窗口起点 -> 各事件时刻 -> 窗口终点
    # （事件时刻等于窗口起点时不重复计入，起点段直接取事件生效后的功率）
    boundaries = (
        [window_start]
        + [t for t in sorted(by_time) if t != window_start]
        + [window_end]
    )

    current = {code: 0 for code in phase_of}
    peak = {p: 0 for p in PHASES}
    alerts: list[PowerLogAlert] = []
    alert_start: Optional[int] = None  # 正在累积的告警区间起点
    alert_overload = {p: 0 for p in PHASES}  # 正在累积的各相最大超额量

    for i in range(len(boundaries) - 1):
        t = boundaries[i]
        for event in by_time.get(t, ()):
            current[event.code] = event.power
        loads = {p: 0 for p in PHASES}
        for code, power in current.items():
            loads[phase_of[code]] += power
        for p in PHASES:
            if loads[p] > peak[p]:
                peak[p] = loads[p]
        overload = {p: max(0, loads[p] - caps[p]) for p in PHASES}
        if any(overload[p] > 0 for p in PHASES):
            # 超容段：与此前相邻超容段合并（段间首尾相接，区间天然连续）
            if alert_start is None:
                alert_start = t
            for p in PHASES:
                if overload[p] > alert_overload[p]:
                    alert_overload[p] = overload[p]
        elif alert_start is not None:
            # 本段不再超容：告警区间结束于本段起点
            alerts.append(
                PowerLogAlert(
                    start=alert_start,
                    end=t,
                    max_overload=dict(alert_overload),
                )
            )
            alert_start = None
            alert_overload = {p: 0 for p in PHASES}
    if alert_start is not None:  # 超容区间一直延伸至窗口终点
        alerts.append(
            PowerLogAlert(
                start=alert_start,
                end=window_end,
                max_overload=dict(alert_overload),
            )
        )

    return PowerLogReplayResult(alerts=tuple(alerts), peak_loads=peak)


# ---------------------------------------------------------------------------
# 电缆盘裁切预演
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CableSegment:
    """一台设备所需的一整段电缆（不可拼接）。"""

    code: str  # 设备唯一编号
    length: int  # 电缆段长度（正整数）


@dataclass(frozen=True)
class CableReel:
    """一个库存电缆盘。"""

    code: str  # 电缆盘唯一编号
    length: int  # 电缆盘长度（正整数）


@dataclass(frozen=True)
class CableCut:
    """某盘上裁给一台设备的一段电缆。"""

    device_code: str  # 设备编号
    length: int  # 电缆段长度（正整数）


@dataclass(frozen=True)
class CableReelPlan:
    """单个启用盘的裁切清单。"""

    reel_code: str  # 电缆盘编号
    reel_length: int  # 电缆盘原长度
    cuts: tuple[CableCut, ...]  # 裁切清单（按设备编号排序）
    occupied: int  # 占用长度 = 段长之和 + (段数 - 1)·切割损耗
    remaining: int  # 剩余长度 = 盘长 - 占用长度


@dataclass(frozen=True)
class CableCuttingResult:
    """电缆盘裁切预演结果。feasible 为 False 时其余字段为 None。"""

    feasible: bool
    cut_loss: Optional[int]  # 每个相邻切口的切割损耗（非负整数）
    assignment: Optional[dict[str, str]]  # 设备编号 -> 电缆盘编号
    reel_plans: Optional[tuple[CableReelPlan, ...]]  # 各启用盘裁切清单（按盘编号排序）
    reel_count: Optional[int]  # 启用盘数
    reel_total_length: Optional[int]  # 启用盘总长度


def solve_cable_cutting(
    segments: Iterable[CableSegment],
    reels: Iterable[CableReel],
    cut_loss: int,
) -> CableCuttingResult:
    """求解电缆盘裁切预演。

    每台设备需要一整段正整数长度电缆，不可拼接；同一盘裁出 k 段时占用长度为
    「段长之和 + (k-1)·cut_loss」，不得超过盘长。目标依次为：
    1) 启用盘数最少；2) 启用盘总长度最短；3) 按设备编号排序的电缆盘编号
    序列字典序最小。

    权值变换：令 w_i = 段长_i + cut_loss、C_j = 盘长_j + cut_loss，则盘 j 上
    裁出段集合 S 可行 ⟺ Σ_{i∈S} w_i ≤ C_j，即标准的「每件整体放入一箱」
    装箱问题（各箱容量可不同）。

    求解分两步（设备、盘均不超过 8）：
    - 逐盘 0/1 背包式子集划分 DP：reach[j][mask] 表示恰用前 j 个盘（每个盘
      至多一次）能否裁出 mask 中的全部段，转移枚举第 j 个盘承接的非空
      子集 sub ⊆ mask；记录最优 (启用盘数, 启用盘总长度)。
    - 最优 (盘数, 总长度) 预算下，按设备编号排序逐段 DFS，盘按编号顺序
      展开（先已启用且放得下的盘，再未启用的盘），首个完整方案即编号序列
      字典序最小者；配合容量约束、盘数 / 总长度预算剪枝及失败状态记忆化。

    :param segments: 电缆段集合（设备编号唯一、段长为正整数，不超过 8 段）。
    :param reels: 库存电缆盘集合（编号唯一、盘长为正整数，不超过 8 个）。
    :param cut_loss: 每个相邻切口的切割损耗（非负整数）。
    :return: CableCuttingResult；无可行裁切方案时 feasible=False。
    """
    ordered_segments = sorted(segments, key=lambda s: s.code)
    ordered_reels = sorted(reels, key=lambda r: r.code)
    n = len(ordered_segments)
    m = len(ordered_reels)
    weights = [s.length + cut_loss for s in ordered_segments]
    capacities = [r.length + cut_loss for r in ordered_reels]
    reel_lengths = [r.length for r in ordered_reels]

    size = 1 << n
    full = size - 1

    # subset_weight[mask]：子集内段的变换权值之和
    subset_weight = [0] * size
    for mask in range(1, size):
        lsb = mask & (-mask)
        i = lsb.bit_length() - 1
        subset_weight[mask] = subset_weight[mask ^ lsb] + weights[i]

    # 逐盘 0/1 背包式子集划分 DP：
    # dp[mask] = 到达 mask 的最优 (启用盘数, 启用盘总长度)；None 为不可达。
    dp: list[Optional[tuple[int, int]]] = [None] * size
    dp[0] = (0, 0)
    for j in range(m):
        # 倒序更新保证每个盘至多使用一次；同一盘承接的段集合在 fit_masks[j]
        # 内枚举（新增的 sub 与已有 mask 不相交时即取反方向的转移 mask|sub）
        for mask in range(full, -1, -1):
            current = dp[mask]
            if current is None:
                continue
            remaining = full ^ mask
            sub = remaining
            while sub:
                if subset_weight[sub] <= capacities[j]:
                    candidate = (current[0] + 1, current[1] + reel_lengths[j])
                    target = mask | sub
                    if dp[target] is None or candidate < dp[target]:
                        dp[target] = candidate
                sub = (sub - 1) & remaining

    best = dp[full]
    if best is None:
        return CableCuttingResult(
            feasible=False,
            cut_loss=cut_loss,
            assignment=None,
            reel_plans=None,
            reel_count=None,
            reel_total_length=None,
        )
    best_count, best_total = best

    # 预算内按设备编号顺序 DFS 构造字典序最小方案。
    # 状态：已处理前 i 段；loads[j] 为已放入盘 j 的变换权值和（未启用为 -1）。
    # 所有盘严格按编号顺序展开（已启用盘与未启用盘交错比较），故首个满足
    # 最优 (盘数, 总长度) 预算的完整方案即编号序列字典序最小者。
    loads = [-1] * m
    chosen: list[Optional[int]] = [None] * n
    found: Optional[list[int]] = None
    # 失败状态记忆化：(i, tuple(loads)) 无法在预算内补全；启用盘集合由 loads 决定
    dead: set[tuple[int, tuple[int, ...]]] = set()

    def dfs(i: int, used_count: int, used_total: int) -> None:
        nonlocal found
        if found is not None:
            return
        if i == n:
            if used_count == best_count and used_total == best_total:
                found = chosen.copy()
            return
        key = (i, tuple(loads))
        if key in dead:
            return
        remaining_segments = n - i
        # 盘数预算剪枝：最终启用盘数必在 [used_count, used_count + remaining]
        if used_count > best_count:
            dead.add(key)
            return
        # 总长度预算剪枝：后续即使不再启用新盘也已超总长
        if used_total > best_total:
            dead.add(key)
            return
        if used_count < best_count and used_count + remaining_segments < best_count:
            # 剩余段每段至多新开一盘，仍凑不够最优盘数
            dead.add(key)
            return
        w = weights[i]
        # 所有盘严格按编号顺序尝试（已启用盘与未启用盘交错比较）：盘编号
        # 序列按设备编号排序后逐位字典序比较，当前位置选编号更小的盘总是
        # 占优（可行性 / 预算交由后续剪枝与回溯保证），故首个完整方案即
        # 字典序最小者
        for j in range(m):
            if w > capacities[j]:
                continue
            if loads[j] >= 0:
                # 放入已启用盘：不增加盘数与总长度
                if loads[j] + w > capacities[j]:
                    continue
                loads[j] += w
                chosen[i] = j
                dfs(i + 1, used_count, used_total)
                loads[j] -= w
                chosen[i] = None
            else:
                # 启用一个新盘：受盘数 / 总长度预算约束
                new_count = used_count + 1
                new_total = used_total + reel_lengths[j]
                if new_count > best_count or new_total > best_total:
                    continue
                if (
                    new_count < best_count
                    and new_count + (remaining_segments - 1) < best_count
                ):
                    # 剩余段每段至多再新开一盘，仍凑不够最优盘数
                    continue
                loads[j] = w
                chosen[i] = j
                dfs(i + 1, new_count, new_total)
                loads[j] = -1
                chosen[i] = None
            if found is not None:
                return
        dead.add(key)

    dfs(0, 0, 0)

    assert found is not None  # DP 已证明可行，预算内必有完整方案

    # 汇总各启用盘的裁切清单（按盘编号排序），占用 / 剩余长度按原口径计算
    cuts_by_reel: dict[int, list[tuple[str, int]]] = {}
    assignment: dict[str, str] = {}
    for i, j in enumerate(found):
        code = ordered_segments[i].code
        assignment[code] = ordered_reels[j].code
        cuts_by_reel.setdefault(j, []).append((code, ordered_segments[i].length))

    reel_plans: list[CableReelPlan] = []
    for j in sorted(cuts_by_reel, key=lambda idx: ordered_reels[idx].code):
        cuts_tuple = tuple(
            CableCut(device_code=code, length=length)
            for code, length in sorted(cuts_by_reel[j])
        )
        occupied = sum(length for _, length in cuts_by_reel[j]) + cut_loss * (
            len(cuts_by_reel[j]) - 1
        )
        reel_plans.append(
            CableReelPlan(
                reel_code=ordered_reels[j].code,
                reel_length=reel_lengths[j],
                cuts=cuts_tuple,
                occupied=occupied,
                remaining=reel_lengths[j] - occupied,
            )
        )
    return CableCuttingResult(
        feasible=True,
        cut_loss=cut_loss,
        assignment=assignment,
        reel_plans=tuple(reel_plans),
        reel_count=len(reel_plans),
        reel_total_length=sum(reel_lengths[j] for j in cuts_by_reel),
    )

# ---------------------------------------------------------------------------
# 电缆路由预演
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CableRouteEdge:
    """一条无向边（端点按编号小大规范化）。"""

    u: int  # 较小端节点编号
    v: int  # 较大端节点编号
    length: int  # 边长度（正整数）
    capacity: int  # 可同时容纳的电缆数（0~4）


@dataclass(frozen=True)
class CableRouteDevice:
    """电缆路由预演中的一台设备（相位沿用原计算记录）。"""

    code: str  # 设备唯一编号
    phase: str  # 所属相（A/B/C），决定该设备的路径起点
    endpoint: int  # 设备终点节点编号


@dataclass(frozen=True)
class CableRoutePath:
    """一台设备的电缆路径。"""

    code: str  # 设备编号
    phase: str  # 所属相（A/B/C）
    endpoint: int  # 设备终点节点编号
    nodes: tuple[int, ...]  # 路径经过的节点序列（无重复节点；同点时为单节点）
    length: int  # 路径总长度（同点零边路径为 0）


@dataclass(frozen=True)
class CableRouteEdgeUsage:
    """一条边上的电缆占用情况。"""

    u: int  # 较小端节点编号
    v: int  # 较大端节点编号
    length: int  # 边长度
    capacity: int  # 边容量
    occupied: int  # 经该边铺设的电缆数（不超过容量）


@dataclass(frozen=True)
class CableRoutesResult:
    """电缆路由预演结果。feasible 为 False 时其余字段为 None。"""

    feasible: bool
    paths: Optional[tuple[CableRoutePath, ...]]  # 各设备路径（按设备编号排序）
    total_length: Optional[int]  # 各路径长度之和
    edge_usage: Optional[tuple[CableRouteEdgeUsage, ...]]  # 各边占用（按端点编号排序）


def solve_cable_routes(
    devices: Iterable[CableRouteDevice],
    edges: Iterable[CableRouteEdge],
    phase_starts: dict[str, int],
    node_count: int,
) -> CableRoutesResult:
    """求解电缆路由预演。

    在 node_count 个节点、若干无向边（正整数长度、容量 0~4）构成的图上，
    每台设备从其所属相起点走一条无重复节点的简单路径至自身终点，起终点
    相同时使用零边路径；每条边经过的电缆数不得超过其容量。目标依次为：
    1) 各路径长度之和（总长度）最小；2) 总长度相同时，按设备编号排序，
    依次比较各路径节点序列取字典序最小者。

    设备、节点、边的规模都很小（至多 4 / 6 / 8），直接精确枚举：
    - 对每台设备 DFS 枚举全部简单路径：邻接点按编号升序展开、到达终点即
      记录且不再延伸（终点不可能在路径中重复出现），故候选路径按节点
      序列字典序依次产生；容量为 0 的边不参与枚举（任何路径都不得经过）。
    - 再按设备编号做组合 DFS，每台设备的路径候选按字典序展开，首个取得
      更小总长度的完整方案即字典序最小者；以「当前长度 + 剩余设备各自
      最短路径长度」为总长度乐观下界做剪枝（等长只会落在字典序更靠后的
      方案上，下界达到当前最优即可安全剪枝），并记忆失败状态。

    :param devices: 设备集合（编号唯一、相位为 A/B/C、终点为合法节点）。
    :param edges: 无向边集合（无自环、无重复，长度为正整数，容量 0~4）。
    :param phase_starts: 各相起点，形如 {"A": int, "B": int, "C": int}。
    :param node_count: 节点数（节点编号 0 ~ node_count-1）。
    :return: CableRoutesResult；无可行路由方案时 feasible=False。
    """
    ordered = sorted(devices, key=lambda d: d.code)
    k = len(ordered)
    # 边按 (u, v) 规范化并排序，边占用与结果顺序均以此为准
    canon_edges = sorted(
        (
            CableRouteEdge(
                u=min(e.u, e.v),
                v=max(e.u, e.v),
                length=e.length,
                capacity=e.capacity,
            )
            for e in edges
        ),
        key=lambda e: (e.u, e.v),
    )
    m = len(canon_edges)

    # 邻接表：node -> [(相邻节点, 边长度, 边编号)]，按相邻节点编号升序，
    # 保证简单路径 DFS 按节点序列字典序依次产生候选；容量为 0 的边不可能
    # 承载任何电缆，不参与路径枚举（经过它的路径必然违反容量约束）。
    adjacency: dict[int, list[tuple[int, int, int]]] = {
        node: [] for node in range(node_count)
    }
    for idx, edge in enumerate(canon_edges):
        if edge.capacity <= 0:
            continue
        adjacency[edge.u].append((edge.v, edge.length, idx))
        adjacency[edge.v].append((edge.u, edge.length, idx))
    for node in adjacency:
        adjacency[node].sort(key=lambda item: item[0])

    @dataclass(frozen=True)
    class _Option:
        """一条候选路径：节点序列、总长度、依次经过的边编号。"""

        nodes: tuple[int, ...]
        length: int
        edge_ids: tuple[int, ...]

    def enumerate_paths(start: int, target: int) -> list[_Option]:
        """枚举 start -> target 的全部简单路径（按节点序列字典序）。"""
        options: list[_Option] = []
        visited = [False] * node_count
        path_nodes: list[int] = [start]
        path_edges: list[int] = []
        visited[start] = True

        def dfs(node: int, length: int) -> None:
            if node == target:
                # 到达终点即记录；零边路径（start==target）首先记录，
                # 且终点不可能在无重复节点路径中再次出现，无需继续延伸
                options.append(
                    _Option(tuple(path_nodes), length, tuple(path_edges))
                )
                return
            for neighbor, edge_length, edge_id in adjacency[node]:
                if visited[neighbor]:
                    continue
                visited[neighbor] = True
                path_nodes.append(neighbor)
                path_edges.append(edge_id)
                dfs(neighbor, length + edge_length)
                path_edges.pop()
                path_nodes.pop()
                visited[neighbor] = False

        dfs(start, 0)
        return options

    # 每台设备的候选路径（按节点序列字典序）与最短路径长度
    options_per_device: list[list[_Option]] = []
    shortest: list[int] = []
    for device in ordered:
        start = phase_starts[device.phase]
        options = enumerate_paths(start, device.endpoint)
        if not options:
            return CableRoutesResult(
                feasible=False, paths=None, total_length=None, edge_usage=None
            )
        options_per_device.append(options)
        shortest.append(min(option.length for option in options))

    # suffix_shortest[i]：第 i..k-1 台设备各自最短路径长度之和（乐观下界）
    suffix_shortest = [0] * (k + 1)
    for i in range(k - 1, -1, -1):
        suffix_shortest[i] = suffix_shortest[i + 1] + shortest[i]

    used = [0] * m  # 各边当前经过的电缆数
    chosen: list[Optional[_Option]] = [None] * k
    best_total: Optional[int] = None
    best_options: Optional[list[_Option]] = None
    # 失败状态记忆：(设备序号, 各边占用, 当前总长度) 无法扩展为不劣于最优的完整方案
    dead: set[tuple[int, tuple[int, ...], int]] = set()

    def dfs(i: int, current_total: int) -> None:
        nonlocal best_total, best_options
        if i == k:
            # 候选按字典序展开，仅总长度严格更优才更新：
            # 同总长度时先枚举到的完整方案节点序列字典序更小
            if best_total is None or current_total < best_total:
                best_total = current_total
                best_options = [option for option in chosen if option is not None]
            return
        # 乐观下界剪枝：后续设备即使各取最短路径，总长度仍不低于当前最优时，
        # 子树只可能给出等长（字典序更靠后）或更长方案，可整体剪除
        lower_bound = current_total + suffix_shortest[i]
        key = (i, tuple(used), current_total)
        if best_total is not None and lower_bound >= best_total:
            return
        if key in dead:
            return
        for option in options_per_device[i]:
            if all(
                used[edge_id] < canon_edges[edge_id].capacity
                for edge_id in option.edge_ids
            ):
                for edge_id in option.edge_ids:
                    used[edge_id] += 1
                chosen[i] = option
                dfs(i + 1, current_total + option.length)
                chosen[i] = None
                for edge_id in option.edge_ids:
                    used[edge_id] -= 1
                if best_total is not None and suffix_shortest[0] == best_total:
                    return  # 已命中全局长度下界，字典序最优方案必已取得
        dead.add(key)

    dfs(0, 0)

    if best_options is None:
        return CableRoutesResult(
            feasible=False, paths=None, total_length=None, edge_usage=None
        )

    occupied = [0] * m
    paths: list[CableRoutePath] = []
    for device, option in zip(ordered, best_options):
        paths.append(
            CableRoutePath(
                code=device.code,
                phase=device.phase,
                endpoint=device.endpoint,
                nodes=option.nodes,
                length=option.length,
            )
        )
        for edge_id in option.edge_ids:
            occupied[edge_id] += 1
    edge_usage = tuple(
        CableRouteEdgeUsage(
            u=edge.u,
            v=edge.v,
            length=edge.length,
            capacity=edge.capacity,
            occupied=occupied[idx],
        )
        for idx, edge in enumerate(canon_edges)
    )
    return CableRoutesResult(
        feasible=True,
        paths=tuple(paths),
        total_length=sum(option.length for option in best_options),
        edge_usage=edge_usage,
    )


# ---------------------------------------------------------------------------
# 检修停机排程预演
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaintenanceDevice:
    """检修停机排程中的一台设备（未选设备始终在线，仅需提供其相位与功率）。"""

    code: str  # 设备唯一编号
    phase: str  # 固定接入相位（A/B/C，沿用原计算记录）
    power: int  # 记录功率（正整数）


@dataclass(frozen=True)
class MaintenanceWindow:
    """一台选中设备的停机要求：时长 d，开始时隙 s ∈ [earliest, latest]。"""

    code: str  # 设备唯一编号（与某台 MaintenanceDevice 对应）
    duration: int  # 连续停机时长（1~3 个时隙）
    earliest_start: int  # 最早开始时隙（0~11）
    latest_start: int  # 最晚开始时隙（0~11，不早于 earliest_start）


@dataclass(frozen=True)
class MaintenanceScheduleItem:
    """一台设备的检修安排：半开停机区间 [start, start+duration)。"""

    code: str  # 设备编号
    phase: str  # 所属相（A/B/C）
    power: int  # 设备记录功率
    start: int  # 开始时隙
    duration: int  # 连续停机时长
    finish: int  # 完工时隙（= start + duration，即区间右端点）


@dataclass(frozen=True)
class MaintenanceScheduleResult:
    """检修停机排程预演结果。feasible 为 False 时其余字段为 None。

    slot_loads：逐时隙（长度为总时隙数）各相在线负载；completion_slot：
    最后完工时隙 max_i(s_i + d_i)；reason：无解时的具体说明。
    """

    feasible: bool
    items: Optional[tuple[MaintenanceScheduleItem, ...]]  # 各设备安排（按编号排序）
    slot_loads: Optional[tuple[dict[str, int], ...]]  # 逐时隙相位 -> 在线负载
    completion_slot: Optional[int]  # 最后完工时隙
    reason: Optional[str]  # 无解说明（可行时为 None）


def solve_maintenance_schedule(
    all_devices: Iterable[MaintenanceDevice],
    windows: Iterable[MaintenanceWindow],
    total_slots: int,
    simultaneous_limit: int,
    lower_bounds: dict[str, int],
) -> MaintenanceScheduleResult:
    """求解检修停机排程预演。

    未选设备始终在线；每台选中设备须在其允许的开始时隙范围内安排一次长度为
    ``duration`` 的连续停机（半开区间 [start, start+duration)，整体落在
    [0, total_slots) 内）。每时隙停机设备数不得超过 ``simultaneous_limit``；
    每时隙各相在线负载（该相全部设备功率之和减去该时隙停机设备功率之和）不得
    低于对应 ``lower_bounds``。目标依次为：1) 最后完工时隙
    max_i(start_i + duration_i) 最小；2) 同值时取按设备编号排序的开始时隙
    序列字典序最小者。

    求解：先做整体性必要判定给出无解说明，再以 MRV + 前向检查的回溯判定给定
    完工时限是否可行，对完工时限二分求出最小值，最后在最优时限内按设备编号
    顺序、开始时隙升序 DFS 取字典序最小方案（详见模块 docstring）。

    :param all_devices: 记录内全部设备（编号唯一、相位为 A/B/C、功率为正整数）。
    :param windows: 选中设备的停机要求（编号互不重复且均存在于设备集合中，
        每台满足 0 <= earliest <= latest 且 latest + duration <= total_slots）。
    :param total_slots: 总时隙数（1~12，时隙编号 0 ~ total_slots-1）。
    :param simultaneous_limit: 每时隙同时检修设备数上限（1~3）。
    :param lower_bounds: 各相最低在线负载（非负），形如 {"A": int, ...}。
    :return: MaintenanceScheduleResult；无可行排程时 feasible=False 并给出 reason。
    """
    ordered_devices = sorted(all_devices, key=lambda d: d.code)
    phase_of = {d.code: d.phase for d in ordered_devices}
    power_of = {d.code: d.power for d in ordered_devices}
    bounds = {p: lower_bounds[p] for p in PHASES}

    ordered_windows = sorted(windows, key=lambda w: w.code)
    n = len(ordered_windows)
    codes = [w.code for w in ordered_windows]
    durations = [w.duration for w in ordered_windows]
    earliest = [w.earliest_start for w in ordered_windows]
    latest = [w.latest_start for w in ordered_windows]

    # 全部设备在线时各相负载（未选设备任何时隙均在线，构成基础负载）
    base_loads = {p: 0 for p in PHASES}
    for device in ordered_devices:
        base_loads[device.phase] += device.power

    # ---- 整体性必要判定（给出可读的无解说明） ----
    for p in PHASES:
        if base_loads[p] < bounds[p]:
            return MaintenanceScheduleResult(
                feasible=False,
                items=None,
                slot_loads=None,
                completion_slot=None,
                reason=(
                    f"无可行排程：{p} 相全部设备在线时负载仅为 {base_loads[p]}，"
                    f"低于该相最低在线负载 {bounds[p]}"
                ),
            )
    total_demand = sum(durations)
    capacity_slots = simultaneous_limit * total_slots
    if total_demand > capacity_slots:
        return MaintenanceScheduleResult(
            feasible=False,
            items=None,
            slot_loads=None,
            completion_slot=None,
            reason=(
                "无可行排程：各设备停机时隙需求合计 "
                f"{total_demand} 超过同时检修上限 {simultaneous_limit} 与总时隙数 "
                f"{total_slots} 所能容纳的 {capacity_slots} 个设备·时隙"
            ),
        )
    # 单台设备功率超过其所属相的可停电余量时，该设备任何时隙都不能停机：
    # 其停机区间内该相在线负载将严格低于下限
    for idx, code in enumerate(codes):
        p = phase_of[code]
        if power_of[code] > base_loads[p] - bounds[p]:
            return MaintenanceScheduleResult(
                feasible=False,
                items=None,
                slot_loads=None,
                completion_slot=None,
                reason=(
                    f"无可行排程：设备 {code} 停机时 {p} 相在线负载将降至 "
                    f"{base_loads[p] - power_of[code]}，低于该相最低在线负载 "
                    f"{bounds[p]}"
                ),
            )

    # 每个候选开始时隙对应一个停机时隙位掩码（总时隙数不超过 12，单字整数即可）
    start_masks: list[dict[int, int]] = []
    for idx in range(n):
        masks: dict[int, int] = {}
        for start in range(earliest[idx], latest[idx] + 1):
            masks[start] = ((1 << durations[idx]) - 1) << start
        start_masks.append(masks)

    # down_count[t]：时隙 t 已预订停机的设备数；
    # down_power[p][t]：时隙 t 已预订停机的 p 相设备功率之和
    down_count = [0] * total_slots
    down_power = {p: [0] * total_slots for p in PHASES}

    def candidate_starts(idx: int, limit: int) -> list[int]:
        """设备 i 在当前停机预订下的可行开始时隙：完工不晚于 limit，且每个停机
        时隙同时检修数与各相在线负载约束均满足（停机时长不超过 3，检查常数个
        时隙）。"""
        p = phase_of[codes[idx]]
        w = power_of[codes[idx]]
        result: list[int] = []
        max_start = min(latest[idx], limit - durations[idx])
        for start in range(earliest[idx], max_start + 1):
            mask = start_masks[idx][start]
            ok = True
            t = mask
            while t:
                bit = t & (-t)
                s = bit.bit_length() - 1
                if down_count[s] >= simultaneous_limit:
                    ok = False
                    break
                if base_loads[p] - down_power[p][s] - w < bounds[p]:
                    ok = False
                    break
                t ^= bit
            if ok:
                result.append(start)
        return result

    def book(idx: int, start: int, sign: int) -> None:
        """按 sign=+1/-1 预订 / 撤销设备 i 自 start 起的停机区间。"""
        p = phase_of[codes[idx]]
        w = power_of[codes[idx]]
        t = start_masks[idx][start]
        while t:
            bit = t & (-t)
            s = bit.bit_length() - 1
            down_count[s] += sign
            down_power[p][s] += sign * w
            t ^= bit

    def feasible_within(limit: int) -> bool:
        """判定是否存在完工时隙不晚于 limit 的可行排程（MRV + 前向检查）。

        候选开始时隙只取决于当前停机预订：预订只会占用容量，故对尚未安排的
        设备，若在当前预订下已无候选，则任何后续安排都不会令其恢复可行，
        可安全剪枝。候选数最少的设备先安排（MRV），尽早暴露冲突。回溯时撤销
        全部预订（含成功路径），故多次可行性调用与后续字典序 DFS 相互独立。
        """
        remaining = set(range(n))

        def search() -> bool:
            if not remaining:
                return True
            best_idx = -1
            best_starts: Optional[list[int]] = None
            for idx in remaining:
                starts = candidate_starts(idx, limit)
                if not starts:
                    return False  # 前向检查：当前预订下该设备已无处可放
                if best_starts is None or len(starts) < len(best_starts):
                    best_idx, best_starts = idx, starts
                    if len(starts) == 1:
                        break
            remaining.remove(best_idx)
            for start in best_starts:
                book(best_idx, start, +1)
                if search():
                    book(best_idx, start, -1)
                    remaining.add(best_idx)
                    return True
                book(best_idx, start, -1)
            remaining.add(best_idx)
            return False

        return search()

    # 整体窗口内无可行排程：无解
    if not feasible_within(total_slots):
        return MaintenanceScheduleResult(
            feasible=False,
            items=None,
            slot_loads=None,
            completion_slot=None,
            reason=(
                "无可行排程：不存在使每台选中设备各检修一次、每时隙同时检修数"
                f"不超过 {simultaneous_limit}、且各相在线负载均不低于下限的安排"
            ),
        )

    # 对完工时限二分求最小完工时隙 L*（可行性关于 L 单调）
    lo, hi = max(durations), total_slots
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible_within(mid):
            hi = mid
        else:
            lo = mid + 1
    best_limit = lo

    # 在 L* 时限内按设备编号顺序、开始时隙升序 DFS：首个完整方案即按编号排序
    # 的开始时隙序列字典序最小者（前向检查仅用于剪枝，不改变枚举次序）
    starts: list[Optional[int]] = [None] * n

    def lex_search(i: int) -> bool:
        if i == n:
            return True
        # 候选开始时隙已按升序产生，故按设备编号顺序枚举即字典序 DFS
        for start in candidate_starts(i, best_limit):
            book(i, start, +1)
            # 前向检查：所选开始时隙须保证其余未安排设备仍可在当前预订下放置
            forward_ok = all(
                candidate_starts(j, best_limit) for j in range(i + 1, n)
            )
            if forward_ok and lex_search(i + 1):
                # 成功路径保留预订并记录选择（调用方不再使用预订状态）
                starts[i] = start
                return True
            book(i, start, -1)
        return False

    assert lex_search(0)  # 二分已证 L* 可行

    chosen_starts = [s for s in starts]
    completion = max(s + d for s, d in zip(chosen_starts, durations))

    # 逐时隙各相在线负载：基础负载减去该时隙停机设备功率
    slot_loads: list[dict[str, int]] = []
    for t in range(total_slots):
        loads = dict(base_loads)
        for idx in range(n):
            if (start_masks[idx][chosen_starts[idx]] >> t) & 1:
                loads[phase_of[codes[idx]]] -= power_of[codes[idx]]
        slot_loads.append(loads)

    items = tuple(
        MaintenanceScheduleItem(
            code=codes[idx],
            phase=phase_of[codes[idx]],
            power=power_of[codes[idx]],
            start=chosen_starts[idx],
            duration=durations[idx],
            finish=chosen_starts[idx] + durations[idx],
        )
        for idx in range(n)
    )
    return MaintenanceScheduleResult(
        feasible=True,
        items=items,
        slot_loads=tuple(slot_loads),
        completion_slot=completion,
        reason=None,
    )


# ---------------------------------------------------------------------------
# 仪表校准预演
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeterDevice:
    """仪表校准预演中的设备（沿用可行计算记录的功率与固定相位）。"""

    code: str  # 设备唯一编号
    phase: str  # 固定接入相位（A/B/C，沿用原计算记录）
    power: int  # 记录功率（正整数）


@dataclass(frozen=True)
class MeterSnapshot:
    """一组仪表快照：当时在线的记录内设备与仪表三个通道的读数。"""

    online: frozenset[str]  # 当时在线的设备编号集合（记录内设备，互不重复；可为空集）
    readings: tuple[int, int, int]  # 通道 1/2/3 的非负整数读数


@dataclass(frozen=True)
class MeterSnapshotResult:
    """单组快照的校准结果：三通道预测读数与绝对误差。"""

    predicted: tuple[int, int, int]  # 通道 1/2/3 的预测读数（该相在线功率和 + 底载）
    errors: tuple[int, int, int]  # 通道 1/2/3 的绝对误差 |读数 − 预测|


@dataclass(frozen=True)
class MeterCalibrationResult:
    """仪表校准预演结果（任意输入均有校准方案，故无 feasible 字段）。"""

    channel_mapping: dict[str, int]  # 相位 -> 通道编号（1/2/3，一一对应）
    base_loads: dict[str, int]  # 相位 -> 跨快照不变的非负整数底载
    max_error: int  # 所有快照所有通道读数与预测的最大绝对误差
    total_error: int  # 所有快照所有通道读数与预测的绝对误差总和
    snapshots: tuple[MeterSnapshotResult, ...]  # 各快照预测与误差（与输入顺序一致）


def solve_meter_calibration(
    devices: Iterable[MeterDevice],
    snapshots: Iterable[MeterSnapshot],
) -> MeterCalibrationResult:
    """求解仪表校准预演：联合选择通道对应与各相底载，使读数拟合最优。

    设备沿用记录功率与固定相位；三个通道与 A/B/C 相位一一对应（对应关系未知），
    每相有跨快照不变的非负整数底载。对快照 s 与相位 p，预测对应通道读数为
    「快照 s 该相在线设备功率之和 + 该相底载」。目标依次为：
    1) 所有快照所有通道的「读数 − 预测」最大绝对误差最小；
    2) 最大误差相同时，绝对误差总和最小；
    3) 仍同值时，按 A/B/C 对应的通道序列、再按 A/B/C 底载序列取字典序最小者。

    求解结构（详见模块 docstring）：给定通道对应后各相互不影响。对相位 p，令
    d_s = 对应通道在快照 s 的读数 − 快照 s 该相在线设备功率之和，则底载 b 的
    逐快照误差为 |d_s − b|。该相最大误差的最优值为
    m_p = max(ceil((max d_s − min d_s)/2), −min d_s)（max(|min d_s − b|,
    |max d_s − b|) 在 b ≥ 0 上的最小值），全局最优最大误差 M* = max_p m_p。
    在「最大误差不超 M*」的底载区间 [max(0, max d_s − M*), min d_s + M*] 内，
    绝对误差总和是 b 的凸函数，其无约束最小集为 d_s 的中位数区间，故约束最优
    即中位数区间到该底载区间的投影点；该点同时是同值底载集合的最左点，天然
    满足底载序列字典序裁决。枚举全部 6 种通道对应，以
    (最大误差, 误差总和, 通道序列, 底载序列) 为键取字典序最小者。

    :param devices: 设备集合（编号唯一、相位为 A/B/C、功率为正整数）。
    :param snapshots: 3~8 组快照（在线编号均为记录内设备，读数为非负整数）。
    :return: MeterCalibrationResult。
    """
    snaps = list(snapshots)
    s_count = len(snaps)
    device_by_code = {d.code: d for d in devices}

    # online_loads[s][p]：快照 s 中 p 相在线设备功率之和
    online_loads: list[dict[str, int]] = []
    for snap in snaps:
        row = {p: 0 for p in PHASES}
        for code in snap.online:
            device = device_by_code[code]
            row[device.phase] += device.power
        online_loads.append(row)

    best_key: Optional[tuple] = None
    best_mapping: Optional[dict[str, int]] = None
    best_bases: Optional[dict[str, int]] = None
    # 枚举三通道与 A/B/C 相位的一一对应：perm = (A 相通道, B 相通道, C 相通道)
    for perm in permutations((1, 2, 3)):
        # 每相的 d 序列：对应通道读数 − 该相在线设备功率之和
        per_phase: dict[str, list[int]] = {}
        for idx, phase in enumerate(PHASES):
            channel = perm[idx]
            per_phase[phase] = [
                snaps[s].readings[channel - 1] - online_loads[s][phase]
                for s in range(s_count)
            ]
        # 一级目标：该相最大误差最优值 m_p = max(ceil((hi−lo)/2), −lo)，
        # 全局最优最大误差为各相 m_p 的最大值
        max_error = 0
        for phase in PHASES:
            ds = per_phase[phase]
            lo, hi = min(ds), max(ds)
            max_error = max(max_error, (hi - lo + 1) // 2, -lo)
        # 二级目标：各相在「最大误差不超 max_error」的底载区间内最小化误差总和
        # （凸函数取中位数区间到约束区间的投影点，即同值底载集合的最左点）
        total_error = 0
        bases: dict[str, int] = {}
        for phase in PHASES:
            ds = per_phase[phase]
            lo, hi = min(ds), max(ds)
            bound_lo = max(0, hi - max_error)
            bound_hi = lo + max_error
            ordered_ds = sorted(ds)
            median_lo = ordered_ds[(s_count - 1) // 2]
            base = min(max(median_lo, bound_lo), bound_hi)
            bases[phase] = base
            total_error += sum(abs(d - base) for d in ds)
        base_sequence = tuple(bases[p] for p in PHASES)
        key = (max_error, total_error, perm, base_sequence)
        if best_key is None or key < best_key:
            best_key = key
            best_mapping = {p: perm[idx] for idx, p in enumerate(PHASES)}
            best_bases = bases

    assert best_mapping is not None and best_bases is not None and best_key is not None

    # 由最优通道对应与底载构造各快照的三通道预测读数与绝对误差
    phase_of_channel = {channel: p for p, channel in best_mapping.items()}
    results: list[MeterSnapshotResult] = []
    for s, snap in enumerate(snaps):
        predicted = tuple(
            online_loads[s][phase_of_channel[channel]]
            + best_bases[phase_of_channel[channel]]
            for channel in (1, 2, 3)
        )
        errors = tuple(
            abs(snap.readings[idx] - predicted[idx]) for idx in range(3)
        )
        results.append(MeterSnapshotResult(predicted=predicted, errors=errors))
    return MeterCalibrationResult(
        channel_mapping=best_mapping,
        base_loads=best_bases,
        max_error=best_key[0],
        total_error=best_key[1],
        snapshots=tuple(results),
    )

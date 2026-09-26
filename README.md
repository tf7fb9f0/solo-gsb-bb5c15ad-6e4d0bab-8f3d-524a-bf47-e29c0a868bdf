# 临时展位三相配电排布 API

基于 **Python + FastAPI + SQLite** 的临时展位三相配电排布服务。

提交最多 **12 台设备**（唯一编号、正整数功率、非空可接入相位集合）以及 **A/B/C 各相容量**，
服务在「所有设备均接入、每台设备整体接入单一允许相位、各相不超容量」的约束下求解分配方案：

1. **首要目标**：使三相负载最大值与最小值之差最小；
2. **次要目标**：差值相同时，取按设备编号排序后的相位序列字典序最小的方案；
3. 不存在可行分配时，返回明确的 `feasible: false` 结果与说明信息。

每次计算的**输入、分配结果与各相负载**均持久化到 SQLite，可随时查询历史记录。
对于原容量下无可行分配的记录，还可通过扩容接口获取「各相最小扩容量 + 对应分配」
建议（保持设备功率与允许相位不变，且不修改原记录）。

此外，服务提供**稳健分相预演**接口：每台设备功率为正整数区间
`[min_power, max_power]`，区间内可独立变化。接口求解「每台设备接入一个允许相位、
且**任意功率组合下各相均不超容量**」的分配，并在其中最小化任意功率组合可能产生的
三相最大负载与最小负载之差。预演结果**不写入历史计算记录**。

对于**已有可行分配**的计算记录，服务还提供**启动顺序预演**接口：沿用记录中的
固定相位与容量，逐台给定**不低于额定功率的启动瞬时功率**，设备一台接一台启动
（启动瞬间按启动功率计，完成后按额定功率持续运行），求解使**全过程三相负载最大值
与最小值之差的峰值**最小的启动顺序。预演同样**不修改历史记录**。

此外，服务还提供**单相故障保供预演**接口：对已有可行分配的记录指定一个故障相，
健康相设备保持原分配，故障相设备只能迁至其允许的健康相（不得超容量）或断开，
在所有应急方案中**先最大化保留设备的总功率，再最大化保留设备数**，同值时取
相位选择序列字典序最小者。预演同样**不修改历史记录**。

最后，服务还提供**新增设备接入预演**接口：对已有可行分配的记录提交一批
**新设备**（沿用编号、功率与允许相位规则，且新旧设备总数不超过 12、编号互不
重复），在**保持原容量**的前提下让新旧设备全部接入且各相不超容量；优化目标
依次为**原设备改相台数最少**、**三相负载最大值与最小值之差最小**、按全部设备
编号排序的相位序列**字典序最小**。预演同样**不修改历史记录**。

此外，服务还提供**双时段错峰接入规划**接口：提交 **1 ~ 8 台设备**（唯一编号、
正整数功率、非空允许相位集合、非空允许运行时段集合）以及**两时段共用的
A/B/C 相容量**，每台设备**恰选一个允许时段（早 / 晚）和一个允许相位**，
各时段各相负载均不超容量；优化目标依次为**两时段总负载的较大值最小**、
**两时段三相负载差的较大值最小**、按设备编号排序的 (时段, 相位) 序列
**字典序最小**。该接口只做预演，**不写入历史计算记录**。

最后，服务还提供**运行功率日志复盘**接口：对已有可行分配的记录，沿用其
设备相位与各相容量，提交**起止 Unix 秒窗口**与**最多 200 条设备实际功率
变更事件**（设备编号、时刻、非负整数功率）。窗口起点所有设备功率为 0，
同一时刻的事件批量生效，接口计算事件之间至窗口终点的三相负载，将
**连续存在任一相超容的区间合并为告警**，返回每段告警的起止时刻、各相
最大超额量以及全窗口各相峰值负载。复盘同样**不修改历史记录**。

此外，服务还提供**电缆盘裁切预演**接口：对**设备不超过 8 台**且已有可行
分配的记录，按设备编号逐台给出一段**正整数长度电缆（不可拼接）**，并提供
**至多 8 个**编号唯一、长度为正整数的库存电缆盘及**非负整数切割损耗**。
同一盘裁出多段时，占用长度为「各段长度之和 + 相邻切口数 × 切割损耗」。
在全部电缆段均可整体裁出的方案中，依次**最小化启用盘数**、**最小化启用盘
总长度**，再取按设备编号排序的电缆盘编号序列**字典序最小**者，返回各盘
裁切清单与剩余长度；无可行裁切方案时明确返回。预演同样**不修改历史记录**。

此外，服务还提供**电缆路由预演**接口：对**设备不超过 4 台**且已有可行
分配的记录，在 **1 ~ 6 个节点、至多 8 条无向边**（正整数长度、容量
**0 ~ 4**）构成的图上，给出**各相起点与每台设备终点**。每台设备沿用记录
中的分相，自所属相起点走一条**无重复节点的路径**至终点（同点用零边路径），
**每条边经过的电缆数不得超过其容量**；在所有方案中**最小化各路径总长度**，
同值时按设备编号排序、依次比较各路径节点序列取**字典序最小**者，返回各
设备路径、总长度与各边占用；无可行方案时明确返回。预演同样**不修改历史
记录**。

此外，服务还提供**检修停机排程预演**接口：对已有可行分配的记录，选择记录内
**1 ~ 6 台设备**，逐台给出 **1 ~ 3 个时隙的连续停机时长**与 **0 ~ 11 范围内的
最早、最晚开始时隙**，并给出**总时隙数（1 ~ 12）**、**每时隙同时检修设备数
上限（1 ~ 3）**以及 **A/B/C 各相非负最低在线负载**。**未选设备始终在线**；
选中设备在半开停机区间 `[start, start+duration)` 内**不计入所属相负载**，其余
时隙按记录功率运行。在所有设备各检修一次、每时隙同时检修数不超上限、各相
在线负载不低于下限的安排中，**先最小化最后完工时隙**，同值时取**按设备编号
排序的开始时隙序列字典序最小**者，返回检修安排与逐时隙各相在线负载；无可行
排程时明确返回。预演同样**不修改历史记录**。

此外，服务还提供**仪表校准预演**接口：对已有可行分配的记录提交 **3 ~ 8 组
仪表快照**，每组列出**当时在线的记录内设备编号**与仪表**三个通道的非负整数
读数**（按通道 1/2/3 排列）。设备沿用记录功率与固定相位；假设三通道与
A/B/C 相**一一对应**、且每相存在**跨快照不变的非负整数底载**，接口联合选择
通道对应关系与三相底载：**先最小化所有读数与「该相在线设备功率之和 +
底载」的最大绝对误差，再最小化绝对误差总和**；仍同值时按 **A/B/C 对应的
通道序列、底载序列字典序**裁决，返回对应关系、底载与各快照预测读数及误差。
预演同样**不修改历史记录**。

## 快速开始（一键启动）

前置条件：已安装 Docker 与 Docker Compose 插件。

```bash
docker compose up --build
```

依赖安装与数据库初始化（自动建表）均在容器启动时完成，无需任何额外步骤。

启动后访问：

| 地址 | 说明 |
| --- | --- |
| http://localhost:8000 | 服务根端口 |
| http://localhost:8000/docs | Swagger 交互式 API 文档 |
| http://localhost:8000/health | 健康检查 |

停止服务：`docker compose down`（加 `-v` 可同时清除数据卷）。

## 配置说明

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_PATH` | 容器内 `/data/app.db`；本地运行 `data/app.db` | SQLite 数据库文件路径，通过环境变量覆盖 |
| 端口映射 | `8000:8000` | 在 `docker-compose.yml` 的 `ports` 中调整宿主机端口 |

数据库文件保存在 Compose 命名卷 `app-data` 中，容器重建后历史计算记录不丢失。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/calculations` | 创建一次排布计算，返回最优分配、各相负载与差值 |
| `GET` | `/api/v1/calculations` | 查询历史计算记录摘要（支持 `limit` / `offset` 分页） |
| `GET` | `/api/v1/calculations/{id}` | 查询单条记录详情（含原始输入设备与分配结果） |
| `POST` | `/api/v1/calculations/{id}/capacity-upgrade` | 为「无可行分配」的记录给出最小扩容建议（原记录不变） |
| `POST` | `/api/v1/calculations/{id}/startup-plan` | 为「有可行分配」的记录预演负载差峰值最小的安全启动顺序（原记录不变） |
| `POST` | `/api/v1/calculations/{id}/phase-fault-rehearsal` | 为「有可行分配」的记录预演单相故障下的保供迁移 / 断开方案（原记录不变） |
| `POST` | `/api/v1/calculations/{id}/device-addition-plan` | 为「有可行分配」的记录预演新增设备接入方案（原设备改相最少，原记录不变） |
| `POST` | `/api/v1/calculations/{id}/power-log-replay` | 为「有可行分配」的记录复盘窗口内功率变更日志，合并超容告警并给出各相峰值（原记录不变） |
| `POST` | `/api/v1/calculations/{id}/cable-cutting-plan` | 为「设备 ≤ 8 台且有可行分配」的记录预演电缆盘裁切方案（启用盘数/总长/字典序最优，原记录不变） |
| `POST` | `/api/v1/calculations/{id}/cable-routes` | 为「设备 ≤ 4 台且有可行分配」的记录预演电缆路由（总长度/路径节点序列字典序最优，原记录不变） |
| `POST` | `/api/v1/calculations/{id}/maintenance-schedule` | 为「有可行分配」的记录预演 1~6 台设备的检修停机排程（完工时隙最早/开始时隙序列字典序最优，原记录不变） |
| `POST` | `/api/v1/calculations/{id}/meter-calibration` | 为「有可行分配」的记录用 3~8 组仪表快照标定通道对应与各相底载（最大误差/总误差/字典序最优，原记录不变） |
| `POST` | `/api/v1/robust-rehearsals` | 稳健分相预演：设备功率为区间，求任意功率组合下均不超容量的最优分配（不持久化） |
| `POST` | `/api/v1/shift-plans` | 双时段错峰接入规划：1~8 台设备各选一个允许时段（早/晚）与相位，两时段共用容量（不持久化） |
| `GET` | `/health` | 健康检查 |

### 请求示例

```bash
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A", "B", "C"]},
      {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"]},
      {"id": "D3", "power": 30, "allowed_phases": ["B", "C"]}
    ]
  }'
```

### 响应示例（有可行方案）

```json
{
  "id": 1,
  "created_at": "2026-09-24T08:00:00.000000+00:00",
  "capacities": {"A": 100, "B": 100, "C": 100},
  "feasible": true,
  "imbalance": 20,
  "loads": {"A": 10, "B": 20, "C": 30},
  "message": "计算成功：已找到三相不平衡度最小的分配方案",
  "assignments": [
    {"device_id": "D1", "phase": "A"},
    {"device_id": "D2", "phase": "B"},
    {"device_id": "D3", "phase": "C"}
  ]
}
```

### 响应示例（无可行方案）

```json
{
  "id": 2,
  "created_at": "2026-09-24T08:01:00.000000+00:00",
  "capacities": {"A": 5, "B": 0, "C": 0},
  "feasible": false,
  "imbalance": null,
  "loads": null,
  "message": "无可行分配：不存在所有设备均接入且各相不超容量的方案",
  "assignments": []
}
```

## 容量扩容建议

对于返回 `feasible: false` 的计算记录，可调用扩容接口。服务**保持设备功率与允许
相位不变**，计算 A/B/C 各相需要增加的**非负整数容量**以及扩容后的设备分配，
使所有设备都能接入。优化目标依次为：

1. **三相扩容总量最小**（`total_upgrade`）；
2. 总量相同时，**单相最大扩容量最小**（`max_upgrade`）；
3. 仍相同时，取按设备编号排序的相位序列**字典序最小**的方案。

接口只返回建议，**原计算记录不做任何修改**。记录不存在返回 `404`；
原记录已有可行分配（无需扩容）返回 `409`。

### 请求示例

```bash
# 先创建一条无可行分配的记录
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 5, "B": 0, "C": 0},
    "devices": [
      {"id": "BIG", "power": 50, "allowed_phases": ["A", "B", "C"]},
      {"id": "FIX", "power": 7, "allowed_phases": ["A"]}
    ]
  }'

# 再对该记录请求扩容建议（假设记录 id 为 2）
curl -X POST http://localhost:8000/api/v1/calculations/2/capacity-upgrade
```

### 响应示例

```json
{
  "id": 2,
  "created_at": "2026-09-24T08:01:00.000000+00:00",
  "original_capacities": {"A": 5, "B": 0, "C": 0},
  "capacity_upgrades": {"A": 2, "B": 50, "C": 0},
  "suggested_capacities": {"A": 7, "B": 50, "C": 0},
  "total_upgrade": 52,
  "max_upgrade": 50,
  "assignments": [
    {"device_id": "BIG", "phase": "B"},
    {"device_id": "FIX", "phase": "A"}
  ],
  "loads": {"A": 7, "B": 50, "C": 0},
  "message": "扩容建议：已在最小化三相扩容总量、再最小化单相最大扩容量的目标下，找到使所有设备均接入的容量与分配方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `original_capacities` | 原各相容量 |
| `capacity_upgrades` | 各相需要增加的非负整数容量 |
| `suggested_capacities` | 建议容量 = 原容量 + 扩容量 |
| `total_upgrade` / `max_upgrade` | 三相扩容总量 / 单相最大扩容量 |
| `assignments` | 建议容量下的设备相位分配（按设备编号排序） |
| `loads` | 该分配下各相的实际负载（均不超过建议容量） |

### 输入校验规则

- 设备数量 **1 ~ 12** 台，设备编号**唯一**且非空；
- 功率为**正整数**；
- `allowed_phases` 为**非空**数组，元素取自 `A` / `B` / `C`（自动去重）；
- 各相容量为**非负整数**。

不满足规则时返回 `422` 及具体错误信息。

## 稳健分相预演

`POST /api/v1/robust-rehearsals` 用于设备功率尚未确定、只能给出波动区间时的
事前推演。每台设备的功率为正整数区间 `[min_power, max_power]`（**下界不大于
上界**），各设备功率在区间内**独立变化**。接口寻找每台设备接入一个允许相位、
且**任意功率组合下各相均不超容量**的分配（稳健可行），并在稳健可行方案中：

1. **最小化**任意功率组合可能产生的「三相最大负载与最小负载之差」
   （`worst_imbalance`）；
2. 同值时取按设备编号排序的相位序列**字典序最小**的方案。

接口**只做预演，不写入历史计算记录**；无稳健可行方案时返回
`feasible: false` 及说明信息。

### 请求示例

```bash
curl -X POST http://localhost:8000/api/v1/robust-rehearsals \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "min_power": 5,  "max_power": 10, "allowed_phases": ["A", "B", "C"]},
      {"id": "D2", "min_power": 15, "max_power": 20, "allowed_phases": ["A", "B", "C"]},
      {"id": "D3", "min_power": 25, "max_power": 30, "allowed_phases": ["B", "C"]}
    ]
  }'
```

### 响应示例（稳健可行）

```json
{
  "capacities": {"A": 100, "B": 100, "C": 100},
  "feasible": true,
  "worst_imbalance": 25,
  "load_lower_bounds": {"A": 5, "B": 15, "C": 25},
  "load_upper_bounds": {"A": 10, "B": 20, "C": 30},
  "assignments": [
    {"device_id": "D1", "phase": "A"},
    {"device_id": "D2", "phase": "B"},
    {"device_id": "D3", "phase": "C"}
  ],
  "message": "预演成功：已找到任意功率组合下各相均不超容量、且最坏负载差最小的稳健分配方案"
}
```

### 响应示例（无稳健可行方案）

```json
{
  "capacities": {"A": 40, "B": 40, "C": 40},
  "feasible": false,
  "worst_imbalance": null,
  "load_lower_bounds": null,
  "load_upper_bounds": null,
  "assignments": [],
  "message": "无稳健可行分配：不存在任意功率组合下各相均不超容量的接入方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `feasible` | 是否存在稳健可行分配 |
| `worst_imbalance` | 任意功率组合下「三相最大负载 - 最小负载」的最大值 |
| `load_lower_bounds` | 各相负载下界（该相设备均取功率下界之和） |
| `load_upper_bounds` | 各相负载上界（该相设备均取功率上界之和，均不超过容量） |
| `assignments` | 稳健分配方案（按设备编号排序）；无解时为空数组 |

### 输入校验规则

- 设备数量 **1 ~ 12** 台，设备编号**唯一**且非空；
- `min_power` / `max_power` 均为**正整数**，且 `min_power` **不大于** `max_power`；
- `allowed_phases` 为**非空**数组，元素取自 `A` / `B` / `C`（自动去重）；
- 各相容量为**非负整数**。

不满足规则时返回 `422` 及具体错误信息。

## 启动顺序预演

`POST /api/v1/calculations/{id}/startup-plan` 用于在已得到可行分配后，预演设备
**一台接一台启动**的最优顺序。接口**沿用记录中的固定相位（每台设备的接入相位）
与容量**，请求中逐台给出**启动瞬时功率**：

- 启动瞬时功率为**正整数，且不低于该设备的额定功率**；
- 请求中的**设备编号须与记录完全一致**（不多、不少、不重复）。

启动过程：设备一次启动一台；**启动瞬间**该设备按启动瞬时功率计，此前已启动的设备
按额定功率持续运行；**启动完成后**该设备亦按额定功率持续运行。每个启动瞬间及每个
稳定状态下，A/B/C 各相负载均不得超过容量。接口在所有安全启动顺序中：

1. **最小化全过程**「三相负载最大值与最小值之差」的**峰值**
   （`peak_imbalance`，取所有启动瞬间与稳定状态的最大负载差）；
2. 峰值相同时，取**设备编号序列字典序最小**的启动顺序。

接口**只做预演，不修改历史计算记录**；不存在任何安全启动顺序时返回
`feasible: false` 及说明信息。记录不存在返回 `404`；原记录无可行分配返回 `409`；
启动功率低于额定功率或设备编号与记录不一致返回 `422`。

### 请求示例

```bash
# 先创建一条可行计算记录（设备 D1/D2/D3 分别固定接 A/B/C）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 10, "B": 10, "C": 10},
    "devices": [
      {"id": "D1", "power": 6, "allowed_phases": ["A"]},
      {"id": "D2", "power": 4, "allowed_phases": ["B"]},
      {"id": "D3", "power": 5, "allowed_phases": ["C"]}
    ]
  }'

# 再对该记录请求启动顺序预演（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/startup-plan \
  -H "Content-Type: application/json" \
  -d '{
    "startup_powers": [
      {"device_id": "D1", "startup_power": 8},
      {"device_id": "D2", "startup_power": 6},
      {"device_id": "D3", "startup_power": 9}
    ]
  }'
```

### 响应示例（存在安全启动顺序）

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "capacities": {"A": 10, "B": 10, "C": 10},
  "feasible": true,
  "peak_imbalance": 8,
  "startup_order": ["D1", "D2", "D3"],
  "steps": [
    {
      "device_id": "D1",
      "phase": "A",
      "rated_power": 6,
      "startup_power": 8,
      "transient_loads": {"A": 8, "B": 0, "C": 0},
      "transient_imbalance": 8,
      "steady_loads": {"A": 6, "B": 0, "C": 0},
      "steady_imbalance": 6
    },
    {
      "device_id": "D2",
      "phase": "B",
      "rated_power": 4,
      "startup_power": 6,
      "transient_loads": {"A": 6, "B": 6, "C": 0},
      "transient_imbalance": 6,
      "steady_loads": {"A": 6, "B": 4, "C": 0},
      "steady_imbalance": 6
    },
    {
      "device_id": "D3",
      "phase": "C",
      "rated_power": 5,
      "startup_power": 9,
      "transient_loads": {"A": 6, "B": 4, "C": 9},
      "transient_imbalance": 5,
      "steady_loads": {"A": 6, "B": 4, "C": 5},
      "steady_imbalance": 2
    }
  ],
  "message": "预演成功：已找到全过程三相负载最大值与最小值之差峰值最小的安全启动顺序"
}
```

### 响应示例（无安全启动顺序）

某设备启动功率 11，但其固定接入的 A 相容量仅为 10（额定功率 10 下记录本可行），
任何顺序都无法安全启动该设备：

```json
{
  "id": 2,
  "created_at": "2026-09-25T08:01:00.000000+00:00",
  "capacities": {"A": 10, "B": 0, "C": 0},
  "feasible": false,
  "peak_imbalance": null,
  "startup_order": [],
  "steps": [],
  "message": "无安全启动顺序：不存在每个启动瞬间及稳定状态各相均不超容量的启动顺序"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `peak_imbalance` | 全过程负载差峰值：所有启动瞬间与稳定状态的「最大相负载 − 最小相负载」的最大值 |
| `startup_order` | 最优启动顺序（设备编号）；无安全顺序时为空数组 |
| `steps[].phase` | 该设备沿用自计算记录的固定接入相位 |
| `steps[].transient_loads` | 该设备**启动瞬间**各相负载（该设备按启动功率计） |
| `steps[].transient_imbalance` | 启动瞬间三相负载最大值与最小值之差 |
| `steps[].steady_loads` | 启动**完成后**各相稳定负载（该设备转入额定功率） |
| `steps[].steady_imbalance` | 稳定状态三相负载最大值与最小值之差 |

### 输入校验规则

- `startup_powers` 为**非空**数组，设备编号**唯一**且与记录**完全一致**
  （缺失、多余均返回 `422`）；
- 每台设备的 `startup_power` 为**正整数**，且**不低于其额定功率**；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

## 单相故障保供预演

`POST /api/v1/calculations/{id}/phase-fault-rehearsal?fault_phase=A` 用于在某一相
发生故障时预演应急保供方案。故障相通过查询参数 `fault_phase` 指定（取值 `A`/`B`/`C`）：

- **健康相上的设备保持原分配不动**（不迁移、不参与重新优化）；
- **故障相设备**只能迁至其**允许接入的健康相**，迁入后该相负载**不得超过容量**，
  也可以**断开**；故障相最终负载**必为零**。

在所有满足约束的应急方案中，目标依次为：

1. **最大化保留设备的总功率**（`retained_power`，含健康相上保持原分配的设备）；
2. 总功率相同时，**最大化保留设备数**（`retained_count`）；
3. 仍相同时，按**故障相设备编号排序**，取其**相位选择序列字典序最小**者，
   单项次序为 **A＜B＜C＜断开**（只在允许的健康相中选择）。

全部故障相设备断开总是可行，因此该接口不返回 `feasible=false`。接口**只做预演，
不修改历史计算记录**。记录不存在返回 `404`；原记录无可行分配（`feasible=false`）
返回 `409`；`fault_phase` 缺失或取值非法返回 `422`。

### 请求示例

```bash
# 先创建一条可行计算记录（F1/F2 接 A，H1 接 B）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 20, "B": 12, "C": 12},
    "devices": [
      {"id": "H1", "power": 7, "allowed_phases": ["B"]},
      {"id": "F1", "power": 5, "allowed_phases": ["A", "B"]},
      {"id": "F2", "power": 5, "allowed_phases": ["A", "B"]}
    ]
  }'

# 再对该记录预演 A 相故障（假设记录 id 为 1）
curl -X POST "http://localhost:8000/api/v1/calculations/1/phase-fault-rehearsal?fault_phase=A"
```

原记录负载为 `{A: 10, B: 7, C: 0}`。A 相故障后，B 相仅剩 `12 - 7 = 5` 空闲，
两台功率均为 5 的故障相设备最多迁一台至 B（均不允许 C）；保留总功率与设备数
相同，故取相位选择序列字典序最小者——编号较小的 `F1` 迁 B，`F2` 断开。

### 响应示例

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "fault_phase": "A",
  "capacities": {"A": 20, "B": 12, "C": 12},
  "original_loads": {"A": 10, "B": 7, "C": 0},
  "loads": {"A": 0, "B": 12, "C": 0},
  "migrations": [
    {"device_id": "F1", "power": 5, "from_phase": "A", "to_phase": "B"}
  ],
  "disconnected": [
    {"device_id": "F2", "power": 5, "phase": "A"}
  ],
  "retained_power": 12,
  "retained_count": 2,
  "disconnected_power": 5,
  "disconnected_count": 1,
  "message": "预演成功：健康相设备保持原分配，故障相设备在允许健康相不超容量的前提下，已找到保留总功率最大、再保留设备数最多，且相位选择序列字典序最小的保供方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `fault_phase` | 故障相（A/B/C） |
| `original_loads` | 故障前各相负载（原记录的分配负载，含故障相设备） |
| `loads` | 预演后各相负载（健康相不动设备 + 迁入设备；故障相恒为 `0`，各相不超容量） |
| `migrations` | 迁至健康相的故障相设备（按设备编号排序），含功率、原相位与迁入相位 |
| `disconnected` | 被断开的故障相设备（按设备编号排序），含功率与原相位 |
| `retained_power` / `retained_count` | 保留设备（健康相不动设备 + 迁移设备）的总功率 / 数量 |
| `disconnected_power` / `disconnected_count` | 断开设备的总功率 / 数量 |

## 新增设备接入预演

`POST /api/v1/calculations/{id}/device-addition-plan` 用于在已有可行分配的记录
基础上，预演**提交一批新设备**后的整体接入方案。请求体中的新设备沿用与创建
计算相同的规则（唯一编号、正整数功率、非空可接入相位集合），并额外要求：

- 新设备编号**不得与记录中已有设备重复**；
- **新旧设备总数不超过 12 台**。

接口**保持原记录容量不变**，要求新旧设备全部接入各自的允许相位且各相不超
容量；原设备可以**改相（迁移）**，也可以保持原相位。优化目标依次为：

1. **原设备改相台数最少**（`migrated_count`）；
2. 改相台数相同时，**三相负载最大值与最小值之差最小**（`imbalance`）；
3. 仍相同时，取按**全部设备（新 + 旧）编号排序**的相位序列**字典序最小**者。

接口**只做预演，不修改历史计算记录**；保持原容量时若不存在全部设备接入的
可行方案，返回 `feasible: false` 及说明信息。记录不存在返回 `404`；原记录
无可行分配返回 `409`；新设备编号与记录重复、新旧总数超过 12 台或新设备
字段不满足规则返回 `422`。

### 请求示例

```bash
# 先创建一条可行计算记录（D1->A 功率 6，D2->B 功率 4，容量各 10）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 10, "B": 10, "C": 10},
    "devices": [
      {"id": "D1", "power": 6, "allowed_phases": ["A", "B"]},
      {"id": "D2", "power": 4, "allowed_phases": ["B", "C"]}
    ]
  }'

# 再对该记录预演新增一台设备（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/device-addition-plan \
  -H "Content-Type: application/json" \
  -d '{
    "devices": [
      {"id": "N1", "power": 4, "allowed_phases": ["C"]}
    ]
  }'
```

### 响应示例（无需改相）

新设备 `N1` 只能接 C，原设备保持原相位即得最优方案（负载 6/4/4）：

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "capacities": {"A": 10, "B": 10, "C": 10},
  "feasible": true,
  "imbalance": 2,
  "loads": {"A": 6, "B": 4, "C": 4},
  "migrated_count": 0,
  "existing_assignments": [
    {"device_id": "D1", "phase": "A"},
    {"device_id": "D2", "phase": "B"}
  ],
  "new_assignments": [
    {"device_id": "N1", "phase": "C"}
  ],
  "migrations": [],
  "message": "预演成功：保持原容量不变，已在原设备改相台数最少、三相负载最大值与最小值之差最小、相位序列字典序最小的目标下，找到新旧设备全部接入的分配方案"
}
```

### 响应示例（需要改相）

若上例容量收紧为各相 8，新增 `N1`（功率 5，允许 A/B）在原分配下无处可放，
必须改相一台：最优方案为 `D2` 迁至 C、`N1` 接 B（负载 6/5/4）：

```json
{
  "id": 2,
  "created_at": "2026-09-25T08:05:00.000000+00:00",
  "capacities": {"A": 8, "B": 8, "C": 8},
  "feasible": true,
  "imbalance": 2,
  "loads": {"A": 6, "B": 5, "C": 4},
  "migrated_count": 1,
  "existing_assignments": [
    {"device_id": "D1", "phase": "A"},
    {"device_id": "D2", "phase": "C"}
  ],
  "new_assignments": [
    {"device_id": "N1", "phase": "B"}
  ],
  "migrations": [
    {"device_id": "D2", "power": 4, "from_phase": "B", "to_phase": "C"}
  ],
  "message": "预演成功：保持原容量不变，已在原设备改相台数最少、三相负载最大值与最小值之差最小、相位序列字典序最小的目标下，找到新旧设备全部接入的分配方案"
}
```

### 响应示例（无可行方案）

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "capacities": {"A": 10, "B": 10, "C": 10},
  "feasible": false,
  "imbalance": null,
  "loads": null,
  "migrated_count": null,
  "existing_assignments": [],
  "new_assignments": [],
  "migrations": [],
  "message": "无可行分配：保持原容量不变时，不存在新旧设备全部接入且各相不超容量的方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `capacities` | 各相容量（沿用原计算记录，保持不变） |
| `feasible` | 保持原容量时，是否存在新旧设备全部接入的可行分配 |
| `migrated_count` | 改相的原设备台数（首要优化目标） |
| `imbalance` | 三相负载最大值与最小值之差 |
| `loads` | 各相负载（均不超过原容量） |
| `existing_assignments` | 原设备分配（按设备编号排序），相位可能与原记录不同 |
| `new_assignments` | 新设备分配（按设备编号排序） |
| `migrations` | 改相的原设备清单（按设备编号排序），含功率、原相位与新相位 |

### 输入校验规则

- 新设备数量 **1 ~ 12** 台，编号**唯一**且非空，且**不得与记录中设备重复**；
- **新旧设备总数不超过 12 台**；
- 功率为**正整数**；`allowed_phases` 为**非空**数组，元素取自 `A` / `B` / `C`
  （自动去重）；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

## 双时段错峰接入规划

`POST /api/v1/shift-plans` 用于在**早（`morning`）、晚（`evening`）两个时段**
之间错峰安排设备运行的事前预演。提交 **1 ~ 8 台设备**（唯一编号、正整数功率、
非空允许相位集合、非空允许运行时段集合）以及**两时段共用的 A/B/C 相容量**。
每台设备**恰选一个允许时段和一个允许相位**；两时段共用同一组容量，
**各时段各相负载均不得超过容量**。优化目标依次为：

1. **两时段总负载（三相之和）的较大值最小**（`peak_total_load`）；
2. **两时段三相负载差（最大值与最小值之差）的较大值最小**（`peak_imbalance`）；
3. 仍相同时，取按设备编号排序的 **(时段, 相位) 序列字典序最小**者
   （时段次序 **早＜晚**，相位次序 **A＜B＜C**）。

接口**只做预演，不写入历史计算记录**；无可行方案时返回 `feasible: false`
及说明信息。

### 请求示例

```bash
curl -X POST http://localhost:8000/api/v1/shift-plans \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 30, "B": 30, "C": 30},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A", "B"],
       "allowed_slots": ["morning", "evening"]},
      {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"],
       "allowed_slots": ["morning", "evening"]},
      {"id": "D3", "power": 15, "allowed_phases": ["B", "C"],
       "allowed_slots": ["evening"]},
      {"id": "D4", "power": 12, "allowed_phases": ["A", "C"],
       "allowed_slots": ["morning"]}
    ]
  }'
```

### 响应示例（有可行方案）

总功率 57，两时段总负载较大值最小为 32（`D3` 只能晚、`D4` 只能早，最优时段
划分为 `D1` 晚、`D2` 早：早 32 / 晚 25）；此时早时段 `D2`(20) 与 `D4`(12)
必分两相，负载差最小为 20，晚时段负载差 15：

```json
{
  "capacities": {"A": 30, "B": 30, "C": 30},
  "feasible": true,
  "peak_total_load": 32,
  "peak_imbalance": 20,
  "slots": {
    "morning": {
      "loads": {"A": 20, "B": 0, "C": 12},
      "total_load": 32,
      "imbalance": 20
    },
    "evening": {
      "loads": {"A": 10, "B": 15, "C": 0},
      "total_load": 25,
      "imbalance": 15
    }
  },
  "assignments": [
    {"device_id": "D1", "slot": "evening", "phase": "A"},
    {"device_id": "D2", "slot": "morning", "phase": "A"},
    {"device_id": "D3", "slot": "evening", "phase": "B"},
    {"device_id": "D4", "slot": "morning", "phase": "C"}
  ],
  "message": "预演成功：已在两时段总负载较大值最小、两时段三相负载差较大值最小的目标下，找到各时段各相均不超容量的错峰接入方案"
}
```

### 响应示例（无可行方案）

```json
{
  "capacities": {"A": 5, "B": 0, "C": 0},
  "feasible": false,
  "peak_total_load": null,
  "peak_imbalance": null,
  "slots": null,
  "assignments": [],
  "message": "无可行方案：不存在每台设备恰选一个允许时段与允许相位、且各时段各相负载均不超容量的错峰接入方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `capacities` | 两时段共用的各相容量（回显请求输入） |
| `feasible` | 是否存在可行错峰接入方案 |
| `peak_total_load` | 两时段总负载（三相之和）的较大值（首要优化目标） |
| `peak_imbalance` | 两时段三相负载差的较大值（次要优化目标） |
| `slots.morning` / `slots.evening` | 早 / 晚时段的三相负载、总负载（`total_load`）与负载差（`imbalance`）；无解时为 `null` |
| `assignments` | 设备安排（按设备编号排序），每台设备恰含一个 `slot`（`morning`/`evening`）与一个 `phase`（`A`/`B`/`C`）；无解时为空数组 |

### 输入校验规则

- 设备数量 **1 ~ 8** 台，设备编号**唯一**且非空；
- 功率为**正整数**；
- `allowed_phases` 为**非空**数组，元素取自 `A` / `B` / `C`（自动去重）；
- `allowed_slots` 为**非空**数组，元素取自 `morning`（早）/ `evening`（晚）
  （自动去重）；
- 各相容量为**非负整数**，两时段共用（各时段各相负载分别不得超过容量）。

不满足规则时返回 `422` 及具体错误信息。

## 运行功率日志复盘

`POST /api/v1/calculations/{id}/power-log-replay` 用于在已有可行分配的记录
基础上，**回放一段时间窗口内的设备实际功率变更日志**，找出超容时段。接口
**沿用记录中的设备相位（每台设备的接入相位）与各相容量**，请求体给出：

- `window_start` / `window_end`：复盘窗口的起止 **Unix 秒**，**起点须早于
  终点**，窗口为**左闭右开** `[window_start, window_end)`；
- `events`：**0 ~ 200 条**设备实际功率变更事件，每条含设备编号、变更时刻
  （Unix 秒）与变更后的**非负整数**功率（`0` 表示设备关停）。

复盘规则：

- **窗口起点所有设备功率为 0**；事件时刻须落在左闭右开窗口内，
  **同一设备同一时刻不得重复**；
- **同一时刻的事件批量生效**：段 `[t_i, t_{i+1})` 的各相负载取 `t_i` 时刻
  事件生效后的功率（`t_i` 依次为窗口起点与各事件时刻，末段延伸至窗口终点）；
- 某段内**任一相负载超过容量**即为超容段；**连续的超容段合并为一段告警**，
  返回每段告警的起止时刻与区间内**各相最大超额量**（未超容相为 0）；
- 同时返回**全窗口各相峰值负载**。

接口**只做复盘，不修改历史计算记录**。记录不存在返回 `404`；原记录无可行
分配返回 `409`；窗口起点不早于终点、事件时刻落在窗口之外、同一设备同一
时刻重复、事件包含未知设备编号或功率为负均返回 `422`。

### 请求示例

```bash
# 先创建一条可行计算记录（D1/D2/D3 分别固定接 A/B/C，容量各 25）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 25, "B": 25, "C": 25},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A"]},
      {"id": "D2", "power": 10, "allowed_phases": ["B"]},
      {"id": "D3", "power": 10, "allowed_phases": ["C"]}
    ]
  }'

# 再对该记录复盘窗口 [1000, 2000) 内的功率变更日志（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/power-log-replay \
  -H "Content-Type: application/json" \
  -d '{
    "window_start": 1000,
    "window_end": 2000,
    "events": [
      {"device_id": "D1", "timestamp": 1100, "power": 20},
      {"device_id": "D1", "timestamp": 1200, "power": 30},
      {"device_id": "D2", "timestamp": 1300, "power": 30},
      {"device_id": "D1", "timestamp": 1400, "power": 0},
      {"device_id": "D2", "timestamp": 1500, "power": 10},
      {"device_id": "D3", "timestamp": 1600, "power": 40}
    ]
  }'
```

### 响应示例

`[1200, 1500)` 内三段连续超容（A 超、A/B 同超、仅 B 超）合并为一段告警，
`[1600, 2000)` 的 C 相超容一直延伸至窗口终点：

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "capacities": {"A": 25, "B": 25, "C": 25},
  "window_start": 1000,
  "window_end": 2000,
  "alerts": [
    {"start": 1200, "end": 1500,
     "max_overload": {"A": 5, "B": 5, "C": 0}},
    {"start": 1600, "end": 2000,
     "max_overload": {"A": 0, "B": 0, "C": 15}}
  ],
  "peak_loads": {"A": 30, "B": 30, "C": 40},
  "message": "复盘完成：窗口内存在超容区间，已将连续超容段合并为告警"
}
```

窗口内各相负载均未超容量时，`alerts` 为空数组：

```json
{
  "id": 1,
  "created_at": "2026-09-25T08:00:00.000000+00:00",
  "capacities": {"A": 25, "B": 25, "C": 25},
  "window_start": 1000,
  "window_end": 2000,
  "alerts": [],
  "peak_loads": {"A": 20, "B": 10, "C": 0},
  "message": "复盘完成：窗口内各相负载均未超过容量"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `capacities` | 各相容量（沿用原计算记录） |
| `window_start` / `window_end` | 复盘窗口起止时刻（Unix 秒，回显请求输入） |
| `alerts` | 合并后的超容告警（按起点升序）；无告警时为空数组 |
| `alerts[].start` / `alerts[].end` | 告警区间起止时刻（Unix 秒，左闭右开） |
| `alerts[].max_overload` | 告警区间内各相最大超额量（负载超出容量的最大值，未超容相为 0） |
| `peak_loads` | 全窗口各相峰值负载 |

### 输入校验规则

- `window_start` 须**早于** `window_end`（均为 Unix 秒整数）；
- 事件数量 **0 ~ 200** 条；每条事件的 `power` 为**非负整数**；
- 事件时刻须落在**左闭右开**窗口 `[window_start, window_end)` 内；
- **同一设备同一时刻不得重复**；不同设备允许同一时刻（批量生效）；
- 事件中的设备编号须**全部存在于计算记录中**（未知设备返回 `422`）；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

不满足规则时返回 `422` 及具体错误信息。

## 电缆盘裁切预演

`POST /api/v1/calculations/{id}/cable-cutting-plan` 用于在已有可行分配的记录
基础上，预演如何从库存电缆盘上为每台设备裁切电缆。仅对**设备不超过 8 台**
的记录开放。请求体给出：

- `segments`：按设备编号逐台给出的电缆段，每台设备一段、长度为**正整数**，
  且**设备编号集合须与计算记录完全一致**（不多、不少、不重复）；每段电缆
  **不可拼接**；
- `reels`：库存电缆盘，**0 ~ 8 个**，编号**唯一**、长度为**正整数**；
- `cut_loss`：同一盘上每个相邻切口的**切割损耗**（非负整数）。

同一盘裁出 `k` 段、各段长度之和为 `S` 时，占用长度为
`S + (k - 1) · cut_loss`（段间共 `k-1` 个切口，单段无损耗），不得超过盘长。
在全部电缆段均可**整体**裁出的方案中，优化目标依次为：

1. **启用盘数最少**（`reel_count`）；
2. 启用盘数相同时，**启用盘总长度最短**（`reel_total_length`）；
3. 仍相同时，取**按设备编号排序**的电缆盘编号序列
   （`reel_sequence`）**字典序最小**者。

接口返回各启用盘的裁切清单 `reel_plans`（按电缆盘编号排序，每盘含按设备
编号排序的 `cuts`、占用 `occupied` 与剩余 `remaining`）。接口**只做预演，
不修改历史计算记录**；不存在可行裁切方案时返回 `feasible: false` 及说明
信息。记录不存在返回 `404`；原记录无可行分配或设备超过 8 台返回 `409`；
设备编号与记录不一致或字段不满足规则返回 `422`。

> 算法等价：令每段权值 `w = 段长 + cut_loss`、每盘容量 `C = 盘长 + cut_loss`，
> 则同盘裁出段集合的可行条件变为「权值之和不超过容量」，即每段整体放入一个
> 盘的装箱问题（各盘容量可不同）。先以逐盘 0/1 背包式子集划分 DP 求最优
> （启用盘数、启用盘总长度），再在最优预算内按设备编号顺序 DFS 取盘编号序列
> 字典序最小者。设备、盘均不超过 8，最坏情形亦可在毫秒~百毫秒级完成。

### 请求示例

```bash
# 先创建一条可行计算记录（D1/D2/D3，容量各 100）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A", "B", "C"]},
      {"id": "D2", "power": 20, "allowed_phases": ["A", "B", "C"]},
      {"id": "D3", "power": 20, "allowed_phases": ["A", "B", "C"]}
    ]
  }'

# 再对该记录请求电缆盘裁切预演（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/cable-cutting-plan \
  -H "Content-Type: application/json" \
  -d '{
    "segments": [
      {"device_id": "D1", "length": 10},
      {"device_id": "D2", "length": 20},
      {"device_id": "D3", "length": 20}
    ],
    "reels": [
      {"id": "R1", "length": 100},
      {"id": "R2", "length": 50}
    ],
    "cut_loss": 0
  }'
```

### 响应示例（存在可行方案）

全部段长之和 50，单个 50 长盘即可装下：启用盘数最少为 1，并取最短的可容纳
盘 `R2(50)`：

```json
{
  "id": 1,
  "created_at": "2026-09-26T08:00:00.000000+00:00",
  "cut_loss": 0,
  "feasible": true,
  "reel_count": 1,
  "reel_total_length": 50,
  "reel_sequence": ["R2", "R2", "R2"],
  "reel_plans": [
    {
      "reel_id": "R2",
      "reel_length": 50,
      "cuts": [
        {"device_id": "D1", "length": 10},
        {"device_id": "D2", "length": 20},
        {"device_id": "D3", "length": 20}
      ],
      "occupied": 50,
      "remaining": 0
    }
  ],
  "message": "预演成功：已在最小化启用盘数、再最小化启用盘总长度、并最小化电缆盘编号序列字典序的目标下，找到全部电缆段均可裁出的方案"
}
```

### 响应示例（无可行裁切方案）

两段各 10、切割损耗 1，同盘需占用 `10 + 1 + 10 = 21`，而唯一盘长仅 20，
且电缆不可拼接：

```json
{
  "id": 2,
  "created_at": "2026-09-26T08:01:00.000000+00:00",
  "cut_loss": 1,
  "feasible": false,
  "reel_count": null,
  "reel_total_length": null,
  "reel_sequence": [],
  "reel_plans": [],
  "message": "无可裁方案：不存在每段电缆整体裁出、不拼接且各盘占用不超过盘长的方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `cut_loss` | 每个相邻切口的切割损耗（回显请求输入） |
| `feasible` | 是否存在可裁出全部电缆段的方案 |
| `reel_count` | 启用盘数（首要优化目标）；无解时为 `null` |
| `reel_total_length` | 启用盘总长度（次要优化目标）；无解时为 `null` |
| `reel_sequence` | 按设备编号排序后各设备所用电缆盘编号序列；无解时为空数组 |
| `reel_plans[].reel_id` / `reel_length` | 启用盘编号 / 原盘长（清单按盘编号排序） |
| `reel_plans[].cuts` | 本盘裁切清单（按设备编号排序），每段不可拼接 |
| `reel_plans[].occupied` | 占用长度 = 段长之和 +（段数 - 1）·切割损耗，不超过盘长 |
| `reel_plans[].remaining` | 剩余长度 = 盘长 - 占用长度（非负） |

### 输入校验规则

- `segments` 为 **1 ~ 8** 段（与记录设备数一致），设备编号**唯一**且与记录
  **完全一致**，段长为**正整数**；
- `reels` 为 **0 ~ 8** 个盘，编号**唯一**、盘长为**正整数**（无盘时无解）；
- `cut_loss` 为**非负整数**；
- 记录不存在返回 `404`；原记录 `feasible=false` 或设备超过 8 台返回 `409`。

不满足规则时返回 `422` 及具体错误信息。

## 电缆路由预演

`POST /api/v1/calculations/{id}/cable-routes` 用于在已有可行分相记录的
基础上，于给定无向图上预演各设备的电缆布设路径。仅对**设备不超过 4 台**
的记录开放。请求体给出：

- `node_count`：节点数，**1 ~ 6**，节点编号为 **0 ~ node_count-1**；
- `edges`：无向边，**0 ~ 8 条**（端点无方向，按 `(u, v)` 规范化），
  **无自环、无重复**（含反向重复）；每条边长度为**正整数**，可容纳电缆数
  （`capacity`）为 **0 ~ 4**，容量为 0 的边不可通行；
- `phase_starts`：A/B/C 各相电缆的**起点节点编号**；
- `device_endpoints`：逐台给出设备终点节点，**设备编号不重复，且须完整
  覆盖计算记录中的全部设备**（不多、不少）。

每台设备沿用记录中的分相结果，从所属相起点走一条**无重复节点的简单路径**
至自身终点；**起点与终点相同时使用零边路径**（节点序列仅含该节点、长度
为 0、不占用任何边）。一条边被一条电缆经过一次即占用 1 个容量，
**每条边经过的电缆数不得超过其容量**。在所有可行方案中，优化目标依次为：

1. **各路径长度之和（总长度）最小**（`total_length`）；
2. 总长度相同时，**按设备编号排序**，依次比较各设备的**路径节点序列**，
   取字典序最小者（节点序列逐位比较，故零边/短前缀路径天然更小）。

接口返回每台设备的路径 `paths`（按设备编号排序，含所属相、终点、节点
序列与路径长度）、最优总长度与各边占用 `edge_usage`（按端点编号排序，
未被使用的边 `occupied` 为 0）。接口**只做预演，不修改历史计算记录**；
不存在可行路由方案时返回 `feasible: false`、空路径与 `null` 总长度。
记录不存在返回 `404`；原记录无可行分配返回 `409`；记录设备超过 4 台、
节点 / 边超规模、自环或重复边、节点引用越界、设备终点映射不完整或字段
不满足规则均返回 `422`。

> 算法：先对每台设备 DFS 枚举自所属相起点到终点的全部简单路径（邻接点
> 按编号升序展开，路径按节点序列字典序依次产生；容量为 0 的边直接剔除），
> 再按设备编号做组合 DFS，候选路径按字典序展开，首个取得更小总长度的
> 完整方案即字典序最小者；以「当前长度 + 剩余设备各自最短路径长度」的
> 乐观下界剪枝并记忆失败状态。设备 ≤ 4、节点 ≤ 6、边 ≤ 8，瞬时完成。

### 请求示例

```bash
# 先创建一条可行计算记录（D1 固定接 A、D2 固定接 B）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A"]},
      {"id": "D2", "power": 20, "allowed_phases": ["B"]}
    ]
  }'

# 再对该记录请求电缆路由预演（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/cable-routes \
  -H "Content-Type: application/json" \
  -d '{
    "node_count": 4,
    "edges": [
      {"u": 0, "v": 1, "length": 2, "capacity": 2},
      {"u": 1, "v": 2, "length": 3, "capacity": 2},
      {"u": 0, "v": 3, "length": 5, "capacity": 4},
      {"u": 3, "v": 2, "length": 1, "capacity": 4}
    ],
    "phase_starts": {"A": 0, "B": 1, "C": 0},
    "device_endpoints": [
      {"device_id": "D1", "endpoint": 2},
      {"device_id": "D2", "endpoint": 3}
    ]
  }'
```

D1 自 A 相起点 0 到 2：路径 `0-1-2` 长度 5 与 `0-3-2` 长度 6，取前者；
D2 自 B 相起点 1 到 3：路径 `1-0-3` 长度 7 与 `1-2-3` 长度 4，取后者。
最优总长度为 `5 + 4 = 9`，且两条路径不共边。

### 响应示例（存在可行方案）

```json
{
  "id": 1,
  "created_at": "2026-09-26T08:00:00.000000+00:00",
  "node_count": 4,
  "feasible": true,
  "total_length": 9,
  "paths": [
    {"device_id": "D1", "phase": "A", "endpoint": 2, "nodes": [0, 1, 2], "length": 5},
    {"device_id": "D2", "phase": "B", "endpoint": 3, "nodes": [1, 2, 3], "length": 4}
  ],
  "edge_usage": [
    {"u": 0, "v": 1, "length": 2, "capacity": 2, "occupied": 1},
    {"u": 0, "v": 3, "length": 5, "capacity": 4, "occupied": 0},
    {"u": 1, "v": 2, "length": 3, "capacity": 2, "occupied": 2},
    {"u": 2, "v": 3, "length": 1, "capacity": 4, "occupied": 1}
  ],
  "message": "预演成功：已在最小化各路径总长度、同值时按设备编号排序比较路径节点序列字典序的目标下，找到每台设备自所属相起点到终点、各边占用均不超容量的电缆路由方案"
}
```

### 响应示例（无可行方案）

两台设备的唯一路径共用容量为 1 的瓶颈边时（或某台设备的终点不可达），
返回：

```json
{
  "id": 2,
  "created_at": "2026-09-26T08:01:00.000000+00:00",
  "node_count": 4,
  "feasible": false,
  "total_length": null,
  "paths": [],
  "edge_usage": [
    {"u": 0, "v": 1, "length": 1, "capacity": 1, "occupied": 0}
  ],
  "message": "无可布路由方案：不存在每台设备均以无重复节点路径到达终点、且每条边经过电缆数不超过容量的方案"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `node_count` | 节点数（回显请求输入） |
| `feasible` | 是否存在满足各边容量的电缆路由方案 |
| `total_length` | 各路径长度之和（最优总长度）；无解时为 `null` |
| `paths[].phase` | 设备所属相（沿用计算记录，决定路径起点） |
| `paths[].nodes` | 路径经过的节点序列（无重复节点）；起终点相同时为单节点零边路径 |
| `paths[].length` | 路径总长度（零边路径为 0） |
| `edge_usage[].capacity` / `occupied` | 边可容纳的电缆数（0 ~ 4）/ 实际经过的电缆数（不超过容量） |

### 输入校验规则

- 记录设备数 **1 ~ 4** 台（记录本身设备超过 4 台返回 `422`）；
- `node_count` 为 **1 ~ 6** 的整数，节点编号 **0 ~ node_count-1**；
- `edges` 为 **0 ~ 8** 条无向边，**无自环、无重复**（含反向重复），
  端点节点引用必须有效，长度为**正整数**，容量为 **0 ~ 4**；
- `phase_starts` 中 A/B/C 起点与每台设备 `endpoint` 都必须是有效节点；
- `device_endpoints` 设备编号**不重复**且与记录**完全一致**；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

不满足规则时返回 `422` 及具体错误信息。

## 检修停机排程预演

`POST /api/v1/calculations/{id}/maintenance-schedule` 用于在已有可行分配的记录
基础上，预演若干设备停机检修时的排程。请求体给出：

- `devices`：参与检修的设备，**1 ~ 6 台**，逐台给出
  - `device_id`：设备编号，须**存在于计算记录中**且**不得重复**（每台设备
    至多检修一次）；
  - `duration`：连续停机时长，**1 ~ 3 个时隙**；
  - `earliest_start` / `latest_start`：最早 / 最晚开始时隙，取值 **0 ~ 11**，
    **最早开始不得晚于最晚开始**；
- `total_slots`：总时隙数，**1 ~ 12**（时隙编号为 `0 ~ total_slots-1`）；
- `simultaneous_limit`：每时隙同时检修设备数上限，**1 ~ 3**；
- `lower_bounds`：**A/B/C 各相非负最低在线负载**。

停机区间为半开区间 `[start, start+duration)`，且**最晚开始 + 停机时长不得超过
总时隙数**（即停机必须在总时隙窗口内完成）。**未选设备始终在线**；选中设备在
停机区间内**不计入所属相负载**，其余时隙按记录功率运行。排程要求：

- 每台选中设备**恰好检修一次**（一个连续区间）；
- **每时隙同时检修的设备数不超过** `simultaneous_limit`；
- **每时隙各相在线负载不低于** `lower_bounds` 中对应相的下限
  （在线负载 = 该相全部设备功率之和 − 该时隙该相停机设备功率之和）。

在所有可行排程中，优化目标依次为：

1. **最小化最后完工时隙**（`completion_slot` =
   `max(start + duration)`，即全部检修完成时刻）；
2. 完工时隙相同时，取**按设备编号排序的开始时隙序列字典序最小**者。

接口返回各设备检修安排 `schedule`（按设备编号排序，含开始时隙、时长与完工
时隙）以及 `slot_loads`（逐时隙、按时隙编号升序的各相在线负载）。接口**只做
预演，不修改历史计算记录**；不存在可行排程时返回 `feasible: false`、空排程与
具体无解说明。记录不存在返回 `404`；原记录无可行分配（`feasible=false`）
返回 `409`；检修设备未知或重复、字段超出取值范围、最早开始晚于最晚开始或
停机区间超出总时隙窗口均返回 `422`。

> 算法：先做整体性必要判定（某相全部设备在线仍低于下限、总停机设备·时隙需求
> 超过「同时检修上限 × 总时隙数」、单台设备功率超过其所属相可停电余量），
> 再以「最小候选值优先（MRV）+ 前向检查」的回溯判定给定完工时限是否可行，
> 对完工时限二分求出最小完工时隙；最后在最优时限内按设备编号顺序、开始时隙
> 升序做字典序 DFS，首个完整方案即字典序最小者。参与检修设备不超过 6、
> 时隙不超过 12，瞬时完成。

### 请求示例

```bash
# 先创建一条可行计算记录（D1 接 A 功率 10，D2 接 B 功率 20，D3 接 C 功率 30）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A"]},
      {"id": "D2", "power": 20, "allowed_phases": ["B"]},
      {"id": "D3", "power": 30, "allowed_phases": ["C"]}
    ]
  }'

# 再对该记录请求检修停机排程预演（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/maintenance-schedule \
  -H "Content-Type: application/json" \
  -d '{
    "devices": [
      {"device_id": "D1", "duration": 2, "earliest_start": 0, "latest_start": 2},
      {"device_id": "D2", "duration": 1, "earliest_start": 0, "latest_start": 3}
    ],
    "total_slots": 6,
    "simultaneous_limit": 1,
    "lower_bounds": {"A": 0, "B": 0, "C": 0}
  }'
```

同时检修上限为 1，故 D1（时长 2）与时隙 0 开始的 D2 不能重叠；字典序最小安排
为 D1 占时隙 0、1，D2 最早可放时隙 2，最后完工时隙为 3（未选设备 D3 始终
在线，C 相负载恒为 30）：

### 响应示例（存在可行排程）

```json
{
  "id": 1,
  "created_at": "2026-09-26T08:00:00.000000+00:00",
  "total_slots": 6,
  "simultaneous_limit": 1,
  "lower_bounds": {"A": 0, "B": 0, "C": 0},
  "feasible": true,
  "completion_slot": 3,
  "schedule": [
    {"device_id": "D1", "phase": "A", "power": 10, "start": 0, "duration": 2, "finish": 2},
    {"device_id": "D2", "phase": "B", "power": 20, "start": 2, "duration": 1, "finish": 3}
  ],
  "slot_loads": [
    {"slot": 0, "loads": {"A": 0, "B": 20, "C": 30}},
    {"slot": 1, "loads": {"A": 0, "B": 20, "C": 30}},
    {"slot": 2, "loads": {"A": 10, "B": 0, "C": 30}},
    {"slot": 3, "loads": {"A": 10, "B": 20, "C": 30}},
    {"slot": 4, "loads": {"A": 10, "B": 20, "C": 30}},
    {"slot": 5, "loads": {"A": 10, "B": 20, "C": 30}}
  ],
  "message": "预演成功：已在最小化最后完工时隙、同值时取按设备编号排序的开始时隙序列字典序最小的目标下，找到每台选中设备各检修一次、每时隙同时检修数不超上限、各相在线负载不低于下限的排程"
}
```

### 响应示例（无可行排程）

例如 A 相仅 D1 一台设备（功率 10），却要求 A 相最低在线负载为 10，则 D1
任何时隙停机都会使 A 相负载降为 0：

```json
{
  "id": 2,
  "created_at": "2026-09-26T08:01:00.000000+00:00",
  "total_slots": 6,
  "simultaneous_limit": 1,
  "lower_bounds": {"A": 10, "B": 0, "C": 0},
  "feasible": false,
  "completion_slot": null,
  "schedule": [],
  "slot_loads": [],
  "message": "无可行排程：设备 D1 停机时 A 相在线负载将降至 0，低于该相最低在线负载 10"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `total_slots` / `simultaneous_limit` / `lower_bounds` | 总时隙数 / 同时检修上限 / 各相最低在线负载（均回显请求输入） |
| `feasible` | 是否存在满足全部约束的检修排程 |
| `completion_slot` | 最后完工时隙 `max(start+duration)`（首要优化目标）；无解时为 `null` |
| `schedule` | 各设备检修安排（按设备编号排序），含开始时隙 `start`、时长 `duration` 与完工时隙 `finish`；无解时为空数组 |
| `slot_loads` | 逐时隙各相在线负载（按时隙编号升序，均不低于下限）；无解时为空数组 |

### 输入校验规则

- 参与检修设备 **1 ~ 6 台**，编号**唯一**且**均存在于计算记录中**；
- `duration` 为 **1 ~ 3** 的整数；`earliest_start` / `latest_start` 为 **0 ~ 11**
  的整数，且 `earliest_start <= latest_start`；
- `total_slots` 为 **1 ~ 12**；`simultaneous_limit` 为 **1 ~ 3**；
- `lower_bounds` 中 A/B/C 均为**非负整数**；
- 每台设备须满足 `latest_start + duration <= total_slots`（停机在窗口内完成）；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

不满足规则时返回 `422` 及具体错误信息。

## 仪表校准预演

`POST /api/v1/calculations/{id}/meter-calibration` 用于在已有可行分配的记录
基础上，依据若干**在线快照**标定仪表三个通道与 A/B/C 相的对应关系及各相
固定底载。请求体 `snapshots` 给出 **3 ~ 8 组**快照，每组包含：

- `online_device_ids`：当时**在线的记录内设备编号**（均须存在于计算记录中，
  组内编号不重复；可为空数组表示当时无设备在线）；
- `readings`：仪表**三个通道的非负整数读数**，固定按通道 **1/2/3** 排列。

设备沿用计算记录中的**功率与固定相位**。假设仪表三个通道与 A/B/C 相
**一一对应**，且每相存在一个**跨所有快照不变的非负整数底载**：若通道 `c`
对应相 `p`、该相底载为 `b_p`，则快照 `t` 通道 `c` 的**预测读数**为

```
predicted(c, t) = 该相在线设备功率之和(t) + b_p
```

接口联合选择通道对应关系（共 `3! = 6` 种）与三相底载，目标依次为：

1. **最小化全部快照、全部通道绝对误差的最大值**（`max_error`）；
2. 再**最小化绝对误差总和**（`total_error`）；
3. 仍相同时，先按 **A/B/C 对应的通道序列**字典序、再按 **A/B/C 底载序列**
   字典序裁决（通道编号与底载均按数值比较）。

返回三相通道对应 `channel_mapping`、各相底载 `base_loads`，以及逐快照的
在线设备（按编号排序）、各相在线功率和 `phase_power`、三通道预测读数
`predicted_readings` 与绝对误差 `errors`。接口**只做预演，不修改历史计算
记录**。记录不存在返回 `404`；原记录无可行分配返回 `409`；快照数不在
3 ~ 8、在线设备编号未知或组内重复、读数不是三个非负整数均返回 `422`。

> 算法：通道对应（仅 6 种排列）确定后各相完全解耦。对每相令
> `d_t = 通道读数 − 该相在线设备功率和`，问题化为以非负整数常数 `b`
> 拟合序列 `d_t`：最小最大误差仅由 `min d`、`max d` 决定（最优区间与
> 非负轴无交集时只能取 `b=0`）；给定最大误差预算后，总误差最小的 `b`
> 为整数中位数，落在预算可行区间之外时取区间边界（并保证同总误差时取
> 最小底载）。故先枚举 6 种对应求全局最小最大误差，再在该预算下按通道
> 序列字典序枚举对应、各相独立选最优底载，首个总误差最小的方案即字典序
> 裁决结果。快照不超过 8 组，计算瞬时完成。

完整的接口参数与返回结构也可在启动后通过 Swagger 文档交互查看：
http://localhost:8000/docs 。

### 请求示例

```bash
# 先创建一条可行计算记录（D1/D2/D3 分别固定接 A/B/C，功率 10/20/30）
curl -X POST http://localhost:8000/api/v1/calculations \
  -H "Content-Type: application/json" \
  -d '{
    "capacities": {"A": 100, "B": 100, "C": 100},
    "devices": [
      {"id": "D1", "power": 10, "allowed_phases": ["A"]},
      {"id": "D2", "power": 20, "allowed_phases": ["B"]},
      {"id": "D3", "power": 30, "allowed_phases": ["C"]}
    ]
  }'

# 再对该记录提交 4 组仪表快照（假设记录 id 为 1）
curl -X POST http://localhost:8000/api/v1/calculations/1/meter-calibration \
  -H "Content-Type: application/json" \
  -d '{
    "snapshots": [
      {"online_device_ids": ["D1"],             "readings": [15, 7, 2]},
      {"online_device_ids": ["D2"],             "readings": [5, 27, 2]},
      {"online_device_ids": ["D3"],             "readings": [5, 7, 32]},
      {"online_device_ids": ["D1", "D2", "D3"], "readings": [15, 27, 32]}
    ]
  }'
```

三组单机快照分别标定出 A/B/C 相对应通道 1/2/3、底载 5/7/2，全部读数与预测
完全吻合（最大误差、总误差均为 0）：

### 响应示例（完全吻合）

```json
{
  "id": 1,
  "created_at": "2026-09-26T08:00:00.000000+00:00",
  "channel_mapping": {"A": 1, "B": 2, "C": 3},
  "base_loads": {"A": 5, "B": 7, "C": 2},
  "snapshots": [
    {
      "online_device_ids": ["D1"],
      "observed_readings": [15, 7, 2],
      "phase_power": {"A": 10, "B": 0, "C": 0},
      "predicted_readings": [15, 7, 2],
      "errors": [0, 0, 0]
    },
    {
      "online_device_ids": ["D2"],
      "observed_readings": [5, 27, 2],
      "phase_power": {"A": 0, "B": 20, "C": 0},
      "predicted_readings": [5, 27, 2],
      "errors": [0, 0, 0]
    },
    {
      "online_device_ids": ["D3"],
      "observed_readings": [5, 7, 32],
      "phase_power": {"A": 0, "B": 0, "C": 30},
      "predicted_readings": [5, 7, 32],
      "errors": [0, 0, 0]
    },
    {
      "online_device_ids": ["D1", "D2", "D3"],
      "observed_readings": [15, 27, 32],
      "phase_power": {"A": 10, "B": 20, "C": 30},
      "predicted_readings": [15, 27, 32],
      "errors": [0, 0, 0]
    }
  ],
  "max_error": 0,
  "total_error": 0,
  "message": "预演成功：已联合选择三通道与 A/B/C 相的对应关系及各相跨快照不变的非负整数底载，先最小化全部读数绝对误差的最大值、再最小化绝对误差总和，同值按 A/B/C 对应的通道序列、底载序列字典序裁决"
}
```

### 响应示例（读数含噪声）

若 A 相（通道 1）两次读数分别为 `16`、`14`（在线设备 D1 功率 10），最优
底载仍为 5，两个读数的绝对误差各为 1：

```json
{
  "id": 1,
  "created_at": "2026-09-26T08:05:00.000000+00:00",
  "channel_mapping": {"A": 1, "B": 2, "C": 3},
  "base_loads": {"A": 5, "B": 7, "C": 2},
  "snapshots": [
    {"online_device_ids": ["D1"], "observed_readings": [16, 7, 2],
     "phase_power": {"A": 10, "B": 0, "C": 0},
     "predicted_readings": [15, 7, 2], "errors": [1, 0, 0]},
    {"online_device_ids": ["D1"], "observed_readings": [14, 7, 2],
     "phase_power": {"A": 10, "B": 0, "C": 0},
     "predicted_readings": [15, 7, 2], "errors": [1, 0, 0]},
    {"online_device_ids": ["D2"], "observed_readings": [5, 27, 2],
     "phase_power": {"A": 0, "B": 20, "C": 0},
     "predicted_readings": [5, 27, 2], "errors": [0, 0, 0]}
  ],
  "max_error": 1,
  "total_error": 2,
  "message": "预演成功：已联合选择三通道与 A/B/C 相的对应关系及各相跨快照不变的非负整数底载，先最小化全部读数绝对误差的最大值、再最小化绝对误差总和，同值按 A/B/C 对应的通道序列、底载序列字典序裁决"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `channel_mapping` | A/B/C 各相对应的仪表通道（取值 1/2/3，互不相同） |
| `base_loads` | A/B/C 各相跨快照不变的非负整数底载 |
| `snapshots[].online_device_ids` | 该快照当时在线的设备编号（按编号排序） |
| `snapshots[].observed_readings` | 三通道实测读数（按通道 1/2/3 排列，回显请求输入） |
| `snapshots[].phase_power` | A/B/C 各相在线设备功率之和（不含底载） |
| `snapshots[].predicted_readings` | 三通道预测读数（对应相在线功率和 + 底载） |
| `snapshots[].errors` | 三通道绝对误差 `|实测读数 − 预测读数|` |
| `max_error` / `total_error` | 全部误差的最大值（首要目标）/ 总和（次要目标） |

### 输入校验规则

- `snapshots` 为 **3 ~ 8** 组，按提交顺序返回；
- 每组 `online_device_ids` 中的编号须**全部存在于计算记录中**，且**组内不
  重复**（允许空数组）；
- `readings` 必须恰为 **3 个**非负整数（通道 1/2/3）；
- 记录不存在返回 `404`；原记录 `feasible=false` 返回 `409`。

不满足规则时返回 `422` 及具体错误信息。

## 本地开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload        # 服务地址 http://127.0.0.1:8000
```

运行测试：

```bash
pytest                               # 全部测试（求解器 + API）
python3 -m unittest tests.test_solver  # 仅求解器测试（无第三方依赖）
```

## 项目结构

```
├── app/
│   ├── main.py       # FastAPI 应用与路由
│   ├── schemas.py    # 请求 / 响应数据模型与校验
│   ├── solver.py     # 三相排布求解器（DFS + 下界剪枝，纯标准库）
│   └── db.py         # SQLite 持久化（启动时自动建表）
├── tests/            # 求解器单元测试（含随机对拍）与 API 集成测试
├── requirements.txt  # 运行依赖
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 求解算法说明

按设备编号排序后做深度优先搜索，相位按 A→B→C 顺序展开，因此完整方案按
「设备编号排序后的相位序列」字典序依次产生；仅在负载差值**严格更小**时更新最优解，
同差值时自然保留字典序最小方案。配合容量约束剪枝与负载差值下界剪枝，
12 台设备的最坏情形亦可在秒级内完成求解。

**扩容建议**（`capacity-upgrade`）同样按设备编号排序、相位按 A→B→C 展开做 DFS，
分两遍搜索：第一遍求三相扩容总量的最小值，第二遍在总量固定最小的方案中以
`(单相最大扩容量, 相位序列)` 为键选出最优（即先最小化单相最大扩容，再取字典序
最小）。搜索中利用「只允许单一相位的设备造成的被迫超载 + 自由设备功率扣除各相
空闲容量」构造扩容总量下界进行剪枝，12 台设备的最坏情形亦可在数秒内完成。

**稳健分相预演**（`robust-rehearsals`）利用如下归约：对固定分配，各相负载可
独立取遍「功率下界之和 ~ 功率上界之和」内的所有整数，因此任意功率组合下各相
均不超容量 ⟺ 各相负载**上界**不超容量；而最坏负载差
`max(max_p L_p - min_p L_p) = max_{p≠q}(上界_p - 下界_q)`（注意并非「上界最大值
- 下界最小值」：同一相不可能同时取到上界与下界，故只取相异相位对）。据此在与
主求解器相同的 DFS 框架（按设备编号排序、相位按 A→B→C 展开、仅严格更优才更新、
容量约束与下界剪枝）中直接求解，12 台设备的最坏情形亦可在数秒内完成。

**启动顺序预演**（`startup-plan`）利用「顺序即子集路径」的结构：任一启动顺序对应
子集 DAG 上 空集→全集 的一条路径——途经节点为已启动设备集合（其稳定状态负载只
取决于该集合），途经边为一次启动（瞬时负载只取决于启动前集合与该设备）。节点与
边的负载差均与到达路径无关，故「最小化全过程负载差峰值」等价于该 DAG 上的
**minimax 路径**：按子集递推各集合的最小可达峰值即可（设备不超过 12 台，状态数
`2^12 = 4096`，瞬时完成）；不存在满足容量的路径时即为无安全顺序。得到最优峰值后，
先自全集反向递推「途经负载差均不超最优峰值、且满足容量时可达全集」的集合，再从
空集出发每一步选取「后缀仍可完成」的编号最小设备，所得顺序即同峰值下设备编号
序列字典序最小者。

**单相故障保供预演**（`phase-fault-rehearsal`）只需对故障相设备（至多 12 台）做
DFS：健康相设备保持原分配，其负载预先计入健康相；每台故障相设备的可选动作按
「允许接入的健康相 A→B→C，最后断开」展开，故完整方案天然按「设备编号排序后的
相位选择序列」字典序（A＜B＜C＜断开）依次产生。目标键为 `(保留功率, 保留设备数)`，
均只统计故障相设备中被保留的部分（健康相部分为常量），仅在严格更优时更新最优解，
同值自然保留字典序最小方案。配合「剩余设备全部保留也无法超过当前最优」的功率 /
数量乐观上界剪枝，12 台设备的最坏情形亦可瞬时完成；全部断开恒可行，故障相负载
恒为零。

**新增设备接入预演**（`device-addition-plan`）将新旧设备合并后按编号排序做 DFS，
相位按 A→B→C 展开，完整方案按「全部设备编号排序后的相位序列」字典序依次产生。
目标键为 `(原设备改相台数, 负载差)`：仅严格更优才更新，同键时先枚举到的方案
字典序最小。剪枝包括容量约束、「改相台数超过当前最优」剪枝（改相台数只增不减），
以及改相台数持平最优时沿用主求解器的负载差下界剪枝（此时改相台数与负载差均
不可能再严格更优）。新旧合计不超过 12 台，最坏情形亦可快速完成。

**双时段错峰接入规划**（`shift-plans`）利用时段与相位的可分解结构：时段分配
确定后，两时段的相位分配互不影响（容量约束按时段逐相独立）。求解分两步：
先对全部 `2^n` 个设备子集分别求解「该子集作为单一时段设备集合」的相位子问题
（与主求解器同构的 DFS，求最小三相负载差；全部子集的总枚举量为 `4^n`，
设备不超过 8 台时仅 65536）；再按时段序列字典序枚举全部 `2^n` 个时段分配
（设备须允许对应时段且两时段相位子问题均可行），以 `(两时段总负载较大值,
两时段负载差较大值)` 为目标键、仅严格更优才更新，同键时先枚举到的时段序列
字典序最小。最后以最优负载差峰值为各时段预算，对两时段设备子集分别做
「预算内字典序最小」的相位 DFS（相位按 A→B→C 展开，首个满足预算的完整方案
即字典序最小）——注意不能简单取各时段最小负载差的方案：联合目标只要求两时段
负载差不超过最优峰值，某时段在预算内放宽容差可换取字典序更小的相位选择。
两时段各自最优的相位子序列交错合并，即 (时段, 相位) 联合序列字典序最小的方案。
全部计算为精确枚举，8 台设备的最坏情形亦在秒级内完成。

**运行功率日志复盘**（`power-log-replay`）为确定性模拟：沿用记录中的设备相位
与各相容量，窗口起点所有设备功率为 0，将事件按时刻分组（同一时刻批量生效），
以「窗口起点 → 各事件时刻 → 窗口终点」为段边界做一次顺序扫描——每段各相负载
即该相设备当前功率之和，逐段更新各相峰值；某段任一相负载超过容量即为超容段，
相邻超容段首尾相接、直接合并为一段告警，并取合并区间内各相超额量的最大值。
事件不超过 200 条，扫描一次即可完成。

**电缆盘裁切预演**（`cable-cutting-plan`）先做权值变换：令每段权值
`w = 段长 + 切割损耗`、每盘容量 `C = 盘长 + 切割损耗`，则「同盘裁出 `k` 段、
占用为段长之和加 `(k-1)·损耗`」恰好等价于「同盘各段权值之和不超过容量」，
于是问题归约为每段电缆整体放入一个盘、各盘容量可不同的装箱问题。求解分两步：
先以逐盘 0/1 背包式子集划分 DP（状态 `dp[mask]` 记录裁出 `mask` 中各段的最优
`(启用盘数, 启用盘总长度)`，每个盘倒序转移、至多使用一次）求出最优目标值；
再在最优 `(盘数, 总长度)` 预算内按设备编号顺序 DFS——所有盘严格按编号顺序
展开（已启用盘与未启用盘交错逐位比较，而非优先复用已启用盘），配合容量、
盘数 / 总长度预算剪枝与失败状态记忆化，首个完整方案即按设备编号排序的盘编号
序列字典序最小者；最后按原口径汇总各盘裁切清单的占用与剩余长度。设备、盘均
不超过 8（子集状态 `2^8`、单盘子集枚举总量 `3^8`），最坏情形亦可快速完成。

**电缆路由预演**（`cable-routes`）先对每台设备单独 DFS 枚举其自所属相起点
到终点的全部无重复节点简单路径：邻接节点按编号升序展开，到达终点即记录、
不再延伸（无重复节点路径不可能再次经过终点），候选路径天然按节点序列
字典序依次产生；容量为 0 的边不可能承载电缆，直接不纳入邻接表。随后按
设备编号做组合 DFS，每台设备的候选路径按字典序展开，边容量随铺设 / 回溯
增减；完整方案按「各设备路径节点序列依次比较」的字典序首次产生，故仅在
总长度严格更小时更新最优解，同总长度先枚举到的方案即字典序最小者。
剪枝包括「当前长度 + 剩余设备各自最短路径长度」的总长度乐观下界（下界
达到当前最优时，子树至多给出等长但字典序更靠后的方案，可安全剪除）与
失败状态记忆。设备不超过 4、节点不超过 6、边不超过 8，最坏情形瞬时完成。

**检修停机排程预演**（`maintenance-schedule`）先做整体性必要判定并给出可读的
无解说明：某相全部设备在线时负载仍低于该相下限；总停机设备·时隙需求
`Σ duration_i` 超过「同时检修上限 × 总时隙数」；单台设备功率超过其所属相
「基础负载 − 下限」的可停电余量（该设备任何时隙停机都会击穿下限）。随后用
「最小候选值优先（MRV）+ 前向检查」的回溯判定给定完工时限 `L` 下是否可行：
设备的候选开始时隙只取决于当前停机预订（后续预订只会占用容量），故未安排
设备在当前预订下若无候选即可安全剪枝；可行性关于 `L` 单调，二分即得最小
完工时隙 `L*`。最后在 `L*` 时限内按设备编号顺序、开始时隙升序做 DFS（枚举
次序即「按设备编号排序的开始时隙序列」的字典序），配合同样的前向检查剪枝，
首个完整方案即字典序最小者；逐时隙各相在线负载由基础负载减去该时隙停机
设备功率直接汇总。参与检修设备不超过 6、每台候选开始时隙不超过 12，
最坏情形瞬时完成。

**仪表校准预演**（`meter-calibration`）中，通道与相的一一对应仅有 `3! = 6`
种排列；任一排列下各相完全解耦——对相 `p` 及其对应通道，令
`d_t = 通道读数 − 该相在线设备功率和`，则预测误差即 `|d_t − b_p|`，问题
化为以非负整数常数 `b_p` 拟合序列 `d_t`。无整数约束时使最大误差最小的
区间为 `[(min d + max d − 1) // 2, (min d + max d) // 2]`，与非负整数轴
相交时最优最大误差为 `ceil((max d − min d) / 2)`，否则最优底载只能取 0、
误差为 `max |d|`。先枚举 6 种排列求全局最小最大误差 `M*`；再在每相最大
误差不超过 `M*` 的预算区间
`[max(0, max d − M*), min d + M*]` 内选底载——总绝对误差最小的整数底载
为中位数，与预算区间的交集非空时取交集最小值（同总误差取最小底载），
预算区间整体低于 / 高于中位数区间时分别取区间上 / 下端。排列按 A/B/C
对应通道序列字典序枚举、仅总误差严格更优才更新，故同值时先枚举到的
排列与底载序列即字典序裁决结果。快照不超过 8 组，全部计算为 6 个排列上
的线性扫描，瞬时完成。

"""示例数据：每个模块给几条不同状态的记录，方便起服务后立刻看到内容。

聚合层（gold）效果视图所需的联动数据集中在 silver / gold / quality / meta 四个模块：
- silver（清洗层）记录上游清洗表的批次完成度、计划完成时间与最近完成时间；
- gold（聚合层）记录聚合视图依赖哪些清洗表、更新频率与所属分层；
- quality / meta 记录可从效果视图直接定位的质量指标与元数据版本。

时间类字段在导入时按“当前时刻”动态生成，保证值班场景（上午批次一张清洗表延迟
20 分钟、另一张正常完成）开箱即可复现，而不是写死在某一天。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _build_lakehouse_seed(now: datetime) -> dict[str, list[dict[str, Any]]]:
    """构造清洗层、聚合层、质量监控、元数据中心四块联动示例数据。

    以“当前时刻往前 20 分钟”作为上午批次的计划完成时刻：一张清洗表延迟 20 分钟
    仍未跑完（完成度 60%），另一张提前 5 分钟正常完成，值班场景随时可复现。
    """
    batch_plan = now - timedelta(minutes=20)
    yesterday_plan = batch_plan - timedelta(days=1)

    silver_rows: list[dict[str, Any]] = [
        {
            "id": 1,
            "status": "运行中",
            "pending": True,
            "abnormal": True,
            "表编号": "SILV-0001",
            "上游原始表": "BRON-0001 订单主表",
            "清洗脚本": "clean_order_master.py",
            "格式校验": "非空+枚举校验",
            "异常过滤": "剔除测试与黑名单订单",
            "去重字段": "order_id",
            "输出路径": "lake/silver/order_master",
            "调度周期": "每日",
            "所属分层": "DWS",
            "更新频率": "每日",
            "计划完成时间": _fmt(batch_plan),
            "最近完成时间": _fmt(yesterday_plan),
            "完成度": 60,
            "批次状态": "延迟",
        },
        {
            "id": 2,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "表编号": "SILV-0002",
            "上游原始表": "BRON-0002 支付流水表",
            "清洗脚本": "clean_payment_flow.py",
            "格式校验": "金额精度+币种校验",
            "异常过滤": "剔除重复支付流水",
            "去重字段": "payment_id",
            "输出路径": "lake/silver/payment_flow",
            "调度周期": "每日",
            "所属分层": "DWS",
            "更新频率": "每日",
            "计划完成时间": _fmt(batch_plan),
            "最近完成时间": _fmt(batch_plan - timedelta(minutes=5)),
            "完成度": 100,
            "批次状态": "正常",
        },
        {
            "id": 3,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "表编号": "SILV-0003",
            "上游原始表": "BRON-0003 商品维表",
            "清洗脚本": "clean_product_dim.py",
            "格式校验": "类目层级校验",
            "异常过滤": "剔除下架脏数据",
            "去重字段": "product_id",
            "输出路径": "lake/silver/product_dim",
            "调度周期": "每小时",
            "所属分层": "DWD",
            "更新频率": "每小时",
            "计划完成时间": _fmt(now - timedelta(minutes=18)),
            "最近完成时间": _fmt(now - timedelta(minutes=18)),
            "完成度": 100,
            "批次状态": "正常",
        },
        {
            "id": 4,
            "status": "已停用",
            "pending": True,
            "abnormal": True,
            "表编号": "SILV-0004",
            "上游原始表": "BRON-0004 会员行为表",
            "清洗脚本": "clean_member_event.py",
            "格式校验": "事件类型校验",
            "异常过滤": "剔除爬虫流量",
            "去重字段": "event_id",
            "输出路径": "lake/silver/member_event",
            "调度周期": "每周",
            "所属分层": "ADS",
            "更新频率": "每周",
            "计划完成时间": _fmt(batch_plan),
            # 最近完成时间落在未来：属于非法时间范围，效果视图必须判为时间异常，不能算健康。
            "最近完成时间": _fmt(now + timedelta(days=1)),
            "完成度": 100,
            "批次状态": "时间异常",
        },
        {
            "id": 5,
            "status": "待校验",
            "pending": True,
            "abnormal": True,
            "表编号": "SILV-0005",
            "上游原始表": "BRON-0005 退款申请表",
            "清洗脚本": "clean_refund_request.py",
            "格式校验": "退款原因枚举校验",
            "异常过滤": "剔除无效退款单",
            "去重字段": "refund_id",
            "输出路径": "lake/silver/refund_request",
            "调度周期": "每日",
            "所属分层": "ADS",
            "更新频率": "每日",
            "计划完成时间": _fmt(batch_plan),
            "最近完成时间": _fmt(batch_plan - timedelta(days=2)),
            "完成度": 35,
            "批次状态": "延迟",
        },
    ]

    gold_rows: list[dict[str, Any]] = [
        {
            "id": 1,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "视图编号": "GOLD-0001",
            "上游清洗表": "SILV-0001,SILV-0002",
            "聚合维度": "订单日期·门店",
            "度量字段": "支付金额、订单数",
            "聚合函数": "SUM/COUNT",
            "物化策略": "全量重刷",
            "更新频率": "每日",
            "数据新鲜度": "",
            "所属分层": "ADS",
        },
        {
            "id": 2,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "视图编号": "GOLD-0002",
            "上游清洗表": "SILV-0003",
            "聚合维度": "商品类目",
            "度量字段": "曝光量、点击量",
            "聚合函数": "SUM",
            "物化策略": "增量合并",
            "更新频率": "每小时",
            "数据新鲜度": "",
            "所属分层": "DWS",
        },
        {
            "id": 3,
            "status": "待校验",
            "pending": True,
            "abnormal": True,
            "视图编号": "GOLD-0003",
            "上游清洗表": "SILV-0004",
            "聚合维度": "会员等级",
            "度量字段": "活跃会员数",
            "聚合函数": "COUNT_DISTINCT",
            "物化策略": "全量重刷",
            "更新频率": "每周",
            "数据新鲜度": "",
            "所属分层": "ADS",
        },
        {
            "id": 4,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "视图编号": "GOLD-0004",
            "上游清洗表": "SILV-0002,SILV-0005",
            "聚合维度": "订单日期·渠道",
            "度量字段": "退款金额、退款率",
            "聚合函数": "SUM/AVG",
            "物化策略": "增量合并",
            "更新频率": "每日",
            "数据新鲜度": "",
            "所属分层": "ADS",
        },
        {
            "id": 5,
            "status": "草稿",
            "pending": True,
            "abnormal": False,
            "视图编号": "GOLD-0005",
            "上游清洗表": "SILV-9999",
            "聚合维度": "履约仓",
            "度量字段": "妥投时长",
            "聚合函数": "AVG",
            "物化策略": "全量重刷",
            "更新频率": "每日",
            "数据新鲜度": "",
            "所属分层": "DWD",
        },
    ]

    quality_rows: list[dict[str, Any]] = [
        {
            "id": 1,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "指标编号": "QUAL-0001",
            "监控对象": "SILV-0001",
            "指标类型": "完整性",
            "阈值范围": "完成度≥95%",
            "检测周期": "每批次",
            "告警级别": "P1",
            "通知渠道": "值班群",
            "恢复策略": "重跑清洗作业",
        },
        {
            "id": 2,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "指标编号": "QUAL-0002",
            "监控对象": "SILV-0002",
            "指标类型": "及时性",
            "阈值范围": "延迟≤10分钟",
            "检测周期": "每批次",
            "告警级别": "P2",
            "通知渠道": "值班群",
            "恢复策略": "调度补偿",
        },
        {
            "id": 3,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "指标编号": "QUAL-0003",
            "监控对象": "SILV-0003",
            "指标类型": "唯一性",
            "阈值范围": "重复率≤0.1%",
            "检测周期": "每小时",
            "告警级别": "P3",
            "通知渠道": "邮件",
            "恢复策略": "去重重跑",
        },
        {
            "id": 4,
            "status": "待校验",
            "pending": True,
            "abnormal": True,
            "指标编号": "QUAL-0004",
            "监控对象": "SILV-0004",
            "指标类型": "有效性",
            "阈值范围": "时间字段不得晚于当前时刻",
            "检测周期": "每周",
            "告警级别": "P1",
            "通知渠道": "值班群",
            "恢复策略": "人工修数",
        },
        {
            "id": 5,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "指标编号": "QUAL-0005",
            "监控对象": "SILV-0005",
            "指标类型": "完整性",
            "阈值范围": "完成度≥95%",
            "检测周期": "每批次",
            "告警级别": "P2",
            "通知渠道": "值班群",
            "恢复策略": "重跑清洗作业",
        },
    ]

    meta_rows: list[dict[str, Any]] = [
        {
            "id": 1,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "条目编号": "META-0001",
            "对象类型": "清洗表",
            "对象名称": "SILV-0001",
            "属性键": "schema_version",
            "属性值": "v3",
            "数据来源": "订单中心",
            "更新频率": "每日",
            "版本变更": "v2→v3 新增折扣字段",
        },
        {
            "id": 2,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "条目编号": "META-0002",
            "对象类型": "清洗表",
            "对象名称": "SILV-0002",
            "属性键": "schema_version",
            "属性值": "v5",
            "数据来源": "支付中心",
            "更新频率": "每日",
            "版本变更": "v4→v5 币种字段标准化",
        },
        {
            "id": 3,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "条目编号": "META-0003",
            "对象类型": "清洗表",
            "对象名称": "SILV-0003",
            "属性键": "schema_version",
            "属性值": "v2",
            "数据来源": "商品中心",
            "更新频率": "每小时",
            "版本变更": "v1→v2 类目层级调整",
        },
        {
            "id": 4,
            "status": "待审核",
            "pending": True,
            "abnormal": True,
            "条目编号": "META-0004",
            "对象类型": "清洗表",
            "对象名称": "SILV-0004",
            "属性键": "schema_version",
            "属性值": "v1",
            "数据来源": "会员中心",
            "更新频率": "每周",
            "版本变更": "v1 待审核：时间字段定义变更",
        },
        {
            "id": 5,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "条目编号": "META-0005",
            "对象类型": "清洗表",
            "对象名称": "SILV-0005",
            "属性键": "schema_version",
            "属性值": "v2",
            "数据来源": "售后中心",
            "更新频率": "每日",
            "版本变更": "v1→v2 退款渠道补录",
        },
    ]

    return {"silver": silver_rows, "gold": gold_rows, "quality": quality_rows, "meta": meta_rows}


def _placeholder_rows(module_code: str, id_prefix: str, label: str, fields: list[str], statuses: list[str]) -> list[dict[str, Any]]:
    """保留其余模块的三档状态占位数据，避免影响既有演示与运营概览口径。"""
    rows: list[dict[str, Any]] = []
    for index in range(3):
        row: dict[str, Any] = {
            "id": index + 1,
            "status": statuses[index],
            "pending": index != 2,
            "abnormal": index == 1,
        }
        for offset, field in enumerate(fields):
            row[field] = f"{label}样例{index + 1}" if offset < 7 else _sample_date(index)
        rows.append(row)
    return rows


def _sample_date(index: int) -> str:
    return (datetime(2026, 9, 1) + timedelta(days=index)).strftime("%Y-%m-%d")


SEED_ROWS: dict[str, list[dict[str, Any]]] = {
    "catalog": _placeholder_rows(
        "catalog", "CATA", "数据编目",
        ["编目编号", "数据集名称", "存储路径", "文件格式", "所属分层", "负责人", "业务域标签", "编目版本"],
        ["草稿", "待审核", "已发布"],
    ),
    "ingest": _placeholder_rows(
        "ingest", "INGE", "多源接入",
        ["通道编号", "源端类型", "连接参数", "接入模式", "批次大小", "校验规则", "异常处理", "通道负责人"],
        ["草稿", "待校验", "运行中"],
    ),
    "bronze": _placeholder_rows(
        "bronze", "BRON", "原始层管理",
        ["表编号", "来源通道", "目标路径", "保留策略", "分区规则", "文件格式", "压缩类型", "数据校验"],
        ["草稿", "待校验", "已启用"],
    ),
    "lakezone": _placeholder_rows(
        "lakezone", "LAKE", "湖区分区",
        ["方案编号", "目标表名", "分区字段", "分区粒度", "保留天数", "冷热分层", "归档路径", "小文件合并"],
        ["草稿", "待校验", "已启用"],
    ),
    "stream": _placeholder_rows(
        "stream", "STRE", "流式处理",
        ["作业编号", "输入Topic", "处理逻辑", "窗口类型", "窗口时长秒", "水位延迟", "检查点间隔", "输出Topic"],
        ["草稿", "待校验", "运行中"],
    ),
    "batch": _placeholder_rows(
        "batch", "BATC", "批量转换",
        ["任务编号", "输入路径", "处理脚本", "输出路径", "分区覆盖", "依赖上游", "重试策略", "超时终止"],
        ["草稿", "待调度", "运行中"],
    ),
    "snapshot": _placeholder_rows(
        "snapshot", "SNAP", "版本快照",
        ["快照编号", "目标表名", "快照时间", "快照大小", "存储介质", "过期策略", "恢复校验", "依赖快照"],
        ["草稿", "待创建", "已生效"],
    ),
    "govern": _placeholder_rows(
        "govern", "GOVE", "湖仓治理",
        ["规则编号", "治理对象", "治理类型", "触发阈值", "执行动作", "执行频率", "影响范围", "回滚策略"],
        ["草稿", "待校验", "已启用"],
    ),
    "lineage": _placeholder_rows(
        "lineage", "LINE", "血缘图谱",
        ["节点编号", "节点类型", "节点名称", "上游节点列表", "下游节点列表", "转换说明", "采集时间", "图谱版本"],
        ["草稿", "待校验", "已启用"],
    ),
    "schedule": _placeholder_rows(
        "schedule", "SCHE", "编排调度",
        ["计划编号", "任务列表", "依赖图定义", "调度表达式", "并发上限", "失败处理", "超时秒数", "通知策略"],
        ["草稿", "待校验", "运行中"],
    ),
    "backfill": _placeholder_rows(
        "backfill", "BACK", "历史回填",
        ["作业编号", "目标表名", "回填起始", "回填截止", "分区范围", "并行度", "失败续跑", "完成校验"],
        ["草稿", "待执行", "运行中"],
    ),
    "search": _placeholder_rows(
        "search", "SEAR", "数据检索",
        ["索引编号", "索引名称", "覆盖表名", "索引字段", "分词策略", "排序权重", "刷新频率", "索引大小"],
        ["草稿", "待构建", "已生效"],
    ),
    "resource": _placeholder_rows(
        "resource", "RESO", "资源计量",
        ["记录编号", "计算引擎", "作业名称", "CPU核秒", "内存GB秒", "存储占用GB", "扫描数据量", "计费周期"],
        ["草稿", "待汇总", "已结算"],
    ),
    "audit": _placeholder_rows(
        "audit", "AUDI", "操作审计",
        ["日志编号", "操作类型", "操作对象", "操作详情", "操作来源", "执行时间", "影响行数", "回滚能力"],
        ["草稿", "待审核", "已归档"],
    ),
}

SEED_ROWS.update(_build_lakehouse_seed(datetime.now()))

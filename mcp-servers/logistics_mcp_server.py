import json
import os
from datetime import datetime

# 必须全部放在 import fastmcp 之前设置
os.environ["FASTMCP_HTTP_HOST_ORIGIN_PROTECTION"] = "false"
os.environ["FASTMCP_HTTP_ALLOWED_HOSTS"] = '["host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0"]'
os.environ["FASTMCP_HTTP_ALLOWED_ORIGINS"] = '["*"]'

from fastmcp import FastMCP

mcp = FastMCP("电商物流查询服务")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGISTICS_FILE = os.path.join(BASE_DIR, "logistics_data.json")
CALL_LOG = os.path.join(os.environ.get("TEMP", BASE_DIR), "mcp_calls.log")


def log_call(tool: str, detail: str) -> None:
    """把工具入参写到临时文件，便于排查 Dify 侧传参问题。"""
    try:
        with open(CALL_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now().isoformat(timespec='seconds')}] {tool} {detail}\n")
    except Exception:
        pass


def load_data(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _format_logistics_text(order_no: str, info: dict) -> str:
    """把物流数据格式化为可读文本，供Dify LLM直接读取"""
    lines = [
        f"订单号：{order_no}",
        f"商品：{info['product']}",
        f"收货人：{info['receiver']}",
        f"快递公司：{info['carrier']}",
        f"运单号：{info['tracking_number']}",
        f"当前状态：{info['current_status']}",
        f"当前位置：{info['current_location']}",
        f"预计送达：{info['expected_delivery']}",
        "物流轨迹（最近3条）：",
    ]
    for track in info["track_history"][-3:]:
        lines.append(f"  - [{track['time']}] {track['location']}：{track['status']}")
    return "\n".join(lines)


@mcp.tool()
def query_logistics(order_number: str = "", order_id: str = "") -> str:
    """根据订单号或运单号查询物流状态、位置和配送进度

    order_number: 订单号或运单号（推荐）
    order_id: 兼容旧参数名，含义同 order_number
    """
    order_number = (order_number or order_id or "").strip()
    log_call("query_logistics", f"order_number={order_number!r}")
    if not order_number:
        return "未提供订单号或运单号，无法查询物流信息"
    logistics_data = load_data(LOGISTICS_FILE)

    # 先按订单号匹配
    for order_no, info in logistics_data.items():
        if order_number.upper() in order_no.upper() or order_no.upper() in order_number.upper():
            return _format_logistics_text(order_no, info)

    # 如果订单号没匹配到，再按运单号匹配
    for order_no, info in logistics_data.items():
        tracking_no = info.get("tracking_number", "")
        if tracking_no and (order_number.upper() in tracking_no.upper() or tracking_no.upper() in order_number.upper()):
            return _format_logistics_text(order_no, info)

    return "未查询到该订单号或运单号的物流信息，请确认信息是否正确"


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8001,
        host_origin_protection=False,
    )

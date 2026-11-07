import json
import os

# 必须全部放在 import fastmcp 之前设置
# 1. 强制关闭 Host + Origin 安全校验
os.environ["FASTMCP_HTTP_HOST_ORIGIN_PROTECTION"] = "false"
# 2. 显式放行所有可能的 Host 主机名
os.environ["FASTMCP_HTTP_ALLOWED_HOSTS"] = '["host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0"]'
# 3. 放行所有来源 Origin，彻底避免跨域拦截
os.environ["FASTMCP_HTTP_ALLOWED_ORIGINS"] = '["*"]'

from fastmcp import FastMCP

mcp = FastMCP("电商库存查询服务")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STOCK_FILE = os.path.join(BASE_DIR, "stock_data.json")


def load_data(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@mcp.tool()
def query_stock(product_name: str = "", product: str = "", product_id: str = "") -> str:
    """根据商品名称查询库存、价格、发货信息

    product_name: 商品名称（推荐，可写型号或关键词，如 RTX5080、笔记本）
    product / product_id: 兼容旧参数名，含义同 product_name
    """
    product_name = (product_name or product or product_id or "").strip()
    if not product_name:
        return json.dumps({"error": "未提供商品名称，无法查询库存"}, ensure_ascii=False)
    stock_data = load_data(STOCK_FILE)

    for name, info in stock_data.items():
        if product_name.lower() in name.lower() or name.lower() in product_name.lower():
            result = {
                "商品": name,
                "商品SKU": info["sku"],
                "当前库存": f"{info['stock']}件",
                "发货仓库": info["warehouse"],
                "发货时效": info["ship_time"],
                "售价": f"{info['price']}元"
            }
            return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": "未查询到对应商品"}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
        host_origin_protection=False,  # 显式关闭 Host/Origin 安全校验，允许 Docker 容器通过 host.docker.internal 访问
    )

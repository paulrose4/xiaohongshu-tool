"""Node 1: 选品智能体 (Product Selector).

Input:  state["instruction"] + state["constraints"]
Logic:  Query taobao-alliance / pinduoduo DDK APIs (or a mock) and hard-filter:
          - 客单价 19.9-69.9 元
          - 佣金率 > 20%
          - 30天销量 > 5000
Output: state["products"] (candidates) + state["selected"] (top-1 爆款)
        with title / highlights / price / white_bg_image_url.
"""
from __future__ import annotations

import logging
import random
from typing import Any

import httpx

from ..config import settings
from ..retry import with_retry
from ..state import AgentState, ProductInfo, append_log, set_error

_log = logging.getLogger("xhs.selector")

# Hard-coded filter thresholds (mirrored from config but explicit per spec).
PRICE_MIN = 19.9
PRICE_MAX = 69.9
COMMISSION_MIN = 0.20
SALES_30D_MIN = 5000


def _passes(p: dict[str, Any]) -> bool:
    try:
        return (
            PRICE_MIN <= float(p["price"]) <= PRICE_MAX
            and float(p["commission_rate"]) > COMMISSION_MIN
            and int(p["sales_30d"]) > SALES_30D_MIN
        )
    except (KeyError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Mock data source (used when USE_MOCK_API=true). Realistic-shaped items so the
# downstream nodes can run end-to-end without external credentials.
# ---------------------------------------------------------------------------
_MOCK_POOL: list[dict[str, Any]] = [
    {
        "product_id": "mock-001",
        "title": "免打孔壁挂收纳盒 卫生间/厨房通用大容量",
        "highlights": ["免打孔安装", "大容量分层", "承重强不脱落"],
        "price": 29.9,
        "commission_rate": 0.25,
        "sales_30d": 18000,
        "white_bg_image_url": "https://picsum.photos/seed/xhs-storage-box/800/800",
        "shop": "好好生活旗舰店",
        "source": "mock",
    },
    {
        "product_id": "mock-002",
        "title": "ins风奶油风桌面小台灯 USB触控调光",
        "highlights": ["三档调光", "USB充电", "暖光护眼"],
        "price": 39.9,
        "commission_rate": 0.22,
        "sales_30d": 9600,
        "white_bg_image_url": "https://picsum.photos/seed/xhs-desk-lamp/800/800",
        "shop": "温柔光线专卖店",
        "source": "mock",
    },
    {
        "product_id": "mock-003",
        "title": "便宜但不推荐 超低价塑料衣架十只装",
        "highlights": ["价格低"],
        "price": 9.9,                # below price floor -> should be filtered
        "commission_rate": 0.10,
        "sales_30d": 2000,
        "white_bg_image_url": "https://picsum.photos/seed/xhs-hanger/800/800",
        "shop": "杂货铺",
        "source": "mock",
    },
    {
        "product_id": "mock-004",
        "title": "小户型折叠脏衣篓 大容量可折叠不占地",
        "highlights": ["折叠收纳", "不占空间", "防水材质"],
        "price": 49.9,
        "commission_rate": 0.28,
        "sales_30d": 12000,
        "white_bg_image_url": "https://picsum.photos/seed/xhs-laundry-basket/800/800",
        "shop": "独居好物研究所",
        "source": "mock",
    },
    {
        "product_id": "mock-005",
        "title": "桌面加湿器 静音卧室宿舍小容量",
        "highlights": ["静音运行", "小巧便携", "七彩夜灯"],
        "price": 59.9,
        "commission_rate": 0.21,
        "sales_30d": 7300,
        "white_bg_image_url": "https://picsum.photos/seed/xhs-humidifier/800/800",
        "shop": "湿润小铺",
        "source": "mock",
    },
]


def _mock_search(instruction: str, constraints: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mock pool, lightly shuffled so each run feels alive."""
    pool = [dict(p) for p in _MOCK_POOL]
    random.shuffle(pool)
    return pool


# ---------------------------------------------------------------------------
# Real API scaffolding: 淘宝联盟 / 多多进宝.
# These are skeletons with the correct request shape; fill in signing + auth
# with your real credentials. They return the same dict shape as the mock.
# ---------------------------------------------------------------------------
@with_retry(name="taobao_search")
async def _taobao_alliance_search(instruction: str, constraints: dict[str, Any]) -> list[dict[str, Any]]:
    """淘宝联盟 淘宝客物料搜索 (tbk.dg.material.optional).

    NOTE: 淘宝联盟请求需签名 (sign = md5(secret+sorted_params)). 这里给出
    请求骨架, 实际使用请用官方 SDK 或补全签名逻辑。
    """
    app_key = settings  # placeholder to keep config reference
    url = "https://eco.taobao.com/router/rest"
    params = {
        "method": "taobao.tbk.dg.material.optional",
        "app_key": "",            # TODO: settings.taobao_app_key
        "sign_method": "md5",
        "timestamp": "",          # TODO: now
        "format": "json",
        "v": "2.0",
        "q": instruction,
        "adzone_id": constraints.get("adzone_id", ""),
        "has_coupon": "true",
        "page_size": "50",
    }
    # sign = hashlib.md5((APP_SECRET + ''.join(f'{k}{v}' for k,v in sorted(params))).encode()).hexdigest().upper()
    # params["sign"] = sign
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    # Map tbk fields -> our ProductInfo shape.
    results = []
    for it in data.get("tbk_dg_material_optional_response", {}).get("result_list", {}).get("map_data", []):
        results.append(
            {
                "product_id": str(it.get("item_id", "")),
                "title": it.get("title", ""),
                "highlights": [it.get("short_title", "")] if it.get("short_title") else [],
                "price": float(it.get("zk_final_price", 0)),
                "commission_rate": float(it.get("commission_rate", 0)) / 100.0,
                "sales_30d": int(it.get("volume", 0)),
                "white_bg_image_url": it.get("pict_url", "").replace("http://", "https://"),
                "shop": it.get("nick", ""),
                "source": "taobao",
            }
        )
    return results


@with_retry(name="pinduoduo_search")
async def _pinduoduo_search(instruction: str, constraints: dict[str, Any]) -> list[dict[str, Any]]:
    """多多进宝 商品搜索 (pdd.ddk.goods.search)。

    NOTE: 多多进宝需 client_id/client_secret 签名。这里给出请求骨架。
    """
    url = "https://gw-api.pinduoduo.com/api/router"
    params = {
        "type": "pdd.ddk.goods.search",
        "client_id": "",
        "keyword": instruction,
        "page_size": 50,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    results = []
    for it in data.get("goods_search_response", {}).get("goods_list", []):
        results.append(
            {
                "product_id": str(it.get("goods_sign", "")),
                "title": it.get("goods_name", ""),
                "highlights": [it.get("goods_desc", "")] if it.get("goods_desc") else [],
                "price": float(it.get("min_group_price", 0)) / 100.0,
                "commission_rate": float(it.get("commission_rate", 0)) / 100.0,
                "sales_30d": int(it.get("sales_tip", 0)),
                "white_bg_image_url": it.get("goods_image_url", ""),
                "shop": it.get("mall_name", ""),
                "source": "pinduoduo",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Node entry
# ---------------------------------------------------------------------------
def _rank_key(p: dict[str, Any]) -> tuple[float, int]:
    """Rank by commission (desc) then 30d sales (desc) -> pick the爆."""
    return (float(p["commission_rate"]), int(p["sales_30d"]))


def select_node(state: AgentState) -> AgentState:
    """选品节点: 拉取候选 -> 硬过滤 -> 排序选爆款 -> 写入 state."""
    instruction = state.get("instruction", "")
    constraints = state.get("constraints", {}) or {}
    append_log(state, "selector", f"querying candidates for: {instruction!r}")

    try:
        if settings.use_mock_api:
            raw = _mock_search(instruction, constraints)
            append_log(state, "selector", f"mock source returned {len(raw)} items")
        else:
            # Real path: fan out to both platforms (skeletons). Run sync wrapper.
            import asyncio

            async def _gather():
                tb, dd = await asyncio.gather(
                    _taobao_alliance_search(instruction, constraints),
                    _pinduoduo_search(instruction, constraints),
                    return_exceptions=True,
                )
                out: list[dict[str, Any]] = []
                for batch in (tb, dd):
                    if isinstance(batch, list):
                        out.extend(batch)
                    else:
                        append_log(state, "selector", f"source error: {batch!r}")
                return out

            raw = asyncio.run(_gather())
    except Exception as e:  # noqa: BLE001
        set_error(state, "selector", f"search failed: {e}")
        return state

    # Hard filter.
    passed = [p for p in raw if _passes(p)]
    append_log(
        state,
        "selector",
        f"filter {PRICE_MIN}-{PRICE_MAX}元 / 佣金>{COMMISSION_MIN*100:.0f}% / 销量>{SALES_30D_MIN}: {len(passed)}/{len(raw)} passed",
    )

    if not passed:
        set_error(state, "selector", "no products passed the hard filter")
        return state

    # Rank and pick top-1.
    passed.sort(key=_rank_key, reverse=True)
    top_k = settings.selection.top_k
    products: list[ProductInfo] = [p for p in passed[:top_k]]  # type: ignore
    chosen = passed[0]

    state["products"] = products
    state["selected"] = chosen  # type: ignore
    state["image_url"] = chosen.get("white_bg_image_url", "")
    state["status"] = "visual"
    state["current_node"] = "selector"
    append_log(
        state,
        "selector",
        f"selected爆款: {chosen['title']} | ¥{chosen['price']} | 佣金{chosen['commission_rate']*100:.0f}% | 销量{chosen['sales_30d']}",
    )
    return state


__all__ = ["select_node"]

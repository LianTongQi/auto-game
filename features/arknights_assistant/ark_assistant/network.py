"""Bounded anonymous GET-only public copilot search. No account data is sent."""
import json
import re
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import normalize_job, resolve_stage

BASE_URL = "https://prts.maa.plus"
MAX_RESPONSE = 4 * 1024 * 1024


def allowed_path(path):
    return path == "/copilot/query" or re.fullmatch(r"/copilot/get/[1-9][0-9]*", path) is not None


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if (parsed.scheme != "https" or parsed.hostname != "prts.maa.plus"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or not allowed_path(parsed.path)):
            raise ValueError("作业站跳转到非白名单地址，已停止")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_public_json(path, query=None):
    if not allowed_path(path):
        raise ValueError("不允许访问此接口")
    url = BASE_URL + path + ("?" + urlencode(query) if query else "")
    request = Request(url, headers={"User-Agent": "ArknightsAssistant/0.1 (read-only)", "Accept": "application/json"}, method="GET")
    with build_opener(SafeRedirect()).open(request, timeout=15) as response:
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise ValueError("公开作业响应过大，已停止")
    payload = json.loads(body.decode("utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("status_code") != 200:
        raise ValueError("作业站返回错误或接口格式已变化；不自动重试")
    return payload.get("data")


def search_jobs(stage, limit=10, stage_map=None):
    if not isinstance(stage, str) or not stage.strip() or len(stage) > 64:
        raise ValueError("请填写关卡编号")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("每次只允许查询 1～20 条作业")
    stage_map = stage_map or {}
    target = resolve_stage(stage, stage_map)
    # Both spellings cover the public server's binding changes. Caller must
    # STILL perform exact local stage filtering, never trust a keyword result.
    data = get_public_json("/copilot/query", {"level_keyword": target, "levelKeyword": target,
                          "type": "PRTS", "page": 1, "limit": limit, "order_by": "hot", "desc": "true"})
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("作业列表协议变化，已停止")
    jobs, rejected = [], []
    detail_reads, wrong_stage, deferred = 0, 0, 0
    for row in data["data"][:limit]:
        try:
            if not isinstance(row, dict):
                raise ValueError("无效作业摘要")
            summary = row.get("content")
            summary = json.loads(summary) if isinstance(summary, str) else summary
            if not isinstance(summary, dict):
                raise ValueError("无效作业摘要内容")
            raw_stage = summary.get("stage_name", "")
            if not isinstance(raw_stage, str) or not raw_stage.strip():
                raise ValueError("摘要缺少关卡标识")
            actual_stage = resolve_stage(raw_stage, stage_map)
            if actual_stage.upper() != target.upper():
                wrong_stage += 1
                continue
            # List content intentionally omits actions on the live server.
            # Fetch details only for exact-stage summaries, at most three.
            if not summary.get("actions"):
                if detail_reads >= 3:
                    deferred += 1
                    continue
                identifier = row.get("id")
                if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
                    raise ValueError("无效作业 ID")
                detail_reads += 1
                row = get_public_json(f"/copilot/get/{identifier}")
                if not isinstance(row, dict):
                    raise ValueError("详情协议无效")
                content = row.get("content")
                content = json.loads(content) if isinstance(content, str) else content
                if not isinstance(content, dict) or resolve_stage(content.get("stage_name"), stage_map).upper() != actual_stage.upper():
                    raise ValueError("作业详情关卡与摘要不一致")
            jobs.append(normalize_job(row, "PRTS Plus 公开作业"))
        except (ValueError, TypeError, KeyError):
            rejected.append(str(row.get("id", "未知")) if isinstance(row, dict) else "未知")
    return jobs, {"requested_stage": stage, "received": len(data["data"]),
                  "accepted": len(jobs), "rejected_ids": rejected,
                  "wrong_stage": wrong_stage, "detail_reads": detail_reads, "deferred": deferred,
                  "note": "只查询一页、最多读取三份完整详情；未找到匹配不代表没有其他作业；关卡不符和不完整作业已排除"}

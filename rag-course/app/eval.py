"""阶段 5 + 升级①：检索评估 —— 内容命中率 Hit@3。

测试集：15 个问题，期望值是"正文关键词"（验证检索是否找到内容）。
注意：引用标签是否准确是另一件事，需要到答案级评估里看。

用法（在 rag-course 目录下）：
    python app/eval.py
"""
from __future__ import annotations

import sys

from retrieve import retrieve

TEST_CASES = [
    {"question": "发薪日是什么时候", "expect": "工资"},
    {"question": "请假超过三天找谁审批", "expect": "请假"},
    {"question": "发票抬头怎么填", "expect": "发票"},
    {"question": "一线城市住宿标准是多少", "expect": "住宿标准"},
    {"question": "病假超过几天需要医院证明", "expect": "病假"},
    {"question": "出差加班餐费能报销吗", "expect": "加班餐费"},
    {"question": "高铁升舱需要提前申请吗", "expect": "升舱"},
    {"question": "公司有哪些福利", "expect": "五险一金"},
    {"question": "出差申请要提前多久提交", "expect": "出差申请"},
    {"question": "工资什么时候发", "expect": "工资"},
    {"question": "年假算不算请假", "expect": "年假"},
    {"question": "报销款什么时候到账", "expect": "报销款"},
    {"question": "五险一金包括哪些", "expect": "五险一金"},
    {"question": "报销发票金额超过多少需要刷卡记录", "expect": "刷卡"},
    {"question": "一线城市包括哪些", "expect": "上海"},
]


def main() -> None:
    passed = 0
    for case in TEST_CASES:
        hits = retrieve(case["question"], final_n=3)
        matched = any(case["expect"] in h["text"] for h in hits)
        passed += matched
        mark = "通过" if matched else "失败"
        print(f"[{mark}] {case['question']}（期望命中：{case['expect']}）")
        for rank, hit in enumerate(hits, 1):
            print(f"    #{rank} {hit['section']}")
        if not matched:
            print(f"    ⚠ 期望的『{case['expect']}』没有出现在前 3 名的正文里")
    print(f"\n内容命中率（Hit@3）：{passed}/{len(TEST_CASES)} = {passed / len(TEST_CASES):.0%}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
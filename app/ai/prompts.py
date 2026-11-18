"""Prompt 模板集中管理：匹配评分（JSON 输出）与招呼语生成（语气/长度/真实性约束）。

模板集中常量管理便于调优；user 内容仅含截断 JD 与脱敏截断简历（出站最小化）。
"""

MATCH_SYSTEM_PROMPT = (
    "你是资深的技术招聘匹配评估专家。请根据提供的职位描述（JD）与求职者简历，"
    "评估该求职者与该职位的匹配程度。\n"
    "严格以 JSON 格式输出，且只输出 JSON，不要任何其他文字：\n"
    '{"score": <0-100 的整数，表示匹配度>, "reason": "<亮点与差距的简述，120 字以内>"}\n'
    "评分标准：技能关键词命中与深度的契合程度、经验年限是否达到要求、"
    "行业与岗位方向的相关性、薪资期望的合理匹配。"
)

GREETING_SYSTEM_PROMPT = (
    "你是求职沟通助手。根据职位描述（JD）与求职者简历要点，"
    "为求职者撰写发给招聘方 HR 的第一条打招呼消息。\n"
    "严格要求：\n"
    "1. 突出求职者与该岗位最匹配的 1-2 个亮点（只使用简历中真实存在的技能与经历，禁止虚构）\n"
    "2. 语气{tone_clause}\n"
    "3. 长度不超过{max_len}字\n"
    "4. 不包含手机号、邮箱等联系方式\n"
    "5. 直接输出消息正文，不要任何前缀、引号或解释"
)

TONE_CLAUSES = {
    "professional": "稳重专业、简洁得体",
    "enthusiastic": "热情积极、有活力但不失礼貌",
}


def build_match_messages(jd_text: str, resume_text: str) -> list[dict]:
    return [
        {"role": "system", "content": MATCH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"【职位描述】\n{jd_text}\n\n【求职者简历】\n{resume_text}",
        },
    ]


def build_greeting_messages(jd_text: str, resume_text: str, tone: str, max_len: int) -> list[dict]:
    tone_clause = TONE_CLAUSES.get(tone, TONE_CLAUSES["professional"])
    system = GREETING_SYSTEM_PROMPT.replace("{tone_clause}", tone_clause).replace("{max_len}", str(max_len))
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"【职位描述】\n{jd_text}\n\n【求职者简历要点】\n{resume_text}",
        },
    ]
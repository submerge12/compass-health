"""
One-off script: fetch per-100g micronutrient values for every food in the
library from DeepSeek using Chinese Food Composition Database (CDR) data.

Run from backend/:
    python scripts/fetch_cdr_nutrients.py > scripts/cdr_output.json

Output shape:
  {
    "slug": {
      "calcium_mg": float,
      "iron_mg": float,
      "zinc_mg": float,
      "iodine_mcg": float,
      "selenium_mcg": float,
      "vitamin_a_mcg": float,   # mcg RAE
      "vitamin_d_mcg": float,   # mcg (1 mcg = 40 IU)
      "vitamin_e_mg": float,    # mg alpha-TE
      "vitamin_k_mcg": float,   # mcg
      "b12_mcg": float,
      "folate_mcg": float,      # mcg DFE
      "omega3_g": float,        # total ALA+EPA+DHA per 100g
      "fiber_g": float
    },
    ...
  }
"""
from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

FOODS: dict[str, str] = {
    # slug: Chinese name used in CDR lookup
    "rice":                    "大米饭（蒸）",
    "brown_rice":              "糙米饭",
    "oats":                    "燕麦片（干）",
    "buckwheat":               "荞麦（熟）",
    "quinoa":                  "藜麦（熟）",
    "sweet_potato":            "红薯（蒸熟）",
    "potato":                  "马铃薯（蒸熟）",
    "corn":                    "鲜玉米",
    "steamed_bun":             "馒头（小麦粉）",
    "pumpkin":                 "南瓜（生）",
    "chicken_breast":          "鸡胸肉（生）",
    "chicken_thigh_skinless":  "去皮鸡腿肉（生）",
    "duck_breast":             "鸭胸肉（生）",
    "pork_tenderloin":         "猪里脊（生）",
    "cod":                     "鳕鱼（生）",
    "sea_bass":                "鲈鱼（生）",
    "tilapia":                 "罗非鱼（生）",
    "shrimp":                  "虾仁（鲜）",
    "egg_white":               "鸡蛋清（生）",
    "beef_tenderloin":         "牛里脊（生）",
    "beef_sirloin":            "牛西冷（生）",
    "lamb":                    "羊肉（瘦，生）",
    "beef_liver":              "牛肝（生）",
    "chicken_liver":           "鸡肝（生）",
    "duck_blood":              "鸭血（生）",
    "oyster":                  "牡蛎（生蚝，鲜）",
    "clam":                    "蛤蜊（生）",
    "mussel":                  "贻贝（淡菜，生）",
    "scallop":                 "扇贝（生）",
    "salmon":                  "大西洋三文鱼（生）",
    "hairtail":                "带鱼（生）",
    "mackerel":                "鲐鱼（生）",
    "sardine":                 "沙丁鱼（鲜）",
    "whole_egg":               "鸡蛋（整蛋，生）",
    "egg_yolk":                "鸡蛋黄（生）",
    "milk":                    "全脂牛乳",
    "yogurt":                  "酸奶（全脂，原味）",
    "greek_yogurt":            "希腊酸奶（浓缩）",
    "cheese":                  "奶酪（再制）",
    "tofu_firm":               "北豆腐（老豆腐）",
    "tofu_soft":               "南豆腐（嫩豆腐）",
    "dried_tofu":              "豆腐干",
    "soy_milk":                "豆浆（原味）",
    "natto":                   "纳豆",
    "tempeh":                  "天贝（发酵大豆饼）",
    "edamame":                 "毛豆（鲜）",
    "spinach":                 "菠菜（生）",
    "bok_choy":                "上海青（小白菜，生）",
    "kale":                    "羽衣甘蓝（生）",
    "amaranth":                "苋菜（生）",
    "mustard_greens":          "芥蓝（生）",
    "broccoli":                "西兰花（生）",
    "cauliflower":             "花椰菜（生）",
    "cabbage":                 "结球甘蓝（生）",
    "shiitake":                "香菇（鲜）",
    "shiitake_sun":            "干香菇（日晒）",
    "enoki":                   "金针菇（鲜）",
    "wood_ear":                "木耳（干，泡发后）",
    "kelp":                    "海带（鲜）",
    "seaweed":                 "紫菜（干）",
    "tomato":                  "番茄（鲜）",
    "cucumber":                "黄瓜（鲜）",
    "carrot":                  "胡萝卜（鲜）",
    "blueberry":               "蓝莓（鲜）",
    "strawberry":              "草莓（鲜）",
    "pineapple":               "菠萝（鲜）",
    "mulberry":                "桑椹（鲜）",
    "apple":                   "苹果（鲜）",
    "raspberry":               "覆盆子（鲜）",
    "banana":                  "香蕉（鲜）",
    "orange":                  "橙子（鲜）",
    "kiwi":                    "猕猴桃（鲜）",
    "walnuts":                 "核桃（干）",
    "almonds":                 "杏仁（甜，干）",
    "cashews":                 "腰果（干，烤）",
    "pumpkin_seeds":           "南瓜子（干）",
    "sunflower_seeds":         "葵花籽（干）",
    "brazil_nuts":             "巴西坚果（干）",
    "flaxseed":                "亚麻籽（干）",
    "chia_seed":               "奇亚籽（干）",
    "sesame":                  "芝麻（干）",
    "pine_nuts":               "松子（干）",
    "pistachios":              "开心果（干，烤）",
    "hazelnuts":               "榛子（干）",
    "peanuts":                 "花生（干）",
    "macadamia":               "澳洲坚果（干，烤）",
    "olive_oil":               "橄榄油",
    "iodized_salt":            "加碘食盐",
}

PROMPT_HEADER = """\
你是中国营养学领域的专家，熟悉《中国食物成分表》（标准版第6版，2018）。

请以JSON格式返回下列食物每100克可食部分的微量营养素含量，数据来源请以CDR/中国食物成分表为主。
若某食物在CDR中无精确数据，请使用国际通用食物成分数据库（USDA FDC / FAO INFOODS）的近似值，并确保符合中国常见加工或烹饪方式。

需要的字段（单位已在括号中注明）：
- calcium_mg    （钙，mg）
- iron_mg       （铁，mg）
- zinc_mg       （锌，mg）
- iodine_mcg    （碘，μg）—— 仅对高碘食物（海带、紫菜、加碘盐）给出实际值，其余可填0
- selenium_mcg  （硒，μg）
- vitamin_a_mcg （维生素A，μg RAE）
- vitamin_d_mcg （维生素D，μg；1μg=40IU）
- vitamin_e_mg  （维生素E，mg α-TE）
- vitamin_k_mcg （维生素K，μg）
- b12_mcg       （维生素B12，μg）
- folate_mcg    （叶酸，μg DFE）
- omega3_g      （Omega-3总量，g；植物源填ALA，鱼类填EPA+DHA总和）
- fiber_g       （膳食纤维，g）

只输出JSON，格式如下（不要输出任何解释文字）：
{
  "slug1": {"calcium_mg": 1.0, "iron_mg": 0.5, ...},
  "slug2": {...},
  ...
}

食物列表（slug: 中文名称）：
"""


def _fetch_batch(client: OpenAI, batch: dict[str, str]) -> dict:
    """Fetch one batch of foods; return the parsed dict."""
    prompt = PROMPT_HEADER + "\n".join(f"  {slug}: {name}" for slug, name in batch.items())
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = resp.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  JSONDecodeError at {exc.pos}, attempting partial parse", file=sys.stderr)
        truncated = raw[: exc.pos]
        last_close = truncated.rfind("},")
        if last_close == -1:
            last_close = truncated.rfind("}")
        repaired = truncated[: last_close + 1] + "\n}"
        return json.loads(repaired)


def main() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(trust_env=False),
    )

    # Split into 3 batches of ~28 foods to avoid output truncation
    items = list(FOODS.items())
    batch_size = 28
    batches = [dict(items[i: i + batch_size]) for i in range(0, len(items), batch_size)]
    all_data: dict = {}

    for idx, batch in enumerate(batches, 1):
        print(f"Calling DeepSeek batch {idx}/{len(batches)} ({len(batch)} foods)...", file=sys.stderr)
        result = _fetch_batch(client, batch)
        all_data.update(result)
        print(f"  Got {len(result)} entries (total so far: {len(all_data)})", file=sys.stderr)

    # Redirect rest of old main body below — keep the PROMPT variable intact but don't use it in the old way
    # Validate completeness
    missing = [s for s in FOODS if s not in all_data]
    if missing:
        print(f"WARNING: missing slugs ({len(missing)}): {missing}", file=sys.stderr)

    print(json.dumps(all_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

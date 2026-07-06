import csv
from collections import Counter

# Load data
ingredients = {}
with open('seed_my_ingredients.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        ingredients[row['slug']] = row

seasonings = {}
with open('seed_my_seasonings.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        seasonings[row['slug']] = row

def calc(slug, grams, is_s=False):
    src = seasonings if is_s else ingredients
    item = src[slug]
    s = grams / 100.0
    return {k: float(item.get(k, '0') or '0') * s
            for k in ['energy_kcal', 'protein_g', 'fat_g', 'carbohydrate_g', 'sodium_mg']}

def total(parts):
    t = {'energy_kcal': 0, 'protein_g': 0, 'fat_g': 0, 'carbohydrate_g': 0, 'sodium_mg': 0}
    for slug, g, is_s in parts:
        n = calc(slug, g, is_s)
        for k in t:
            t[k] += n[k]
    return t

# === DISHES ===
D = {
    'salad':       ('凉拌鸡丝虾仁沙拉', [('chicken_breast',100,0),('shrimp_jiweixia',100,0),('cucumber',80,0),('carrot',40,0),('light_soy_sauce',10,1),('sesame_oil',3,1)]),
    'braised_ht':  ('红烧带鱼',        [('hairtail',200,0),('light_soy_sauce',10,1),('cooking_wine',10,1),('olive_oil',10,1)]),
    'steamed_br':  ('清蒸鲷鱼片',      [('sea_bream',200,0),('light_soy_sauce',8,1),('sesame_oil',3,1)]),
    'soy_chicken': ('酱鸡腿卤蛋香菇',   [('chicken_thigh',200,0),('egg',50,0),('shiitake_fresh',30,0),('light_soy_sauce',8,1),('dark_soy_sauce',4,1),('cooking_wine',10,1)]),
    'napa_shrimp': ('蒜蓉粉丝娃娃菜虾', [('glass_noodles',40,0),('baby_napa',200,0),('shrimp_jiweixia',100,0),('light_soy_sauce',8,1),('olive_oil',5,1)]),
    'kelp_soup':   ('紫菜海带豆腐汤',   [('nori_dried',3,0),('kelp_fresh',50,0),('tofu',150,0),('salt',1.5,1),('sesame_oil',3,1)]),
    'scallion_bf': ('葱爆牛肉',        [('beef_tenderloin',200,0),('light_soy_sauce',10,1),('cooking_wine',10,1),('olive_oil',10,1)]),
    'garlic_broc': ('蒜蓉西兰花',      [('broccoli',200,0),('olive_oil',13,1),('light_soy_sauce',5,1)]),
    'cold_spin':   ('凉拌菠菜',        [('spinach',200,0),('sesame_oil',5,1),('aged_vinegar',10,1)]),
    'shroom_bok':  ('香菇炒小白菜',     [('shiitake_fresh',60,0),('bok_choy',200,0),('olive_oil',10,1)]),
    'broc_shrimp': ('西兰花炒虾仁',     [('broccoli',150,0),('shrimp_jiweixia',100,0),('olive_oil',10,1),('light_soy_sauce',5,1)]),
    'spin_tofu':   ('菠菜豆腐汤',      [('spinach',150,0),('tofu',150,0),('salt',1.5,1),('sesame_oil',3,1)]),
    'onion_beef':  ('洋葱炒牛肉',      [('beef_tenderloin',200,0),('light_soy_sauce',10,1),('cooking_wine',10,1),('olive_oil',10,1)]),
    'pan_bream':   ('香煎鲷鱼配柠檬',   [('sea_bream',200,0),('olive_oil',10,1),('salt',0.5,1)]),
    'chk_carrot':  ('胡萝卜炒鸡丁',     [('chicken_breast',150,0),('carrot',100,0),('olive_oil',10,1),('light_soy_sauce',8,1)]),
}

# === STAPLES ===
S = {
    'rice':     ('糙米饭1碗',     [('brown_rice', 60, 0)]),
    'bun':      ('馒头1个',       [('steamed_bun', 100, 0)]),
    'ciabatta': ('藜麦恰巴塔1个', [('quinoa_ciabatta', 90, 0)]),
    'potato':   ('红薯1个',       [('sweet_potato', 200, 0)]),
    'corn':     ('玉米1根',       [('corn_fresh', 115, 0)]),
}

# === BREAKFAST COMBOS ===
B = {
    'b1': ('藜麦恰巴塔 + 2鸡蛋 + 牛奶',
           [('quinoa_ciabatta',90,0), ('egg',100,0), ('whole_milk',250,0)]),
    'b2': ('红薯 + 2鸡蛋 + 酸奶 + 杏仁',
           [('sweet_potato',200,0), ('egg',100,0), ('yogurt_high_protein',100,0), ('almond',15,0)]),
    'b3': ('馒头 + 2鸡蛋 + 牛奶',
           [('steamed_bun',100,0), ('egg',100,0), ('whole_milk',250,0)]),
    'b4': ('玉米 + 2鸡蛋 + 牛奶 + 草莓',
           [('corn_fresh',115,0), ('egg',100,0), ('whole_milk',250,0), ('strawberry',60,0)]),
    'b5': ('藜麦恰巴塔 + 2鸡蛋 + 酸奶 + 核桃',
           [('quinoa_ciabatta',90,0), ('egg',100,0), ('yogurt_high_protein',100,0), ('walnut_dried',10,0)]),
}

# === 7-DAY PLAN ===
week = [
    # (breakfast, (main, staple, side/soup) lunch, (main, staple, side/soup) dinner)
    ('b1', ('scallion_bf', 'rice', 'garlic_broc'), ('steamed_br',  'rice',   'spin_tofu')),
    ('b2', ('soy_chicken', 'rice', 'cold_spin'),   ('broc_shrimp', 'corn',   'kelp_soup')),
    ('b3', ('braised_ht',  'rice', 'shroom_bok'),  ('chk_carrot',  'potato', 'cold_spin')),
    ('b4', ('onion_beef',  'rice', 'garlic_broc'), ('napa_shrimp', None,     'spin_tofu')),
    ('b5', ('salad',       'ciabatta', 'kelp_soup'), ('pan_bream', 'rice',   'shroom_bok')),
    ('b1', ('chk_carrot',  'rice', 'cold_spin'),   ('steamed_br',  'corn',   'garlic_broc')),
    ('b3', ('soy_chicken', 'rice', 'garlic_broc'), ('braised_ht',  'potato', 'spin_tofu')),
]

days_zh = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

print('=' * 96)
print(f'{"Compass Health 一周餐单":^96}')
print(f'{"目标: 1771 kcal/天 | 蛋白质 140g | 脂肪 56g | 碳水 177g":^96}')
print('=' * 96)

week_totals = {'energy_kcal': 0, 'protein_g': 0, 'fat_g': 0, 'carbohydrate_g': 0, 'sodium_mg': 0}

for i, (bk, lunch_combo, dinner_combo) in enumerate(week):
    day = days_zh[i]
    bn, bp = B[bk]
    bt = total(bp)

    lm, ls, lsd = lunch_combo
    lunch_parts = list(D[lm][1])
    if ls:
        lunch_parts += S[ls][1]
    lunch_parts += D[lsd][1]
    lt = total(lunch_parts)
    lunch_str = D[lm][0]
    if ls:
        lunch_str += ' + ' + S[ls][0]
    lunch_str += ' + ' + D[lsd][0]

    dm, ds, dsd = dinner_combo
    dinner_parts = list(D[dm][1])
    if ds:
        dinner_parts += S[ds][1]
    dinner_parts += D[dsd][1]
    dt = total(dinner_parts)
    dinner_str = D[dm][0]
    if ds:
        dinner_str += ' + ' + S[ds][0]
    dinner_str += ' + ' + D[dsd][0]

    day_total = {k: bt[k] + lt[k] + dt[k] for k in bt}
    for k in week_totals:
        week_totals[k] += day_total[k]

    kcal_pct = day_total['energy_kcal'] / 1771 * 100
    p_pct = day_total['protein_g'] / 140 * 100

    print(f'\n{"─" * 96}')
    print(f'  {day}                                    kcal    蛋白    脂肪    碳水      钠')
    print(f'{"─" * 96}')
    print(f'  早餐  {bn:<36} {bt["energy_kcal"]:>5.0f}  {bt["protein_g"]:>5.1f}g  {bt["fat_g"]:>5.1f}g  {bt["carbohydrate_g"]:>5.1f}g  {bt["sodium_mg"]:>6.0f}mg')
    print(f'  午餐  {lunch_str:<36} {lt["energy_kcal"]:>5.0f}  {lt["protein_g"]:>5.1f}g  {lt["fat_g"]:>5.1f}g  {lt["carbohydrate_g"]:>5.1f}g  {lt["sodium_mg"]:>6.0f}mg')
    print(f'  晚餐  {dinner_str:<36} {dt["energy_kcal"]:>5.0f}  {dt["protein_g"]:>5.1f}g  {dt["fat_g"]:>5.1f}g  {dt["carbohydrate_g"]:>5.1f}g  {dt["sodium_mg"]:>6.0f}mg')
    print(f'  {"─" * 55}')
    print(f'  合计  {"":36} {day_total["energy_kcal"]:>5.0f}  {day_total["protein_g"]:>5.1f}g  {day_total["fat_g"]:>5.1f}g  {day_total["carbohydrate_g"]:>5.1f}g  {day_total["sodium_mg"]:>6.0f}mg')
    print(f'  达标  热量 {kcal_pct:.0f}%  蛋白 {p_pct:.0f}%')

print(f'\n{"=" * 96}')
avg = {k: week_totals[k] / 7 for k in week_totals}
print(f'  周均值:  {avg["energy_kcal"]:.0f} kcal  |  蛋白 {avg["protein_g"]:.0f}g  |  脂肪 {avg["fat_g"]:.0f}g  |  碳水 {avg["carbohydrate_g"]:.0f}g  |  钠 {avg["sodium_mg"]:.0f}mg')
print(f'  vs 目标: 热量 {avg["energy_kcal"]/1771*100:.0f}%  |  蛋白 {avg["protein_g"]/140*100:.0f}%  |  钠 {"OK" if avg["sodium_mg"] < 2300 else "偏高"} ({avg["sodium_mg"]:.0f}/2300mg)')
print(f'{"=" * 96}')

# Dish usage
dish_usage = Counter()
for bk, lc, dc in week:
    dish_usage[D[lc[0]][0]] += 1
    dish_usage[D[lc[2]][0]] += 1
    dish_usage[D[dc[0]][0]] += 1
    dish_usage[D[dc[2]][0]] += 1

print(f'\n菜品覆盖: {len(dish_usage)} / 15 道')
for name, cnt in dish_usage.most_common():
    mark = '★' if cnt >= 3 else ''
    print(f'  {name}: {cnt}x {mark}')

unused = set(D.keys()) - {lc[0] for _, lc, _ in week} - {lc[2] for _, lc, _ in week} - {dc[0] for _, _, dc in week} - {dc[2] for _, _, dc in week}
if unused:
    print(f'\n  未使用: {", ".join(D[k][0] for k in unused)}')

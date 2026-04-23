from datetime import timezone as _tz

# Configure logging before anything else imports `logging.getLogger(...)`,
# so module-level loggers pick up the dictConfig on first use.
import logging_config
logging_config.configure()

import logging
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import Base, engine, SessionLocal
from middleware import RequestContextMiddleware
from routers import (
    auth_routes, user_routes, water_routes, exercise_routes,
    diet_routes, condition_routes, stats_routes,
    recipe_routes, meal_plan_routes, admin_routes,
    daily_activity_routes, preferences_routes,
    meal_engine_routes, fixed_meal_routes,
)
from services import autofill
import models

log = logging.getLogger("compass.app")
scheduler = BackgroundScheduler(timezone=_tz.utc)

app = FastAPI(
    title="Compass Health API",
    description="Backend API for Compass Health — a bilingual health tracking app for Chinese immigrants in the US.",
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "null",   # file:// origin during local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Journey-ID"],
)

# Request-context middleware is registered AFTER CORS so the id/user filter
# runs on the innermost request handling. (Starlette applies middleware
# outside-in on entry, inside-out on exit — the one added last wraps
# closest to the endpoint.)
app.add_middleware(RequestContextMiddleware)


# ── Global exception handler ──────────────────────────────────────────────────
# Logs unhandled errors with traceback + the current request_id, then returns
# a generic 500 body — never leak stack traces to the client.
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    log.exception(
        "unhandled server error",
        extra={"path": request.url.path, "method": request.method},
    )
    from logging_config import request_id_var
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id_var.get() or "",
        },
    )

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_routes.router)
app.include_router(user_routes.router)
app.include_router(water_routes.router)
app.include_router(exercise_routes.router)
app.include_router(diet_routes.router)
app.include_router(condition_routes.router)
app.include_router(stats_routes.router)
app.include_router(recipe_routes.router)
app.include_router(meal_plan_routes.router)
app.include_router(admin_routes.router)
app.include_router(daily_activity_routes.router)
app.include_router(preferences_routes.router)
app.include_router(meal_engine_routes.router)
app.include_router(fixed_meal_routes.router)


# ── Built-in recipe seed data (mirrors DIET_RECIPES in diet.js) ───────────────
BUILTIN_RECIPES = [
    {
        "name": "凉拌鸡腿虾仁沙拉",
        "ingredients": "• 鸡腿：200 克\n• 虾仁：100 克\n• 米饭（熟）：280 克\n• 葱：15 克\n• 姜：10 克\n• 蒜：10 克\n• 芝麻：5 克\n• 柠檬：30 克（约半个）\n• 料酒：10 毫升\n• 生抽：20 毫升\n• 白醋：10 毫升\n• 香油：10 毫升",
        "steps": "1. 鸡腿去皮，虾仁洗净。\n2. 鸡腿冷水下锅，加葱、姜、料酒，煮15分钟。虾仁另锅煮2分钟。\n3. 蒜末加芝麻，淋热油激香。\n4. 加柠檬汁，倒入调味汁（盐、生抽2勺、白醋1勺、香油），拌匀。\n\n💡 保存：冷藏可保存2天，冷食即可。",
        "category": "凉拌",
    },
    {
        "name": "西兰花炒虾仁",
        "ingredients": "• 虾仁：200 克\n• 西兰花：200 克\n• 上海青：100 克\n• 米饭（熟）：300 克\n• 蒜：10 克\n• 葱：10 克\n• 淀粉：8 克\n• 香油：10 毫升\n• 酱油：10 毫升\n• 黑胡椒：2 克\n• 食用油：15 毫升\n• 蚝油：8 毫升\n• 生抽：10 毫升",
        "steps": "1. 西兰花焯水2分钟，捞出备用。\n2. 虾仁加黑胡椒腌制，中火翻炒至变色。\n3. 加入西兰花和调味汁（蒜末、葱花、盐、淀粉1勺、香油1勺、酱油1勺、少量水），翻炒均匀。\n\n💡 保存：冷藏可保存2天，平底锅或微波炉加热。",
        "category": "炒菜",
    },
    {
        "name": "西兰花炒牛肉",
        "ingredients": "• 牛肉片：200 克\n• 西兰花：200 克\n• 米饭（熟）：300 克\n• 蚝油：10 毫升\n• 老抽：8 毫升\n• 葱：10 克\n• 姜：10 克\n• 蛋清：30 克（约1个）\n• 食用油：15 毫升",
        "steps": "1. 牛肉切片，加蚝油、老抽拌匀，逐步加入60ml葱姜水搅拌，加盐，再加蛋清拌匀，淋少许油腌制15分钟。\n2. 西兰花焯水2分钟。\n3. 热油下锅，放入牛肉翻炒变色，加入西兰花翻炒均匀调味即可。\n\n💡 保存：冷藏可保存2天。",
        "category": "炒菜",
    },
    {
        "name": "蒜蓉粉丝娃娃菜蒸虾",
        "ingredients": "• 虾仁：150 克\n• 娃娃菜：200 克\n• 粉丝：60 克\n• 米饭（熟）：250 克\n• 蒜：15 克\n• 生抽：10 毫升\n• 蚝油：10 毫升\n• 糖：3 克\n• 食用油：10 毫升",
        "steps": "1. 娃娃菜铺底，粉丝温水泡15分钟，虾仁放在最上面。\n2. 蒜末加热油激香后，加生抽1勺、蚝油1勺、糖半勺调匀，淋在食材上。\n3. 盖盖，小火焖6分钟即可。\n\n💡 保存：冷藏可保存2天，蒸或微波加热。",
        "category": "蒸菜",
    },
    {
        "name": "土豆胡萝卜炖牛腩",
        "ingredients": "• 牛腩：220 克\n• 土豆：150 克\n• 胡萝卜：100 克\n• 米饭（熟）：250 克\n• 葱：15 克\n• 姜：10 克\n• 食用油：15 毫升",
        "steps": "1. 土豆、胡萝卜切块，牛肉切块备用。\n2. 牛肉冷水下锅，煮开撇去浮沫，捞出。\n3. 热油加姜片，翻炒牛肉上色，加入土豆、胡萝卜，倒入足量水，炖至软烂（约40分钟）。\n\n💡 保存：冷藏可保存3天，复热效果好。",
        "category": "炖菜",
    },
    {
        "name": "洋葱炒牛肉",
        "ingredients": "• 牛肉片：200 克\n• 洋葱：150 克（约1个）\n• 上海青：100 克\n• 米饭（熟）：280 克\n• 蚝油：10 毫升\n• 老抽：8 毫升\n• 生抽：10 毫升\n• 姜：10 克\n• 蒜：10 克\n• 蛋清：30 克（约1个）\n• 食用油：15 毫升",
        "steps": "1. 牛肉切片，加蚝油、老抽拌匀，逐步加60ml葱姜水，加盐、蛋清拌匀，淋油腌制15分钟。\n2. 热油炒牛肉至变色，盛出备用。\n3. 加姜、蒜、洋葱翻炒至微软，加生抽和蚝油，牛肉回锅翻炒均匀。\n\n💡 保存：冷藏可保存2天。",
        "category": "炒菜",
    },
    {
        "name": "柠檬鸡胸肉",
        "ingredients": "• 鸡胸肉：250 克\n• 上海青：100 克\n• 米饭（熟）：300 克\n• 花椒：3 克\n• 葱：15 克\n• 料酒：10 毫升\n• 蒜：10 克\n• 芝麻：5 克\n• 柠檬：30 克（约半个）\n• 洋葱：50 克\n• 生抽：20 毫升\n• 白醋：10 毫升\n• 香油：10 毫升\n• 食用油：10 毫升",
        "steps": "1. 冷水加花椒、葱、料酒煮开撇沫，煮5分钟后盖盖焖10分钟，鸡胸肉撕丝。\n2. 蒜末加芝麻，淋热油激香。\n3. 加柠檬汁、洋葱丝和调味汁（盐、生抽2勺、白醋1勺、香油）拌匀即可。\n\n💡 保存：冷藏可保存2天，冷食或常温食用。",
        "category": "凉拌",
    },
    {
        "name": "电饭煲焖鸡腿",
        "ingredients": "• 鸡腿：250 克\n• 苹果：100 克（约半个）\n• 洋葱：80 克\n• 米饭（熟）：260 克\n• 姜：10 克\n• 生抽：30 毫升\n• 老抽：20 毫升\n• 蚝油：10 毫升\n• 上海青：80 克\n• 食用油：8 毫升",
        "steps": "1. 鸡腿用姜片和腌料（生抽3勺、老抽2勺、蚝油1勺）腌制30分钟。\n2. 电饭煲中依次铺入：苹果片 → 洋葱丝 → 鸡腿 → 剩余苹果片。\n3. 按正常煮饭模式启动，完成后焖5分钟。\n\n💡 保存：冷藏可保存3天，微波加热。",
        "category": "焖菜",
    },
    {
        "name": "香菇炒鸡胸肉",
        "ingredients": "• 鸡胸肉：250 克\n• 香菇：150 克\n• 米饭（熟）：300 克\n• 葱：10 克\n• 姜：10 克\n• 蒜：10 克\n• 生抽：10 毫升\n• 酱油：5 毫升\n• 料酒：10 毫升\n• 黑胡椒：2 克\n• 盐：2 克\n• 食用油：12 毫升",
        "steps": "1. 鸡胸肉切片，加生抽1勺、酱油半勺、料酒1勺、盐、黑胡椒腌制15分钟。\n2. 热油爆香葱姜蒜，加入鸡胸肉翻炒至熟。\n3. 加入香菇继续翻炒2分钟，调味出锅。\n\n💡 保存：冷藏可保存2天。",
        "category": "炒菜",
    },
    {
        "name": "菠菜牛肉",
        "ingredients": "• 牛肉片：200 克\n• 菠菜：200 克\n• 金针菇：80 克\n• 米饭（熟）：300 克\n• 生抽：20 毫升\n• 料酒：10 毫升\n• 淀粉：8 克\n• 老抽：10 毫升\n• 蒜：10 克\n• 食用油：12 毫升",
        "steps": "1. 菠菜焯水1分钟，捞出挤干。\n2. 牛肉用生抽2勺、料酒1勺、淀粉1勺、老抽1勺腌制20分钟。\n3. 少量油下锅，放入金针菇和菠菜，加调味汁（生抽1勺、蒜末、半勺水），放入牛肉，盖盖焖10分钟。\n\n💡 保存：冷藏可保存2天，菠菜建议当天食用最佳。",
        "category": "炒菜",
    },
    {
        "name": "菠菜虾仁炒蛋",
        "ingredients": "• 虾仁：150 克\n• 菠菜：200 克\n• 鸡蛋：120 克（约2个）\n• 米饭（熟）：300 克\n• 蒜：10 克\n• 白醋：5 毫升\n• 生抽：20 毫升\n• 食用油：15 毫升\n• 盐：2 克",
        "steps": "1. 菠菜焯水1分钟，捞出备用。\n2. 鸡蛋加1勺白醋打散，热油炒散后盛出。\n3. 锅中加虾仁翻炒至变色，加蒜片、菠菜、鸡蛋。\n4. 加生抽2勺、盐调味翻炒均匀。\n\n💡 保存：冷藏可保存1天，建议当天食用。",
        "category": "炒菜",
    },
    {
        "name": "葱香牛肉",
        "ingredients": "• 牛肉片：220 克\n• 上海青：120 克\n• 米饭（熟）：280 克\n• 蒜：10 克\n• 葱：20 克\n• 糖：3 克\n• 芝麻：5 克\n• 香油：10 毫升\n• 黑胡椒：2 克\n• 盐：2 克\n• 食用油：12 毫升\n• 蚝油：8 毫升\n• 生抽：10 毫升",
        "steps": "1. 牛肉切片，加黑胡椒和盐调味。\n2. 牛肉平铺在锅中，加调味汁（蒜末、葱花、盐、糖、芝麻、香油）。\n3. 中小火焖6分钟，开盖翻炒均匀。\n\n💡 保存：冷藏可保存2天。",
        "category": "炒菜",
    },
    {
        "name": "牛腩西兰花虾仁组合",
        "ingredients": "• 牛腩：150 克\n• 虾仁：100 克\n• 西兰花：150 克\n• 土豆：80 克\n• 胡萝卜：60 克\n• 米饭（熟）：260 克\n• 葱：15 克\n• 姜：10 克\n• 蒜：10 克\n• 淀粉：5 克\n• 香油：8 毫升\n• 酱油：8 毫升\n• 黑胡椒：2 克\n• 食用油：15 毫升",
        "steps": "1. 牛腩切块焯水，加姜葱炖至软烂（约30分钟）。\n2. 西兰花焯水，虾仁加黑胡椒腌制后翻炒至变色。\n3. 将牛腩、土豆、胡萝卜一同炖煮至熟，最后加入西兰花和虾仁，调味出锅。\n\n💡 保存：冷藏可保存2天。",
        "category": "炖菜",
    },
]


def seed_builtin_recipes(db):
    existing_count = db.query(models.Recipe).filter(models.Recipe.is_builtin == True).count()
    if existing_count > 0:
        return  # already seeded
    for data in BUILTIN_RECIPES:
        db.add(models.Recipe(
            name=data["name"],
            ingredients=data["ingredients"],
            steps=data["steps"],
            category=data.get("category"),
            is_builtin=True,
            is_approved=True,
        ))
    db.commit()


# ── Column migrations for existing SQLite databases ───────────────────────────
def run_migrations():
    """Safely add new columns to existing tables (SQLite ALTER TABLE is additive)."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)

    def add_col_if_missing(table: str, col: str, col_def: str):
        existing = [c["name"] for c in inspector.get_columns(table)]
        if col not in existing:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                conn.commit()

    # users table — new columns
    if "users" in inspector.get_table_names():
        add_col_if_missing("users", "is_admin",          "BOOLEAN DEFAULT 0")
        add_col_if_missing("users", "target_weight_kg",  "FLOAT")

    # recipes table — meal-slot applicability + per-serving nutrition + slug index
    if "recipes" in inspector.get_table_names():
        add_col_if_missing("recipes", "meal_types",        "VARCHAR")
        add_col_if_missing("recipes", "calories",          "INTEGER")
        add_col_if_missing("recipes", "protein_g",         "FLOAT")
        add_col_if_missing("recipes", "carbs_g",           "FLOAT")
        add_col_if_missing("recipes", "fat_g",             "FLOAT")
        add_col_if_missing("recipes", "serving_g",         "FLOAT")
        add_col_if_missing("recipes", "ingredient_slugs",  "TEXT")

    # meal_plan_entries — pre-computed per-meal nutrition for auto-fill
    if "meal_plan_entries" in inspector.get_table_names():
        add_col_if_missing("meal_plan_entries", "portion_g", "FLOAT")
        add_col_if_missing("meal_plan_entries", "calories",  "INTEGER")
        add_col_if_missing("meal_plan_entries", "protein_g", "FLOAT")
        add_col_if_missing("meal_plan_entries", "carbs_g",   "FLOAT")
        add_col_if_missing("meal_plan_entries", "fat_g",     "FLOAT")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    log.info("compass-health starting up")
    Base.metadata.create_all(bind=engine)
    run_migrations()
    db = SessionLocal()
    try:
        seed_builtin_recipes(db)
    finally:
        db.close()

    # Auto-fill yesterday's meal-plan slots that the user left empty. Fires at
    # 00:00 UTC; users have the whole previous day up to midnight to confirm.
    scheduler.add_job(
        autofill.run_midnight_autofill,
        "cron",
        hour=0,
        minute=0,
        id="midnight_autofill",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
        log.info("scheduler started (midnight_autofill @ 00:00 UTC)")


@app.on_event("shutdown")
def on_shutdown():
    log.info("compass-health shutting down")
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/")
def health_check():
    return {"status": "ok", "version": "1.0.0", "service": "Compass Health API"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

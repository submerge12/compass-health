from datetime import datetime, timedelta, timezone

from tests.conftest import register


def test_refund_call_removes_the_charged_row_not_the_latest(client, clean_db):
    from database import SessionLocal
    import models
    from services import llm_quota

    register(client, "quota_owner")

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(username="quota_owner").one()

        charge = llm_quota.check_and_consume(db, user.id, llm_quota.POOL_NAME)
        charged_id = charge["call_log_id"]
        db.commit()

        later = models.LLMCallLog(
            user_id=user.id,
            kind=llm_quota.POOL_NAME,
            called_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        db.add(later)
        db.commit()
        later_id = later.id

        assert llm_quota.refund_call(
            db,
            charged_id,
            user_id=user.id,
            kind=llm_quota.POOL_NAME,
        ) is True
        db.commit()

        assert db.query(models.LLMCallLog).filter_by(id=charged_id).first() is None
        assert db.query(models.LLMCallLog).filter_by(id=later_id).first() is not None
    finally:
        db.close()

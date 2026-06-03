from app.tasks.celery_app import celery_app


@celery_app.task(name="generate_report_task")
def generate_report_task(conversation_id: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "status": "not_implemented",
        "message": "报告后台生成任务已预留，后续接入 reports 表和模板渲染。",
    }

from __future__ import annotations

from app.db.session import SessionLocal
from app.main import create_app
from app.services.fliggy_schedule_service import ensure_fliggy_schedule_started


app = create_app()


if __name__ == '__main__':
    runner = ensure_fliggy_schedule_started(session_factory=SessionLocal, logger=app.logger)
    print(f'Fliggy schedule runner started: {runner.is_alive()}')
    app.run(host='127.0.0.1', port=8000, debug=False, use_reloader=False)


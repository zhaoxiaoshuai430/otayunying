from __future__ import annotations

from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from app.api.errors import ApiError
from app.api.plugin_routes import plugin_bp
from app.api.routes import api_bp
from app.core.config import get_settings
from app.db.session import SessionLocal
API_GENERIC_ERROR_MESSAGE = 'Internal server error'
OPS_ASSISTANT_STATIC_DIR = Path(__file__).resolve().parent / 'static' / 'ops-assistant'


def create_app(*, session_factory=SessionLocal) -> Flask:
    settings = get_settings()

    app = Flask(__name__)

    secret_key = str(getattr(settings, 'flask_secret_key', '') or '').strip()
    env_name = str(getattr(settings, 'app_env', '') or '').strip().lower()
    if secret_key:
        app.secret_key = secret_key
    elif env_name in {'prod', 'production'}:
        raise RuntimeError('FLASK_SECRET_KEY must be set when APP_ENV=prod/production')
    else:
        app.secret_key = 'dev-unsafe-secret'
        app.logger.warning(
            'FLASK_SECRET_KEY is empty; using an insecure dev secret. Set FLASK_SECRET_KEY in backend/.env.'
        )

    app.config['SESSION_FACTORY'] = session_factory
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    if env_name in {'prod', 'production'}:
        app.config['SESSION_COOKIE_SECURE'] = True

    @app.before_request
    def _open_db_session() -> None:
        g.db = app.config['SESSION_FACTORY']()

    @app.teardown_request
    def _close_db_session(exc: BaseException | None) -> None:
        db = getattr(g, 'db', None)
        if db is None:
            return
        try:
            if exc is not None:
                try:
                    if hasattr(db, 'rollback'):
                        db.rollback()
                except Exception:
                    pass
        finally:
            if hasattr(db, 'close'):
                db.close()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return jsonify({'detail': exc.detail}), int(exc.status_code)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        status_code = int(exc.code or 500)
        return jsonify({'detail': exc.description}), status_code

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        app.logger.exception('Unhandled application error', exc_info=exc)
        return jsonify({'detail': API_GENERIC_ERROR_MESSAGE}), 500

    @app.route('/ops-assistant', methods=['GET'])
    @app.route('/ops-assistant/', methods=['GET'])
    def _serve_ops_assistant():
        response = send_from_directory(OPS_ASSISTANT_STATIC_DIR, 'index.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/ops-assistant/<path:filename>', methods=['GET'])
    def _serve_ops_assistant_asset(filename: str):
        response = send_from_directory(OPS_ASSISTANT_STATIC_DIR, filename)
        if filename.endswith('.html'):
            response.headers['Cache-Control'] = 'no-store'
        else:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    app.register_blueprint(api_bp)
    app.register_blueprint(plugin_bp)
    return app


app = create_app()

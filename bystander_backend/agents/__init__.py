def get_app():
    from .app import app

    return app


__all__ = ["get_app"]
